"""rag_chunks: corpus fields, upsert key, HNSW index.

Adds page_id, chunk_index, revision_id, source_url columns;
UNIQUE (page_id, chunk_index, game_version) constraint for idempotent upserts;
HNSW vector index for dense retrieval (D-019).

Revision ID: b1c2d3e4f5a6
Revises: a8f3b2c1d4e5
"""

import sqlalchemy as sa
from alembic import op

revision = "b1c2d3e4f5a6"
down_revision = "a8f3b2c1d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Four new columns — DEFAULT values allow clean migration on a DB with
    # pre-existing rows (none in practice, but correct for Alembic).
    op.add_column(
        "rag_chunks",
        sa.Column("page_id", sa.Integer, nullable=False, server_default="0"),
    )
    op.add_column(
        "rag_chunks",
        sa.Column("chunk_index", sa.SmallInteger, nullable=False, server_default="0"),
    )
    op.add_column(
        "rag_chunks",
        sa.Column("revision_id", sa.BigInteger, nullable=False, server_default="0"),
    )
    op.add_column(
        "rag_chunks",
        sa.Column("source_url", sa.Text, nullable=False, server_default=""),
    )

    # Upsert key: (page_id, chunk_index, game_version).
    # Re-running build_corpus on the same raw data produces the same chunk
    # indices and game_version, so the INSERT ... ON CONFLICT DO UPDATE
    # is idempotent without orphan rows.
    op.create_unique_constraint(
        "rag_chunks_upsert_key",
        "rag_chunks",
        ["page_id", "chunk_index", "game_version"],
    )

    # HNSW index for dense retrieval (D-019: m=16, ef_construction=64,
    # vector_cosine_ops).  MiniLM outputs L2-normalised embeddings so
    # cosine distance equals inner product.
    op.execute(
        """
        CREATE INDEX rag_chunks_embedding_hnsw
          ON rag_chunks
          USING hnsw (embedding vector_cosine_ops)
          WITH (m = 16, ef_construction = 64)
        """
    )

    # Grant SELECT on the new columns to terramind_app (already has
    # table-level SELECT from the initial migration; this is a no-op for
    # column-level security but documents intent).
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON rag_chunks TO terramind_app")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS rag_chunks_embedding_hnsw")
    op.drop_constraint("rag_chunks_upsert_key", "rag_chunks", type_="unique")
    op.drop_column("rag_chunks", "source_url")
    op.drop_column("rag_chunks", "revision_id")
    op.drop_column("rag_chunks", "chunk_index")
    op.drop_column("rag_chunks", "page_id")
