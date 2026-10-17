"""Milvus client boundary and lazy official-client construction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from .config import VectorRetrievalConfig
from .errors import (
    MilvusConnectionError,
    VectorBackendError,
    VectorDependencyError,
    VectorRetrievalError,
    VectorTimeoutError,
)


class MilvusClientProtocol(Protocol):
    def has_collection(self, collection_name: str, **kwargs: object) -> bool: ...
    def describe_collection(self, collection_name: str, **kwargs: object) -> dict[str, object]: ...
    def create_schema(self, **kwargs: object) -> object: ...
    def prepare_index_params(self, **kwargs: object) -> object: ...
    def create_collection(self, collection_name: str, **kwargs: object) -> None: ...
    def load_collection(self, collection_name: str, **kwargs: object) -> None: ...
    def upsert(
        self, collection_name: str, data: Sequence[Mapping[str, object]], **kwargs: object
    ) -> object: ...
    def query(self, collection_name: str, **kwargs: object) -> list[dict[str, object]]: ...
    def search(self, collection_name: str, **kwargs: object) -> list[list[dict[str, object]]]: ...
    def delete(self, collection_name: str, **kwargs: object) -> object: ...
    def close(self) -> None: ...


def create_milvus_client(config: VectorRetrievalConfig) -> MilvusClientProtocol:
    if config.milvus_uri is None:
        raise MilvusConnectionError("MILVUS_URI is required when no client is injected")
    try:
        from pymilvus import MilvusClient
    except ImportError as exc:
        raise VectorDependencyError("pymilvus is required; install .[vector-retrieval]") from exc
    kwargs: dict[str, object] = {
        "uri": config.milvus_uri,
        "timeout": config.request_timeout,
    }
    if config.milvus_token:
        kwargs["token"] = config.milvus_token
    try:
        return MilvusClient(**kwargs)
    except Exception as exc:
        raise MilvusConnectionError("failed to create Milvus client") from exc


def translated_milvus_error(exc: BaseException, context: str) -> VectorRetrievalError:
    """Classify common pymilvus/grpc failures without importing optional exception classes."""

    name = type(exc).__name__.lower()
    message = str(exc).lower()
    if "timeout" in name or "deadline exceeded" in message or "timeout" in message:
        return VectorTimeoutError(context)
    if any(token in message for token in ("unavailable", "connect", "connection", "channel")):
        return MilvusConnectionError(context)
    return VectorBackendError(context)
