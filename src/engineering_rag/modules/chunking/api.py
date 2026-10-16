"""Stable Chunk V1 API and dependency-free implementation factory."""

from engineering_rag.contracts.chunks import Chunk, ChunkBatch, ChunkingConfig
from engineering_rag.contracts.documents import Document
from engineering_rag.contracts.protocols import ChunkingService

from .internal.assembler import ClauseFirstChunker as _ClauseFirstChunker


def create_chunking_service() -> ChunkingService:
    """Create the stateless Clause-first Chunk V1 implementation."""
    return _ClauseFirstChunker()


__all__ = [
    "Chunk",
    "ChunkBatch",
    "ChunkingConfig",
    "ChunkingService",
    "Document",
    "create_chunking_service",
]
