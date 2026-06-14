import textwrap
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.lifespan import (
    _load_prompts,
    _validate_anthropic_key,
    check_eval_thresholds,
    check_redis,
)
from app.core.prompts import LoadedPrompts
from app.infra.tracing import init_langfuse
from app.infra.vault import load_secrets

# ── Vault ─────────────────────────────────────────────────────────────────────


def test_vault_unreachable_raises() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost:5432/x",
        vault_addr="http://localhost:19999",
        vault_token="fake-token",
    )
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        load_secrets(settings, timeout=1)


# ── Langfuse ──────────────────────────────────────────────────────────────────


def test_langfuse_unreachable_raises() -> None:
    settings = Settings(
        database_url="postgresql+asyncpg://x:x@localhost:5432/x",
        vault_addr="http://localhost:19999",
        vault_token="fake-token",
        langfuse_public_key="pk-lf-fake",
        langfuse_secret_key="sk-lf-fake",
        langfuse_host="http://localhost:19999",
    )
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        init_langfuse(settings)


# ── Eval thresholds ───────────────────────────────────────────────────────────


def test_eval_thresholds_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        check_eval_thresholds(str(tmp_path / "nonexistent.yaml"))


def test_eval_thresholds_unparseable_raises(tmp_path: Path) -> None:
    bad = tmp_path / "thresholds.yaml"
    bad.write_text("{broken: yaml: content: [}")
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        check_eval_thresholds(str(bad))


def test_eval_thresholds_non_numeric_non_pending_raises(tmp_path: Path) -> None:
    bad = tmp_path / "thresholds.yaml"
    bad.write_text("rag:\n  hit_at_k_min: broken\n")
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        check_eval_thresholds(str(bad))


def test_eval_thresholds_negative_value_raises(tmp_path: Path) -> None:
    bad = tmp_path / "thresholds.yaml"
    bad.write_text("rag:\n  hit_at_k_min: -1\n")
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        check_eval_thresholds(str(bad))


def test_eval_thresholds_pending_values_pass(tmp_path: Path) -> None:
    ok = tmp_path / "thresholds.yaml"
    ok.write_text(
        textwrap.dedent("""\
        rag:
          hit_at_k_min: PENDING
          mrr_at_10_min: PENDING
        redteam:
          max_successful_injections: PENDING
    """)
    )
    check_eval_thresholds(str(ok))  # must not raise


def test_eval_thresholds_zero_passes_for_redteam_key(tmp_path: Path) -> None:
    ok = tmp_path / "thresholds.yaml"
    ok.write_text("redteam:\n  max_successful_injections: 0\n")
    check_eval_thresholds(str(ok))  # must not raise — 0 is a valid strict floor


def test_eval_thresholds_rag_min_zero_refuses(tmp_path: Path) -> None:
    bad = tmp_path / "thresholds.yaml"
    bad.write_text("rag:\n  hit_at_k_min: 0\n")
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        check_eval_thresholds(str(bad))


def test_eval_thresholds_rag_max_zero_refuses(tmp_path: Path) -> None:
    bad = tmp_path / "thresholds.yaml"
    bad.write_text("rag:\n  p95_latency_ms_max: 0\n")
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        check_eval_thresholds(str(bad))


# ── Redis ─────────────────────────────────────────────────────────────────────


async def test_redis_unreachable_raises() -> None:
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        await check_redis("redis://localhost:19999/0")


# ── Anthropic key validation ──────────────────────────────────────────────────


def test_validate_anthropic_key_empty_refuses() -> None:
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        _validate_anthropic_key("")


def test_validate_anthropic_key_placeholder_refuses() -> None:
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        _validate_anthropic_key("CHANGE_ME")


def test_validate_anthropic_key_valid_passes() -> None:
    _validate_anthropic_key("sk-ant-fake-key")  # must not raise


# ── Prompts loading ───────────────────────────────────────────────────────────

_LONG_CONTENT = "A" * 100  # exactly 100 chars — valid


