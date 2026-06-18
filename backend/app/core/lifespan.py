import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.agent.class_detection import ItemClassifier
from app.core.config import get_settings
from app.core.prompts import LoadedPrompts
from app.core.threshold_directions import zero_is_valid_for_key
from app.db.session import make_session_factory
from app.infra.anthropic import AnthropicClient
from app.infra.tracing import init_langfuse
from app.infra.vault import load_secrets
from app.jobs.queue import redis_connection, rerag_queue
from app.rag.embedder import Embedder
from app.rag.pipeline import RetrievalPipeline

_log = logging.getLogger(__name__)

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


_PROMPT_FILES: tuple[tuple[str, str], ...] = (
    ("router", "router.md"),
    ("faq_answer", "faq_answer.md"),
    ("agent_system", "agent_system.md"),
    ("class_fallback", "class_fallback.md"),
    ("guardrail_judge", "guardrail_judge.md"),
)


def _load_prompts(prompts_dir: Path) -> LoadedPrompts:
    loaded: dict[str, str] = {}
    for attr, filename in _PROMPT_FILES:
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
    return LoadedPrompts(
        router=loaded["router"],
        faq_answer=loaded["faq_answer"],
        agent_system=loaded["agent_system"],
        class_fallback=loaded["class_fallback"],
        guardrail_judge=loaded["guardrail_judge"],
    )


async def check_redis(url: str) -> Redis:
    """Connect to Redis and PING; refuse to boot if unreachable (D-029 denylist).

    Returns the live client (cached on app.state). decode_responses=True so the
    denylist reads back ``str`` rather than ``bytes``.
    """
    client: Redis = Redis.from_url(url, decode_responses=True)
    try:
        await client.ping()
    except Exception as exc:
        await client.aclose()
        raise RuntimeError(
            f"REFUSING TO BOOT: Redis unreachable at {url} — {exc}"
        ) from exc
    return client


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

    # ── Redis (session-revocation denylist, D-029; short-term memory later) ─────
    redis_client = await check_redis(settings.redis_url)
    app.state.redis = redis_client

    # ── Re-rag job queue (RQ on the existing Redis, D-033) ─────────────────────
    # A SYNC connection (RQ requires sync) for enqueuing the operator re-rag job
    # and acquiring the single-job lock — distinct from the async app.state.redis
    # above. Redis.from_url is lazy; the check_redis above already proved Redis up.
    app.state.rerag_queue = rerag_queue(redis_connection(settings.redis_url))

    # ── Embedding model + retrieval pipeline ───────────────────────────────────
    # Embedder loads ~90 MB of model weights — done once at startup, never
    # per-query.  RetrievalPipeline holds no extra state beyond these two deps.
    embedding_model = Embedder()
    app.state.embedding_model = embedding_model
    app.state.retrieval_pipeline = RetrievalPipeline(
        session_factory=app.state.session_factory,
        embedder=embedding_model,
    )

    # ── Item classifier (class detection, D-009) ───────────────────────────────
    # Builds the Cargo-backed weapon index once at startup; refuse-to-boot if the
    # Cargo items file is missing or truncated.  Curated armor map is in-code.
    item_classifier = ItemClassifier.from_cargo_file(settings.cargo_items_path)
    app.state.item_classifier = item_classifier
    # Permanent evidence (logs + demo) that the Cargo-backed classifier loaded.
    # 0 cargo weapons here = lifespan did not load Cargo (stale image / wrong path).
    _log.info(
        "item_classifier ready: %d cargo weapons (%d cargo items)",
        item_classifier.cargo_weapon_count,
        item_classifier.cargo_item_count,
    )

    yield

    await redis_client.aclose()
    await engine.dispose()
    langfuse.flush()
