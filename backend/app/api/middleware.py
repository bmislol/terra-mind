from uuid import uuid4

from langfuse import Langfuse
from langfuse.client import StatefulTraceClient
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import request_id_var, tenant_id_var, trace_id_var
from app.infra.tracing import current_trace_var


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Sets per-request contextvars and opens a Langfuse trace.

    - Always generates request_id and adds X-Request-ID to the response.
    - Skips Langfuse trace creation for /healthz to avoid flooding the UI.
    - tenant_id is empty in Phase 1.6; populated by the auth dependency in 4.1.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = str(uuid4())
        request_id_var.set(request_id)
        tenant_id_var.set("")

        trace: StatefulTraceClient | None = None
        langfuse: Langfuse | None = None

        if request.url.path != "/healthz":
            langfuse = request.app.state.langfuse
            trace = langfuse.trace(
                name="http_request",
                metadata={"path": str(request.url.path), "method": request.method},
            )
            trace_id_var.set(trace.id)
            current_trace_var.set(trace)
        else:
            trace_id_var.set("")
            current_trace_var.set(None)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id

        if trace is not None and langfuse is not None:
            trace.update(metadata={"status_code": response.status_code})
            langfuse.flush()

        return response
