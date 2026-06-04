from app.core.logging import configure_logging

# Must run before FastAPI is instantiated so uvicorn's pre-lifespan startup
# logs (banner, "Started server process") flow through the JSON formatter.
configure_logging()

from fastapi import FastAPI  # noqa: E402

from app.api.middleware import RequestContextMiddleware  # noqa: E402
from app.core.lifespan import lifespan  # noqa: E402

app = FastAPI(lifespan=lifespan)
app.add_middleware(RequestContextMiddleware)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
