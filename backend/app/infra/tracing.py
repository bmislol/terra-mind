from contextvars import ContextVar

from langfuse import Langfuse
from langfuse.client import StatefulTraceClient

from app.core.config import Settings

# Set by RequestContextMiddleware for each non-healthz request.
# Consumed by agent/RAG/memory spans in Phase 2+ to attach child spans.
current_trace_var: ContextVar[StatefulTraceClient | None] = ContextVar(
    "current_trace", default=None
)


def init_langfuse(settings: Settings) -> Langfuse:
    """Initialise the Langfuse client and verify credentials.

    Raises RuntimeError("REFUSING TO BOOT: …") if the host is unreachable
    or the public/secret key pair is rejected.
    """
    client = Langfuse(
        public_key=settings.langfuse_public_key,
        secret_key=settings.langfuse_secret_key,
        host=settings.langfuse_host,
    )
    try:
        ok = client.auth_check()
    except Exception as exc:
        raise RuntimeError(
            "REFUSING TO BOOT: Langfuse unreachable at "
            f"{settings.langfuse_host} — {exc}"
        ) from exc

    if not ok:
        raise RuntimeError(
            "REFUSING TO BOOT: Langfuse at "
            f"{settings.langfuse_host} rejected credentials"
        )

    return client
