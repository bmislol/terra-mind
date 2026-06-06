"""Domain models for RAG chunks produced by the corpus build pipeline."""

from uuid import UUID

from pydantic import BaseModel


class ChunkRecord(BaseModel):
    page_id: int
    chunk_index: int
    revision_id: int
    source_url: str
    game_version: str
    page_title: str
    # Section label: "stats", "recipe", "intro", or the heading text.
    section: str
    # Stripped plain text that gets embedded.
    content: str
    # Prepended context included in the embedded string but not stored separately.
    # Stored here so tests can assert on what actually gets embedded.
    embed_text: str


class RetrievedChunk(BaseModel):
    """A single result from dense retrieval.

    ``id`` is the rag_chunks PK — used by the eval harness to match against
    ground-truth UUIDs and by the agent to deduplicate tool results.
    """

    id: UUID
    page_id: int
    page_title: str
    section: str
    content: str
    source_url: str
    game_version: str
    score: float  # cosine similarity in [0, 1]; higher = more relevant
