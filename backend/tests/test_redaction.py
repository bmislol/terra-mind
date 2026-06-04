import logging

from app.infra.redaction import RedactionFilter, redact

_REDACTED = "[REDACTED]"


# ── Pattern coverage ──────────────────────────────────────────────────────────


def test_anthropic_key_redacted() -> None:
    assert redact("key=sk-ant-api03-abc123XYZ") == f"key={_REDACTED}"


def test_anthropic_fires_before_generic_sk() -> None:
    # Both patterns match sk-ant-… but Anthropic must win (most-specific first).
    result = redact("sk-ant-api03-abcdefghijklmnopqrstu")
    assert result == _REDACTED
    assert "sk-ant" not in result


def test_generic_bearer_redacted() -> None:
    # 20+ chars after "sk-", not starting with "ant-"
    assert redact("sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ") == _REDACTED


def test_generic_bearer_too_short_not_redacted() -> None:
    # Fewer than 20 chars after sk- → should NOT match generic bearer pattern.
    assert redact("sk-short") == "sk-short"


def test_vault_token_redacted() -> None:
    assert redact("token=hvs.CAESIAbcdef1234") == f"token={_REDACTED}"


def test_postgres_dsn_redacted() -> None:
    result = redact("postgresql://terramind:s3cr3t@db:5432/terramind")
    assert result == _REDACTED


def test_jwt_redacted() -> None:
    # Three segments each ≥ 10 chars (realistic JWT structure)
    fake_jwt = "eyJhbGciOiJIUzI1NiJ9.eyJ0ZW5hbnRfaWQiOiJ4eXoifQ.SflKxwRJSMeKKF2QT4"
    assert redact(fake_jwt) == _REDACTED


def test_email_redacted() -> None:
    assert redact("contact: user@example.com") == f"contact: {_REDACTED}"


# ── JWT false-positive boundary ───────────────────────────────────────────────


def test_short_dotted_path_not_redacted() -> None:
    # No three consecutive segments of ≥ 10 chars — must pass through unchanged.
    path = "app.services.router.classify_question"
    assert redact(path) == path


def test_python_logger_name_not_redacted() -> None:
    assert redact("app.infra.vault") == "app.infra.vault"


# ── RedactionFilter integration ───────────────────────────────────────────────


def test_redaction_filter_mutates_record_msg() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="key is sk-ant-api03-FAKEFAKEFAKE",
        args=(),
        exc_info=None,
    )
    f = RedactionFilter()
    result = f.filter(record)
    assert result is True
    assert "sk-ant" not in record.msg
    assert _REDACTED in record.msg


def test_redaction_filter_clears_args() -> None:
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="value=%s",
        args=("sk-ant-api03-FAKEFAKEFAKE",),
        exc_info=None,
    )
    RedactionFilter().filter(record)
    # args cleared so formatter won't double-format
    assert record.args == ()
    assert _REDACTED in record.msg


def test_redaction_filter_via_log_handler() -> None:
    """Secret logged through a real handler+filter must not appear in output."""
    import io

    from app.core.logging import JSONFormatter

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(RedactionFilter())
    handler.setFormatter(JSONFormatter())

    logger = logging.getLogger("test.redaction.integration")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    # sk-ant-… matches the Anthropic pattern; the generic sk- pattern requires
    # ≥20 chars after "sk-", so the test value is deliberately Anthropic-prefixed.
    logger.info("api_key=sk-ant-api03-FAKE-not-real")

    output = stream.getvalue()
    assert "sk-ant-api03-FAKE-not-real" not in output
    assert _REDACTED in output
