"""Stable hybrid retrieval API and implementation exports."""

from __future__ import annotations

from engineering_rag.contracts.protocols import (
    HybridRetrievalService,
    KeywordRetrievalService,
    VectorRetrievalService,
)
from engineering_rag.contracts.retrieval import (
    FusionStrategy,
    HybridSearchRequest,
    RetrievalResult,
)

from .internal.config import HybridRetrievalConfig
from .internal.errors import (
    CandidateConflictError,
    CandidateResultError,
    FusionParameterError,
    HybridRetrievalError,
)
from .internal.service import DefaultHybridRetrievalService


def create_hybrid_retrieval_service(
    keyword_service: KeywordRetrievalService,
    vector_service: VectorRetrievalService,
    config: HybridRetrievalConfig | None = None,
) -> DefaultHybridRetrievalService:
    """Compose injected public retrieval capabilities without backend coupling."""

    return DefaultHybridRetrievalService(keyword_service, vector_service, config)


__all__ = [
    "CandidateConflictError",
    "CandidateResultError",
    "DefaultHybridRetrievalService",
    "FusionParameterError",
    "FusionStrategy",
    "HybridRetrievalConfig",
    "HybridRetrievalError",
    "HybridRetrievalService",
    "HybridSearchRequest",
    "RetrievalResult",
    "create_hybrid_retrieval_service",
]
