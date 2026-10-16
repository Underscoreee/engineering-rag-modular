from inspect import signature
from pathlib import Path
from typing import get_type_hints

import pytest

from engineering_rag.contracts.chunks import ChunkBatch, ChunkingConfig
from engineering_rag.contracts.documents import Document
from engineering_rag.contracts.protocols import ChunkingService as CanonicalChunkingService
from engineering_rag.modules.chunking.api import ChunkingService, create_chunking_service


def test_protocol_is_declaration_only() -> None:
    assert ChunkingService is CanonicalChunkingService
    assert getattr(ChunkingService, "_is_protocol", False)
    assert list(signature(ChunkingService.chunk).parameters) == ["self", "document", "config"]
    assert get_type_hints(ChunkingService.chunk) == {
        "document": Document,
        "config": ChunkingConfig,
        "return": ChunkBatch,
    }
    interface = (Path(__file__).parents[1] / "INTERFACE.md").read_text(encoding="utf-8")
    assert "def chunk(self, document: Document, config: ChunkingConfig) -> ChunkBatch" in interface


def test_factory_returns_protocol_implementation() -> None:
    assert isinstance(create_chunking_service(), CanonicalChunkingService)


def test_chunk_v1_rejects_overlap() -> None:
    with pytest.raises(ValueError, match="overlap_tokens=0"):
        ChunkingConfig(strategy_id="clause-first-v1", max_tokens=100, overlap_tokens=1)
