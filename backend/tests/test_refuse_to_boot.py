import textwrap
from pathlib import Path

import pytest

from app.core.config import Settings
from app.core.lifespan import check_eval_thresholds
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
