import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

from app.infra.redaction import RedactionFilter

# Per-request context, populated by RequestContextMiddleware.
# Default to "" so the formatter works cleanly outside request scope.
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
tenant_id_var: ContextVar[str] = ContextVar("tenant_id", default="")


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": record.levelname.lower(),
                "service": "api",
                "event": record.name,
                "message": record.getMessage(),
                "request_id": request_id_var.get(),
                "trace_id": trace_id_var.get(),
                "tenant_id": tenant_id_var.get(),
            }
        )


class HealthzFilter(logging.Filter):
    """Suppresses uvicorn access-log lines for /healthz to reduce UI noise."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/healthz" not in record.getMessage()


def configure_logging() -> None:
    """Configure the root logger with JSON output + redaction.

    Must be called at module-import time in app/main.py (before FastAPI is
    instantiated) so that uvicorn's pre-lifespan startup logs are formatted.
    """
    handler = logging.StreamHandler()
    handler.addFilter(RedactionFilter())
    handler.setFormatter(JSONFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)

    # Take over uvicorn's loggers so startup/request logs are also JSON.
    # uvicorn sets propagate=False on its loggers, so the root handler
    # alone is not enough — each must be reconfigured explicitly.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uv = logging.getLogger(name)
        uv.handlers = [handler]
        uv.propagate = False

    # HealthzFilter on uvicorn.access only — /healthz still gets an
    # X-Request-ID header and trace context; we're suppressing only the
    # access log line to avoid flooding the trace UI.
    logging.getLogger("uvicorn.access").addFilter(HealthzFilter())
