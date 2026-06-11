from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.core.prompts import LoadedPrompts
from app.core.threshold_directions import zero_is_valid_for_key
from app.db.session import make_session_factory
from app.infra.anthropic import AnthropicClient
from app.infra.tracing import init_langfuse
from app.infra.vault import load_secrets
from app.rag.embedder import Embedder
from app.rag.pipeline import RetrievalPipeline

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _walk_thresholds(node: Any, prefix: str) -> None:  # noqa: ANN401
    """Recursively validate threshold values.

    Rules:
    - "PENDING" passes (intentional unfilled marker).
    - Any other non-numeric value refuses.
    - Any numeric value < 0 refuses.
    - 0 is valid only for keys where zero_is_valid_for_key() returns True
      (e.g. redteam.max_successful_injections). For _min and _max keys, 0
      means "no quality gate" and refuses.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            _walk_thresholds(v, f"{prefix}.{k}" if prefix else k)
    elif node == "PENDING":
        pass
    elif isinstance(node, (int, float)):
        if node < 0:
            raise RuntimeError(
                f"REFUSING TO BOOT: eval_thresholds.yaml — {prefix}={node} is negative"
            )
        leaf_key = prefix.rsplit(".", 1)[-1]
        if node == 0 and not zero_is_valid_for_key(leaf_key):
            raise RuntimeError(
                f"REFUSING TO BOOT: eval_thresholds.yaml — {prefix}=0 "
                "sets no quality floor (use PENDING if not yet measured)"
            )
    else:
        raise RuntimeError(
            f"REFUSING TO BOOT: eval_thresholds.yaml — "
            f"{prefix}={node!r} is not a positive number or 'PENDING'"
        )


def _validate_anthropic_key(key: str) -> None:
    if not key or not key.startswith("sk-ant-"):
        raise RuntimeError(
            "REFUSING TO BOOT: Anthropic API key is missing or placeholder — "
            "seed a real sk-ant-… key in Vault at "
            "secret/terra-mind/anthropic (field: api_key)"
        )


def _load_prompts(prompts_dir: Path) -> LoadedPrompts:
    loaded: dict[str, str] = {}
    for attr, filename in (("router", "router.md"), ("faq_answer", "faq_answer.md")):
        path = prompts_dir / filename
        if not path.exists():
            raise RuntimeError(f"REFUSING TO BOOT: prompt file missing — {path}")
        content = path.read_text(encoding="utf-8")
        if len(content.strip()) < 100:
            raise RuntimeError(
                f"REFUSING TO BOOT: prompt file {path.name} is empty or too short "
                f"(got {len(content.strip())} chars, need ≥ 100)"
            )
        loaded[attr] = content
    return LoadedPrompts(router=loaded["router"], faq_answer=loaded["faq_answer"])


def check_eval_thresholds(path: str) -> None:
    resolved = Path(path)
    if not resolved.exists():
        raise RuntimeError(
            f"REFUSING TO BOOT: eval_thresholds.yaml not found at {resolved}"
        )
    try:
        data = yaml.safe_load(resolved.read_text())
    except yaml.YAMLError as exc:
        raise RuntimeError(
            f"REFUSING TO BOOT: eval_thresholds.yaml is unparseable — {exc}"
        ) from exc
    _walk_thresholds(data, "")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()

    # ── Vault ──────────────────────────────────────────────────────────────────
    secrets = load_secrets(settings)
    app.state.secrets = secrets

    # ── Anthropic ──────────────────────────────────────────────────────────────
    _validate_anthropic_key(secrets.anthropic_api_key)
    app.state.anthropic = AnthropicClient(api_key=secrets.anthropic_api_key)

    # ── Prompts ────────────────────────────────────────────────────────────────
    app.state.prompts = _load_prompts(_PROMPTS_DIR)

    # ── Eval thresholds ────────────────────────────────────────────────────────
    check_eval_thresholds(settings.eval_thresholds_path)

    # ── Langfuse ───────────────────────────────────────────────────────────────
    langfuse = init_langfuse(settings)
    app.state.langfuse = langfuse

    # ── Database ───────────────────────────────────────────────────────────────
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        raise RuntimeError(
            f"REFUSING TO BOOT: database unreachable at {settings.database_url} — {exc}"
        ) from exc

    app.state.db_engine = engine
    app.state.session_factory = make_session_factory(engine)

    # ── Embedding model + retrieval pipeline ───────────────────────────────────
    # Embedder loads ~90 MB of model weights — done once at startup, never
    # per-query.  RetrievalPipeline holds no extra state beyond these two deps.
    embedding_model = Embedder()
    app.state.embedding_model = embedding_model
    app.state.retrieval_pipeline = RetrievalPipeline(
        session_factory=app.state.session_factory,
        embedder=embedding_model,
    )

    yield

    await engine.dispose()
    langfuse.flush()
