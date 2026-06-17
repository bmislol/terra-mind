"""rerag_jobs table — operator re-rag job history (Phase 5.3, D-033).

Durable history for the operator-triggered re-rag background job. This is
**operator/cross-tenant data** (jobs aren't owned by a player tenant), so it gets
the SAME treatment as ``audit_log``/``tenants``: a ``terramind_app`` grant and
**NO RLS policy** — authorization is the ``require_operator`` gate at the API
(D-017 two-categories). A fail-closed ``tenant_isolation`` policy is deliberately
**omitted**: the operator path sets no tenant context, so such a policy would deny
it (and the worker) every row. Contrast the per-tenant CONTENT tables
(sessions/messages/tenant_preferences), which ARE fail-closed RLS.

Minimal columns: id / version / status / progress (stage, done, total) /
timestamps / error.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-06-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "e4f5a6b7c8d9"
down_revision: str | None = "d3e4f5a6b7c8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "rerag_jobs",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(32), nullable=False, server_default=""),
        sa.Column("done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Operator/cross-tenant → role-gated, NOT RLS (D-017, like audit_log). The
    # worker INSERTs/UPDATEs job rows; the operator API SELECTs them. NO
    # `ENABLE ROW LEVEL SECURITY` / `tenant_isolation` policy here — that would
    # deny the operator (which sets no tenant context) every row.
    op.execute("GRANT SELECT, INSERT, UPDATE ON rerag_jobs TO terramind_app")


def downgrade() -> None:
    op.drop_table("rerag_jobs")
