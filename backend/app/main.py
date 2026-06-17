import os

from app.core.logging import configure_logging

# Must run before FastAPI is instantiated so uvicorn's pre-lifespan startup
# logs (banner, "Started server process") flow through the JSON formatter.
configure_logging()

from fastapi import FastAPI  # noqa: E402

from app.api.admin import admin_router  # noqa: E402
from app.api.auth import auth_router  # noqa: E402
from app.api.bot import bot_router  # noqa: E402
from app.api.me import me_router  # noqa: E402
from app.api.middleware import RequestContextMiddleware  # noqa: E402
from app.api.versions import versions_router  # noqa: E402
from app.core.cors import add_cors  # noqa: E402
from app.core.lifespan import lifespan  # noqa: E402

app = FastAPI(lifespan=lifespan)

# CORS for the browser portal (Phase 5.1). Read straight from the env (default
# the compose-local portal origin) rather than the full Settings: main.py is
# imported by lightweight tests without the DB/Vault env that Settings requires,
# and middleware must be wired at import time. Never "*" — see add_cors.
_cors_origins = [
    o.strip()
    for o in os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:5173").split(",")
    if o.strip()
]
app.add_middleware(RequestContextMiddleware)
add_cors(app, _cors_origins)
app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(bot_router)
app.include_router(me_router)
app.include_router(versions_router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
