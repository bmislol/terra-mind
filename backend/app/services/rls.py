"""RLS tenant-context setter (the headline security control, ARCH §4).

Lives in the **service layer only** — never api/ or repositories/. A request's
service sets the tenant context from the authenticated access-JWT's tenant_id
*before* any tenant-scoped repository query; Postgres RLS policies on
``sessions``/``messages`` then filter to that tenant (a query can never cross
``tenant_id``).

Transaction-local by design: ``set_config(..., is_local => true)`` is the
``SET LOCAL`` equivalent — the setting lives only until the end of the current
transaction and is reset when the connection returns to the pool, so a tenant
context can never leak across pooled connections / requests. The protected
queries MUST run in the same transaction as this call (no intervening commit).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SET_TENANT = text("SELECT set_config('app.current_tenant_id', :tenant_id, true)")


async def set_tenant_context(session: AsyncSession, tenant_id: UUID) -> None:
    """Bind the session's current transaction to *tenant_id* (transaction-local).

    Must be called before any tenant-scoped query in the same transaction.
    The ``true`` third argument is what keeps it from leaking across requests.
    """
    await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
