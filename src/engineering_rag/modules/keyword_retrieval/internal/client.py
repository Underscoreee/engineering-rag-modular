"""Elasticsearch client boundary and lazy official-client factory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from .config import ElasticsearchKeywordConfig, RefreshPolicy
from .errors import (
    KeywordBackendError,
    KeywordConfigurationError,
    KeywordConnectionError,
    KeywordDependencyError,
    KeywordResponseError,
    KeywordRetrievalError,
    KeywordTimeoutError,
)


class ElasticsearchIndicesClient(Protocol):
    def exists(self, *, index: str) -> object: ...

    def create(
        self,
        *,
        index: str,
        settings: Mapping[str, object],
        mappings: Mapping[str, object],
    ) -> object: ...

    def get_mapping(self, *, index: str) -> object: ...

    def delete(self, *, index: str) -> object: ...


class ElasticsearchClient(Protocol):
    indices: ElasticsearchIndicesClient

    def bulk(
        self,
        *,
        operations: Sequence[Mapping[str, object]],
        refresh: RefreshPolicy,
    ) -> object: ...

    def search(
        self,
        *,
        index: str,
        query: Mapping[str, object],
        size: int,
        sort: Sequence[Mapping[str, object]],
        track_scores: bool,
    ) -> object: ...

    def delete_by_query(
        self,
        *,
        index: str,
        query: Mapping[str, object],
        refresh: bool,
        conflicts: str,
    ) -> object: ...

    def close(self) -> object: ...


def create_elasticsearch_client(config: ElasticsearchKeywordConfig) -> ElasticsearchClient:
    """Create the official client; no import or network I/O occurs before this call."""

    if config.url is None:
        raise KeywordConfigurationError(
            "ELASTICSEARCH_URL is required when no Elasticsearch client is injected"
        )
    try:
        from elasticsearch import Elasticsearch
    except ImportError as exc:
        raise KeywordDependencyError(
            "install the keyword backend with: pip install -e '.[keyword-retrieval]'"
        ) from exc

    kwargs: dict[str, object] = {"request_timeout": config.request_timeout}
    if config.api_key is not None:
        kwargs["api_key"] = config.api_key
    return Elasticsearch(config.url, **kwargs)


def response_body(response: object, *, operation: str) -> Mapping[str, object]:
    """Normalize official ``ObjectApiResponse`` and plain test doubles."""

    body = getattr(response, "body", response)
    if not isinstance(body, Mapping):
        raise KeywordResponseError(f"{operation} returned a non-object response")
    return body


def exception_status(exc: BaseException) -> int | None:
    """Read a status code without importing Elasticsearch exception classes."""

    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    meta = getattr(exc, "meta", None)
    meta_status = getattr(meta, "status", None)
    return meta_status if isinstance(meta_status, int) else None


def is_timeout(exc: BaseException) -> bool:
    return isinstance(exc, TimeoutError) or "timeout" in type(exc).__name__.lower()


def is_connection_error(exc: BaseException) -> bool:
    name = type(exc).__name__.lower()
    return "connection" in name or "transport" in name


def translated_backend_error(exc: BaseException, message: str) -> KeywordRetrievalError:
    """Classify transport failures while preserving the original exception as cause."""

    if is_timeout(exc):
        return KeywordTimeoutError(message)
    if is_connection_error(exc):
        return KeywordConnectionError(message)
    return KeywordBackendError(message)


def refresh_as_bool(policy: RefreshPolicy) -> bool:
    """Delete-by-query accepts a boolean refresh flag, unlike Bulk's wait_for value."""

    return policy != "false"
