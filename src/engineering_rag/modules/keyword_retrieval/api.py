"""Stable keyword retrieval API and real Elasticsearch implementation exports."""

from __future__ import annotations

from engineering_rag.contracts.protocols import KeywordRetrievalService
from engineering_rag.contracts.retrieval import (
    DeleteResult,
    IndexRequest,
    IndexResult,
    KeywordSearchRequest,
    RetrievalResult,
)

from .internal.client import ElasticsearchClient, create_elasticsearch_client
from .internal.config import ElasticsearchKeywordConfig
from .internal.errors import (
    KeywordBackendError,
    KeywordConfigurationError,
    KeywordConnectionError,
    KeywordDependencyError,
    KeywordIndexCompatibilityError,
    KeywordIndexCreationError,
    KeywordIndexNotFoundError,
    KeywordRequestError,
    KeywordResponseError,
    KeywordRetrievalError,
    KeywordTimeoutError,
)
from .internal.service import ElasticsearchKeywordRetrievalService


def create_keyword_retrieval_service(
    config: ElasticsearchKeywordConfig | None = None,
    *,
    client: ElasticsearchClient | None = None,
) -> ElasticsearchKeywordRetrievalService:
    """Create a service with an injected client or a lazily constructed official client."""

    resolved_config = config or ElasticsearchKeywordConfig.from_env()
    if client is not None:
        return ElasticsearchKeywordRetrievalService(client, resolved_config)
    owned_client = create_elasticsearch_client(resolved_config)
    return ElasticsearchKeywordRetrievalService(
        owned_client,
        resolved_config,
        owns_client=True,
    )


__all__ = [
    "DeleteResult",
    "ElasticsearchKeywordConfig",
    "ElasticsearchKeywordRetrievalService",
    "IndexRequest",
    "IndexResult",
    "KeywordRetrievalService",
    "KeywordBackendError",
    "KeywordConfigurationError",
    "KeywordConnectionError",
    "KeywordDependencyError",
    "KeywordIndexCompatibilityError",
    "KeywordIndexCreationError",
    "KeywordIndexNotFoundError",
    "KeywordRequestError",
    "KeywordResponseError",
    "KeywordRetrievalError",
    "KeywordTimeoutError",
    "KeywordSearchRequest",
    "RetrievalResult",
    "create_keyword_retrieval_service",
]
