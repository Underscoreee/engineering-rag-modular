"""Typed configuration for Sentence-Transformers and Milvus."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .errors import VectorConfigurationError

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_EMBEDDING_REVISION = "7999e1d3359715c523056ef9478215996d62a620"


@dataclass(frozen=True, slots=True)
class VectorRetrievalConfig:
    """Private runtime configuration; no connection or model load occurs here."""

    milvus_uri: str | None = None
    milvus_token: str | None = None
    default_collection: str = "engineering_rag_chunks_v1"
    request_timeout: float = 30.0
    embedding_model_id: str = DEFAULT_EMBEDDING_MODEL
    embedding_model_revision: str = DEFAULT_EMBEDDING_REVISION
    embedding_device: str = "cpu"
    embedding_cache_dir: Path | None = None
    embedding_batch_size: int = 32
    query_instruction: str = "为这个句子生成表示以用于检索相关文章："
    normalize_embeddings: bool = True
    expected_dimension: int | None = None
    metric_type: str = "COSINE"
    index_type: str = "HNSW"
    hnsw_m: int = 16
    hnsw_ef_construction: int = 200
    search_ef: int = 64
    write_batch_size: int = 128
    max_top_k: int = 100

    def __post_init__(self) -> None:
        if self.milvus_uri is not None and not self.milvus_uri.strip():
            raise VectorConfigurationError("MILVUS_URI must not be blank")
        for name in ("default_collection", "embedding_model_id", "embedding_model_revision"):
            if not getattr(self, name).strip():
                raise VectorConfigurationError(f"{name} must not be blank")
        if self.request_timeout <= 0:
            raise VectorConfigurationError("request_timeout must be greater than zero")
        for name in ("embedding_batch_size", "write_batch_size", "max_top_k"):
            if getattr(self, name) <= 0:
                raise VectorConfigurationError(f"{name} must be greater than zero")
        if self.expected_dimension is not None and self.expected_dimension <= 0:
            raise VectorConfigurationError("expected_dimension must be greater than zero")
        if self.metric_type != "COSINE":
            raise VectorConfigurationError("Vector Retrieval V1 requires COSINE metric")
        if self.index_type != "HNSW":
            raise VectorConfigurationError("Vector Retrieval V1 requires HNSW index")
        if self.hnsw_m <= 0 or self.hnsw_ef_construction <= 0 or self.search_ef <= 0:
            raise VectorConfigurationError("HNSW parameters must be greater than zero")

    @classmethod
    def from_env(cls) -> VectorRetrievalConfig:
        cache = os.getenv("ENGINEERING_RAG_EMBEDDING_CACHE_DIR")
        return cls(
            milvus_uri=os.getenv("MILVUS_URI"),
            milvus_token=os.getenv("MILVUS_TOKEN"),
            default_collection=os.getenv(
                "ENGINEERING_RAG_VECTOR_COLLECTION", "engineering_rag_chunks_v1"
            ),
            request_timeout=_float_env("ENGINEERING_RAG_MILVUS_TIMEOUT", 30.0),
            embedding_model_id=os.getenv(
                "ENGINEERING_RAG_EMBEDDING_MODEL", DEFAULT_EMBEDDING_MODEL
            ),
            embedding_model_revision=os.getenv(
                "ENGINEERING_RAG_EMBEDDING_REVISION", DEFAULT_EMBEDDING_REVISION
            ),
            embedding_device=os.getenv("ENGINEERING_RAG_EMBEDDING_DEVICE", "cpu"),
            embedding_cache_dir=Path(cache) if cache else None,
            embedding_batch_size=_int_env("ENGINEERING_RAG_EMBEDDING_BATCH_SIZE", 32),
            query_instruction=os.getenv(
                "ENGINEERING_RAG_EMBEDDING_QUERY_INSTRUCTION",
                "为这个句子生成表示以用于检索相关文章：",
            ),
            expected_dimension=_optional_int_env("ENGINEERING_RAG_EMBEDDING_DIMENSION"),
            write_batch_size=_int_env("ENGINEERING_RAG_VECTOR_WRITE_BATCH_SIZE", 128),
            max_top_k=_int_env("ENGINEERING_RAG_VECTOR_MAX_TOP_K", 100),
        )


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    try:
        return default if value is None else int(value)
    except ValueError as exc:
        raise VectorConfigurationError(f"{name} must be an integer") from exc


def _optional_int_env(name: str) -> int | None:
    value = os.getenv(name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise VectorConfigurationError(f"{name} must be an integer") from exc


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    try:
        return default if value is None else float(value)
    except ValueError as exc:
        raise VectorConfigurationError(f"{name} must be a number") from exc
