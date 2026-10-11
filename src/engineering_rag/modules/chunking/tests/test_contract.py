from inspect import signature
from pathlib import Path
from typing import get_type_hints

from engineering_rag.contracts.chunks import ChunkBatch, ChunkingConfig
from engineering_rag.contracts.documents import Document
from engineering_rag.contracts.protocols import ChunkingService as CanonicalChunkingService
from engineering_rag.modules.chunking.api import ChunkingService


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
