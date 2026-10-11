"""Stable keyword retrieval API exports."""

from engineering_rag.contracts.protocols import KeywordRetrievalService
from engineering_rag.contracts.retrieval import (
    DeleteResult,
    IndexRequest,
    IndexResult,
    KeywordSearchRequest,
    RetrievalResult,
)

__all__ = [
    "DeleteResult",
    "IndexRequest",
    "IndexResult",
    "KeywordRetrievalService",
    "KeywordSearchRequest",
    "RetrievalResult",
]
