"""Right-to-erasure orchestration (ARCH §4, SECURITY §3/§6).

The **service** sets the tenant's RLS context and owns the deletes + Redis purge
+ audit; the endpoint only passes the authenticated tenant_id; the repositories
run the SQL deletes under the context.

Guests included: a guest that asks for erasure **gets it** — the same purge as a
player. The "erasure is a no-op for guests" wording in SECURITY §4 meant guests
carry no persistence *guarantee* (TTL-bound, ephemeral), not that erasure does
nothing; guests do write session/message rows (commit 2), so erasure removes
them. (Reconciled in SECURITY §4.)
"""

from __future__ import annotations

from uuid import UUID

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.repositories import messages as messages_repo
from app.repositories import sessions as sessions_repo
from app.repositories.audit import write_audit
from app.services.rls import set_tenant_context


async def erase_tenant(
    *,
    tenant_id: UUID,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
) -> int:
    """Delete the tenant's messages + sessions (under their RLS context) + Redis
    session keys; write a ``tenant.erased`` audit row. Returns rows deleted."""
    async with session_factory() as session:
        await set_tenant_context(session, tenant_id)
        # Messages first (FK → sessions), then sessions — both RLS-scoped.
        deleted = await messages_repo.delete_for_current_tenant(session)
        deleted += await sessions_repo.delete_for_current_tenant(session)
        await write_audit(
            session,
            actor=tenant_id,
            action="tenant.erased",
            target=str(tenant_id),
            meta={"deleted_rows": deleted},
        )
        await session.commit()

    # Purge the tenant's Redis history keys. session_ids aren't indexed anywhere,
    # so SCAN the tenant-namespaced prefix (cursor-based, non-blocking unlike
    # KEYS) — the prefix scopes the match to exactly this tenant's keys.
    async for key in redis.scan_iter(match=f"session:{tenant_id}:*"):
        await redis.delete(key)

    return deleted
