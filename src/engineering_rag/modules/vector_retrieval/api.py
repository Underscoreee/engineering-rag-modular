"""Stable vector retrieval API and real Milvus implementation exports."""

from __future__ import annotations

from engineering_rag.contracts.protocols import VectorRetrievalService
from engineering_rag.contracts.retrieval import (
    DeleteResult,
    IndexRequest,
    IndexResult,
    RetrievalResult,
    VectorSearchRequest,
)

from .internal.config import VectorRetrievalConfig
from .internal.embeddings import EmbeddingProvider, SentenceTransformerEmbeddingProvider
from .internal.errors import (
    CollectionCompatibilityError,
    CollectionNotFoundError,
    EmbeddingModelError,
    InvalidEmbeddingError,
    MilvusConnectionError,
    VectorBackendError,
    VectorConfigurationError,
    VectorDependencyError,
    VectorResponseError,
    VectorRetrievalError,
    VectorTimeoutError,
)
from .internal.milvus_client import MilvusClientProtocol, create_milvus_client
from .internal.service import MilvusVectorRetrievalService


def create_vector_retrieval_service(
    config: VectorRetrievalConfig | None = None,
    *,
    client: MilvusClientProtocol | None = None,
    embedding_provider: EmbeddingProvider | None = None,
) -> MilvusVectorRetrievalService:
    """Create a lazily configured service with optional injected test/runtime dependencies."""

    resolved = config or VectorRetrievalConfig.from_env()
    provider = embedding_provider or SentenceTransformerEmbeddingProvider(resolved)
    if client is not None:
        return MilvusVectorRetrievalService(client, provider, resolved)
    owned_client = create_milvus_client(resolved)
    return MilvusVectorRetrievalService(
        owned_client,
        provider,
        resolved,
        owns_client=True,
    )


__all__ = [
    "DeleteResult",
    "EmbeddingModelError",
    "EmbeddingProvider",
    "InvalidEmbeddingError",
    "IndexRequest",
    "IndexResult",
    "MilvusConnectionError",
    "MilvusVectorRetrievalService",
    "RetrievalResult",
    "SentenceTransformerEmbeddingProvider",
    "CollectionCompatibilityError",
    "CollectionNotFoundError",
    "VectorBackendError",
    "VectorConfigurationError",
    "VectorDependencyError",
    "VectorResponseError",
    "VectorRetrievalService",
    "VectorRetrievalConfig",
    "VectorRetrievalError",
    "VectorTimeoutError",
    "VectorSearchRequest",
    "create_vector_retrieval_service",
]
