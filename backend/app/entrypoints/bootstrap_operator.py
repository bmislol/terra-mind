"""Bootstrap the first operator (RUNBOOK §3).

Run host-side against ``DATABASE_URL`` after ``migrate`` has applied the schema —
NOT through the API or Vault:

    BOOTSTRAP_EMAIL=... BOOTSTRAP_PASSWORD=... DATABASE_URL=... \\
        python -m app.entrypoints.bootstrap_operator

Why an out-of-band script and not an endpoint: normal registration is
**privilege-safe** — `UserManager.create(..., safe=True)` / the register router
strip `is_superuser`, so a player can never self-elevate (SECURITY §5). Making
the FIRST operator therefore has to construct the row directly, out of band.

Idempotent: promotes an existing tenant to operator, or creates one if absent —
safe to re-run.
"""

from __future__ import annotations

import asyncio
import os
from uuid import UUID, uuid4

from fastapi_users_db_sqlalchemy import SQLAlchemyUserDatabase
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.models import Tenant
from app.infra.auth import UserManager


async def bootstrap_operator(
    *,
    email: str,
    password: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> bool:
    """Ensure an operator account exists. Returns True if a new operator was
    created, False if an existing tenant was promoted (or was already operator).

    The row is built with ``is_superuser=True`` **directly** — the privilege-safe
    create/register path can't, by design.
    """
    async with session_factory() as session:
        user_db: SQLAlchemyUserDatabase[Tenant, UUID] = SQLAlchemyUserDatabase(
            session, Tenant
        )
        existing = await user_db.get_by_email(email)
        if existing is not None:
            if not existing.is_superuser:
                existing.is_superuser = True
                await session.commit()
            return False

        # token_secret is only for the (unmounted) reset/verify flows — not used
        # here; we construct UserManager to reuse the project's argon2id hasher.
        user_manager = UserManager(user_db, token_secret="unused-bootstrap-secret")
        hashed = user_manager.password_helper.hash(password)
        session.add(
            Tenant(
                id=uuid4(),
                email=email,
                hashed_password=hashed,
                is_active=True,
                is_superuser=True,
            )
        )
        await session.commit()
        return True


async def _main() -> None:
    email = os.environ["BOOTSTRAP_EMAIL"]
    password = os.environ["BOOTSTRAP_PASSWORD"]
    engine = create_async_engine(os.environ["DATABASE_URL"])
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        created = await bootstrap_operator(
            email=email, password=password, session_factory=session_factory
        )
        action = "created" if created else "promoted (or already operator)"
        print(f"operator {action}: {email}")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(_main())
