"""Stable Document Parser API and the Task 1.1 production implementation entry."""

from engineering_rag.contracts.documents import Document, ParseRequest
from engineering_rag.contracts.protocols import DocumentParser, FileStore

from .internal.diagnostics import PageObserver
from .internal.parser import PyMuPdfDocumentParser


def create_document_parser(
    file_store: FileStore,
    *,
    ocr_backend: str = "rapidocr",
    page_observer: PageObserver | None = None,
) -> PyMuPdfDocumentParser:
    """Create the Task 1.1 parser without loading PDF or OCR dependencies."""

    if ocr_backend != "rapidocr":
        raise ValueError("Task 1.1 production factory supports only 'rapidocr'")
    return PyMuPdfDocumentParser(file_store, page_observer=page_observer)


__all__ = [
    "Document",
    "DocumentParser",
    "ParseRequest",
    "PyMuPdfDocumentParser",
    "create_document_parser",
]
