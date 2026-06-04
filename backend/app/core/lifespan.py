from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.db.session import make_session_factory
from app.infra.vault import load_secrets


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()

    # ── Vault ──────────────────────────────────────────────────────────────────
    # Raises RuntimeError("REFUSING TO BOOT: …") if unreachable or unauthenticated.
    secrets = load_secrets(settings)
    app.state.secrets = secrets

    # ── Database ───────────────────────────────────────────────────────────────
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        await engine.dispose()
        raise RuntimeError(
            f"REFUSING TO BOOT: database unreachable at {settings.database_url} — {exc}"
        ) from exc

    app.state.db_engine = engine
    app.state.session_factory = make_session_factory(engine)

    yield

    await engine.dispose()
