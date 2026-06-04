import json
import logging

from app.core.logging import HealthzFilter, JSONFormatter


def _make_record(msg: str, name: str = "app.test") -> logging.LogRecord:
    record = logging.LogRecord(
        name=name,
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg=msg,
        args=(),
        exc_info=None,
    )
    return record


def test_json_formatter_produces_valid_json() -> None:
    formatter = JSONFormatter()
    record = _make_record("hello world")
    output = formatter.format(record)
    parsed = json.loads(output)
    assert parsed["message"] == "hello world"
    assert parsed["level"] == "info"
    assert parsed["service"] == "api"
    assert parsed["event"] == "app.test"
    assert "timestamp" in parsed


def test_json_formatter_has_all_arch_keys() -> None:
    formatter = JSONFormatter()
    record = _make_record("check keys")
    parsed = json.loads(formatter.format(record))
    for key in (
        "timestamp",
        "level",
        "service",
        "event",
        "message",
        "request_id",
        "trace_id",
        "tenant_id",
    ):
        assert key in parsed, f"missing key: {key}"


def test_json_formatter_contextvars_default_empty() -> None:
    formatter = JSONFormatter()
    record = _make_record("ctx check")
    parsed = json.loads(formatter.format(record))
    assert parsed["request_id"] == ""
    assert parsed["trace_id"] == ""
    assert parsed["tenant_id"] == ""


def test_healthz_filter_suppresses_healthz() -> None:
    f = HealthzFilter()
    record = _make_record("GET /healthz HTTP/1.1 200")
    assert f.filter(record) is False


def test_healthz_filter_passes_other_paths() -> None:
    f = HealthzFilter()
    assert f.filter(_make_record("GET /docs HTTP/1.1 200")) is True
    assert f.filter(_make_record("POST /bot/ask HTTP/1.1 200")) is True
    assert f.filter(_make_record("application startup complete")) is True
