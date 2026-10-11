from inspect import signature
from pathlib import Path
from typing import get_type_hints

from engineering_rag.contracts.documents import Document, ParseRequest
from engineering_rag.contracts.protocols import DocumentParser as CanonicalDocumentParser
from engineering_rag.modules.document_parser.api import DocumentParser


def test_protocol_is_declaration_only() -> None:
    assert DocumentParser is CanonicalDocumentParser
    assert getattr(DocumentParser, "_is_protocol", False)
    assert list(signature(DocumentParser.parse).parameters) == ["self", "request"]
    assert get_type_hints(DocumentParser.parse) == {"request": ParseRequest, "return": Document}
    interface = (Path(__file__).parents[1] / "INTERFACE.md").read_text(encoding="utf-8")
    assert "def parse(self, request: ParseRequest) -> Document" in interface
