"""Stable vector retrieval API exports."""

from engineering_rag.contracts.protocols import VectorRetrievalService
from engineering_rag.contracts.retrieval import (
    DeleteResult,
    IndexRequest,
    IndexResult,
    RetrievalResult,
    VectorSearchRequest,
)

__all__ = [
    "DeleteResult",
    "IndexRequest",
    "IndexResult",
    "RetrievalResult",
    "VectorRetrievalService",
    "VectorSearchRequest",
]
