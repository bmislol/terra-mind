"""tenant_preferences table + fail-closed RLS (Phase 5.1, D-011 revision).

Per-tenant config (selected wiki version + UI prefs). RLS-scoped exactly like
sessions/messages — the SECOND tenant-scoped data type to carry the proven
fail-closed policy (D-030 NULLIF form, copied verbatim from c2d3e4f5a6b7), so the
isolation story stays DB-enforced everywhere, not a WHERE-clause exception.

Preferences live in their own table (not a column on ``tenants``) because the
tenants table is read pre-auth (login by email, with no tenant context set) — a
fail-closed RLS policy there would deny those lookups and break login.

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-06-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "d3e4f5a6b7c8"
down_revision: str | None = "c2d3e4f5a6b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USING = "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "tenant_preferences",
        sa.Column(
            "tenant_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("preferences", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON tenant_preferences TO terramind_app"
    )
    op.execute("ALTER TABLE tenant_preferences ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenant_preferences FORCE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON tenant_preferences USING ({_USING})")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON tenant_preferences")
    op.drop_table("tenant_preferences")
