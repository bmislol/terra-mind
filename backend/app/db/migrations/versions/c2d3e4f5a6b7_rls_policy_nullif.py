"""Harden RLS policies: NULLIF empty-string tenant GUC → fail-closed (no error).

After a transaction-local ``SET app.current_tenant_id`` (set_config local=true)
reverts at transaction end, the custom GUC reads back as ``''`` (empty string),
NOT ``NULL``, on a pooled connection. The original policy cast
``current_setting(...)::uuid``, which RAISES on ``''`` (surfacing as a 500)
instead of denying — so an uncontexted query on a previously-contexted pooled
connection errored rather than failing closed.

``NULLIF(current_setting('app.current_tenant_id', true), '')::uuid`` yields
``NULL`` for both the never-set and the reverted-to-empty cases →
``tenant_id = NULL`` → FALSE → zero rows. Proven by
tests/services/test_rls_context.py::test_uncontexted_connection_sees_zero_rows.

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a6
Create Date: 2026-06-14
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c2d3e4f5a6b7"
down_revision: str | None = "b1c2d3e4f5a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_USING = (
    "tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"
)
_OLD_USING = "tenant_id = current_setting('app.current_tenant_id', true)::uuid"


def _recreate_policies(using: str) -> None:
    for table in ("sessions", "messages"):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"CREATE POLICY tenant_isolation ON {table} USING ({using})")


def upgrade() -> None:
    _recreate_policies(_NEW_USING)


def downgrade() -> None:
    _recreate_policies(_OLD_USING)