def test_load_prompts_missing_router_refuses(tmp_path: Path) -> None:
    (tmp_path / "faq_answer.md").write_text(_LONG_CONTENT, encoding="utf-8")
    # router.md absent
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        _load_prompts(tmp_path)


def test_load_prompts_missing_faq_answer_refuses(tmp_path: Path) -> None:
    (tmp_path / "router.md").write_text(_LONG_CONTENT, encoding="utf-8")
    # faq_answer.md absent
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        _load_prompts(tmp_path)


def test_load_prompts_router_empty_refuses(tmp_path: Path) -> None:
    (tmp_path / "router.md").write_text("too short", encoding="utf-8")
    (tmp_path / "faq_answer.md").write_text(_LONG_CONTENT, encoding="utf-8")
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        _load_prompts(tmp_path)


def test_load_prompts_faq_empty_refuses(tmp_path: Path) -> None:
    (tmp_path / "router.md").write_text(_LONG_CONTENT, encoding="utf-8")
    (tmp_path / "faq_answer.md").write_text("too short", encoding="utf-8")
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        _load_prompts(tmp_path)


def test_load_prompts_missing_agent_system_refuses(tmp_path: Path) -> None:
    (tmp_path / "router.md").write_text(_LONG_CONTENT, encoding="utf-8")
    (tmp_path / "faq_answer.md").write_text(_LONG_CONTENT, encoding="utf-8")
    # agent_system.md absent
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        _load_prompts(tmp_path)


def test_load_prompts_agent_system_empty_refuses(tmp_path: Path) -> None:
    (tmp_path / "router.md").write_text(_LONG_CONTENT, encoding="utf-8")
    (tmp_path / "faq_answer.md").write_text(_LONG_CONTENT, encoding="utf-8")
    (tmp_path / "agent_system.md").write_text("too short", encoding="utf-8")
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        _load_prompts(tmp_path)


def test_load_prompts_missing_class_fallback_refuses(tmp_path: Path) -> None:
    (tmp_path / "router.md").write_text(_LONG_CONTENT, encoding="utf-8")
    (tmp_path / "faq_answer.md").write_text(_LONG_CONTENT, encoding="utf-8")
    (tmp_path / "agent_system.md").write_text(_LONG_CONTENT, encoding="utf-8")
    # class_fallback.md absent
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        _load_prompts(tmp_path)


def test_load_prompts_class_fallback_empty_refuses(tmp_path: Path) -> None:
    (tmp_path / "router.md").write_text(_LONG_CONTENT, encoding="utf-8")
    (tmp_path / "faq_answer.md").write_text(_LONG_CONTENT, encoding="utf-8")
    (tmp_path / "agent_system.md").write_text(_LONG_CONTENT, encoding="utf-8")
    (tmp_path / "class_fallback.md").write_text("too short", encoding="utf-8")
    with pytest.raises(RuntimeError, match="REFUSING TO BOOT"):
        _load_prompts(tmp_path)


def test_load_prompts_all_present_passes(tmp_path: Path) -> None:
    router_text = "R" * 120
    faq_text = "F" * 150
    agent_text = "A" * 110
    fallback_text = "C" * 130
    (tmp_path / "router.md").write_text(router_text, encoding="utf-8")
    (tmp_path / "faq_answer.md").write_text(faq_text, encoding="utf-8")
    (tmp_path / "agent_system.md").write_text(agent_text, encoding="utf-8")
    (tmp_path / "class_fallback.md").write_text(fallback_text, encoding="utf-8")
    result = _load_prompts(tmp_path)
    assert isinstance(result, LoadedPrompts)
    assert result.router == router_text
    assert result.faq_answer == faq_text
    assert result.agent_system == agent_text
    assert result.class_fallback == fallback_text


def test_eval_thresholds_real_values_pass(tmp_path: Path) -> None:
    ok = tmp_path / "thresholds.yaml"
    ok.write_text(
        textwrap.dedent("""\
        rag:
          hit_at_k_min: 0.75
          mrr_at_10_min: 0.60
        redteam:
          max_successful_injections: 0
    """)
    )
    check_eval_thresholds(str(ok))  # must not raise
