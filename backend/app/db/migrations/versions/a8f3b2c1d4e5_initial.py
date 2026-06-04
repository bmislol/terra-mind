"""Initial schema: extension, tables, grants, RLS policies.

Revision ID: a8f3b2c1d4e5
Revises:
Create Date: 2026-06-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector  # type: ignore[import-untyped]
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID

revision: str = "a8f3b2c1d4e5"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── Extension ─────────────────────────────────────────────────────────────
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ── Tables ────────────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String, unique=True, nullable=True),
        sa.Column("hashed_password", sa.String, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_superuser", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_verified", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("is_guest", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("guest_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "sessions",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("game_version", sa.String(32), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_active_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "messages",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            PGUUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", PGUUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "rag_chunks",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("game_version", sa.String(32), nullable=False, index=True),
        sa.Column("page_title", sa.String(512), nullable=False),
        sa.Column("section", sa.String(512), nullable=False, server_default=""),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", PGUUID(as_uuid=True), primary_key=True),
        sa.Column("actor", PGUUID(as_uuid=True), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("target", sa.String(256), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("trace_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    # ── Grants to terramind_app (non-superuser API role) ──────────────────────
    op.execute("GRANT CONNECT ON DATABASE terramind TO terramind_app")
    op.execute("GRANT USAGE ON SCHEMA public TO terramind_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE"
        " ON tenants, sessions, messages, rag_chunks TO terramind_app"
    )
    # audit_log: INSERT only; operator reads via the API (service layer gate).
    # No UPDATE or DELETE — append-only by design (SECURITY.md §6).
    op.execute("GRANT SELECT, INSERT ON audit_log TO terramind_app")
    # Future tables created by terramind automatically inherit these grants.
    op.execute(
        "ALTER DEFAULT PRIVILEGES FOR ROLE terramind IN SCHEMA public"
        " GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO terramind_app"
    )

    # ── Row-Level Security ────────────────────────────────────────────────────
    # current_setting('app.current_tenant_id', true): the second arg (missing-ok)
    # returns NULL when the context variable is not set instead of raising an error.
    # NULL::uuid = any tenant_id is FALSE, so uncontexted connections see zero rows
    # (fail-closed). The service layer always sets the context before any query.
    # WITH CHECK is omitted intentionally: Postgres uses the USING expression as
    # the implicit WITH CHECK when none is specified, so cross-tenant INSERTs are
    # blocked by the same predicate as SELECTs (verified by manual test 6b).
    #
    # audit_log is intentionally NOT RLS-protected — it is cross-tenant by design
    # and operator-gated at the service layer (SECURITY.md §3, DECISIONS.md D-017).
    for table in ("sessions", "messages"):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    op.execute(
        """
        CREATE POLICY tenant_isolation ON sessions
            USING (
                tenant_id = current_setting('app.current_tenant_id', true)::uuid
            )
        """
    )
    op.execute(
        """
        CREATE POLICY tenant_isolation ON messages
            USING (
                tenant_id = current_setting('app.current_tenant_id', true)::uuid
            )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON messages")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON sessions")
    op.drop_table("audit_log")
    op.drop_table("rag_chunks")
    op.drop_table("messages")
    op.drop_table("sessions")
    op.drop_table("tenants")
    op.execute("DROP EXTENSION IF EXISTS vector")
