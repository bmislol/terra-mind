import logging
import re

# Patterns compiled once at module load, most-specific first.
# Order matters: sk-ant- must precede the generic sk- pattern
# so Anthropic keys are caught before the broader bearer token rule.
_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"sk-ant-[A-Za-z0-9\-]+"),
    re.compile(r"sk-[A-Za-z0-9\-]{20,}"),
    re.compile(r"hvs\.[A-Za-z0-9]+"),
    re.compile(r"postgresql://[^\s]+"),
    re.compile(r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
]

_REPLACEMENT = "[REDACTED]"


def redact(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(_REPLACEMENT, text)
    return text


class RedactionFilter(logging.Filter):
    """Redacts secrets from log records before the formatter runs.

    Calls record.getMessage() to fully format the message (substituting any
    %-style args), redacts the result, then stores it back on record.msg and
    clears record.args so the formatter doesn't double-format.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        return True


def redact_metadata(metadata: dict[str, object]) -> dict[str, object]:
    """Redact string values in a flat metadata dict before Langfuse span writes.

    Stub in Phase 1.6 — called from agent/RAG spans in Phase 2+.
    """
    return {k: redact(v) if isinstance(v, str) else v for k, v in metadata.items()}
