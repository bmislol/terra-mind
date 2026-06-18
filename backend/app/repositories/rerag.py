"""Operator re-rag job rows (Phase 5.3, D-033).

`rerag_jobs` has **no RLS policy** (operator/cross-tenant, like `audit_log` —
D-017), so these reads/writes need no tenant context; the non-superuser
`terramind_app` role holds SELECT/INSERT/UPDATE (the rerag_jobs migration), and
authorization is the `require_operator` gate at the route. The WORKER updates
rows on its own sync connection (app/jobs/rerag.py) — these async helpers are the
api path (enqueue + status).
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ReragJob


async def create_job(session: AsyncSession, *, job_id: UUID, version: str) -> None:
    """Insert a queued job row. Caller owns the commit."""
    session.add(ReragJob(id=job_id, version=version, status="queued"))


async def get_job(session: AsyncSession, job_id: UUID) -> ReragJob | None:
    """Fetch a job by id (no tenant context — rerag_jobs has no RLS)."""
    return await session.get(ReragJob, job_id)
