"""Stable Document Parser API and private backend construction."""

from pathlib import Path

from engineering_rag.contracts.documents import Document, ParseRequest
from engineering_rag.contracts.protocols import DocumentParser, FileStore

from .internal.diagnostics import PageObserver
from .internal.mineru import MinerUAdapter
from .internal.parser import PyMuPdfDocumentParser


def create_document_parser(
    file_store: FileStore,
    *,
    ocr_backend: str = "rapidocr",
    page_observer: PageObserver | None = None,
    document_engine: str = "baseline",
    mineru_executable: Path = Path("mineru-kit"),
    mineru_home: Path = Path(".local/mineru-runtime/state"),
) -> PyMuPdfDocumentParser:
    """Create the parser without importing or loading heavyweight model runtimes."""

    if ocr_backend != "rapidocr":
        raise ValueError("Task 1.1 production factory supports only 'rapidocr'")
    if document_engine not in {"baseline", "mineru"}:
        raise ValueError("document_engine must be 'baseline' or 'mineru'")
    adapter = MinerUAdapter(mineru_executable, mineru_home) if document_engine == "mineru" else None
    return PyMuPdfDocumentParser(
        file_store,
        page_observer=page_observer,
        mineru_adapter=adapter,
    )


__all__ = [
    "Document",
    "DocumentParser",
    "ParseRequest",
    "PyMuPdfDocumentParser",
    "create_document_parser",
]
