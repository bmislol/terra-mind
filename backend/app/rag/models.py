"""Domain models for RAG chunks produced by the corpus build pipeline."""

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
