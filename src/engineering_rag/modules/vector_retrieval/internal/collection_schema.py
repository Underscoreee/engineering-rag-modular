"""Versioned Milvus collection schema and compatibility checks."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

from .config import VectorRetrievalConfig
from .embeddings import EmbeddingProvider
from .errors import CollectionCompatibilityError, VectorBackendError, VectorDependencyError
from .milvus_client import MilvusClientProtocol

COLLECTION_SCHEMA_VERSION = "vector-collection-v1"
VECTOR_FIELD = "embedding"
_COLLECTION_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SCALAR_FILTER_FIELDS = (
    "document_id",
    "standard_code",
    "edition",
    "clause_number",
    "content_type",
    "is_explanation",
    "mandatory_state",
)
REQUIRED_FIELDS = {
    "chunk_id",
    VECTOR_FIELD,
    "logical_chunk_id",
    "document_id",
    "content",
    "content_type",
    "standard_name",
    "standard_code",
    "edition",
    "standard_revision",
    "standard_language",
    "clause_id",
    "clause_number",
    "page_start",
    "page_end",
    "is_explanation",
    "mandatory_state",
    "source_refs",
    "source_block_ids",
    "section_path",
    "provenance",
}


def compatibility_metadata(
    config: VectorRetrievalConfig, provider: EmbeddingProvider
) -> dict[str, object]:
    return {
        "schema_version": COLLECTION_SCHEMA_VERSION,
        "embedding_model_id": provider.model_id,
        "embedding_model_revision": provider.model_revision,
        "dimension": provider.dimension,
        "metric_type": config.metric_type,
        "normalized": config.normalize_embeddings,
        "query_instruction": config.query_instruction,
    }


def ensure_collection(
    client: MilvusClientProtocol,
    config: VectorRetrievalConfig,
    provider: EmbeddingProvider,
    collection_name: str,
) -> None:
    """Create once or reject an incompatible existing collection without deleting it."""

    validate_collection_name(collection_name)
    metadata = compatibility_metadata(config, provider)
    try:
        exists = client.has_collection(collection_name=collection_name)
    except Exception as exc:
        raise VectorBackendError(f"failed to inspect collection {collection_name!r}") from exc
    if exists:
        validate_collection(client, collection_name, metadata)
        client.load_collection(collection_name=collection_name)
        return
    try:
        from pymilvus import DataType
    except ImportError as exc:
        raise VectorDependencyError("pymilvus is required to create a collection") from exc
    try:
        schema = client.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
            description=json.dumps(metadata, ensure_ascii=False, sort_keys=True),
        )
        _add_fields(schema, DataType, provider.dimension)
        index_params = client.prepare_index_params()
        index_params.add_index(  # type: ignore[attr-defined]
            field_name=VECTOR_FIELD,
            index_type=config.index_type,
            metric_type=config.metric_type,
            params={"M": config.hnsw_m, "efConstruction": config.hnsw_ef_construction},
        )
        for field_name in SCALAR_FILTER_FIELDS:
            index_params.add_index(  # type: ignore[attr-defined]
                field_name=field_name,
                index_type="INVERTED",
            )
        client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
        )
        validate_collection(client, collection_name, metadata)
        client.load_collection(collection_name=collection_name)
    except (CollectionCompatibilityError, VectorDependencyError):
        raise
    except Exception as exc:
        raise VectorBackendError(f"failed to create collection {collection_name!r}") from exc


def validate_collection_name(name: str) -> None:
    if not _COLLECTION_NAME.fullmatch(name):
        raise ValueError("Milvus collection name must match ^[A-Za-z_][A-Za-z0-9_]*$")


def validate_collection(
    client: MilvusClientProtocol,
    collection_name: str,
    expected_metadata: Mapping[str, object],
) -> None:
    try:
        description = client.describe_collection(collection_name=collection_name)
    except Exception as exc:
        raise VectorBackendError(f"failed to describe collection {collection_name!r}") from exc
    raw_metadata = description.get("description")
    try:
        actual_metadata = json.loads(raw_metadata) if isinstance(raw_metadata, str) else None
    except json.JSONDecodeError as exc:
        raise CollectionCompatibilityError(
            f"collection {collection_name!r} has invalid compatibility metadata"
        ) from exc
    if actual_metadata != dict(expected_metadata):
        raise CollectionCompatibilityError(
            f"collection {collection_name!r} uses incompatible schema or embedding settings"
        )
    fields = description.get("fields")
    if not isinstance(fields, list):
        raise CollectionCompatibilityError(f"collection {collection_name!r} has no field schema")
    by_name = {
        field.get("name"): field
        for field in fields
        if isinstance(field, Mapping) and isinstance(field.get("name"), str)
    }
    if set(by_name) != REQUIRED_FIELDS:
        raise CollectionCompatibilityError(
            f"collection {collection_name!r} fields differ from {COLLECTION_SCHEMA_VERSION}"
        )
    vector_params = by_name[VECTOR_FIELD].get("params")
    if not isinstance(vector_params, Mapping) or int(vector_params.get("dim", -1)) != int(
        expected_metadata["dimension"]
    ):
        raise CollectionCompatibilityError(
            f"collection {collection_name!r} vector dimension is incompatible"
        )
    if by_name["chunk_id"].get("is_primary") is not True:
        raise CollectionCompatibilityError(
            f"collection {collection_name!r} does not use chunk_id as primary key"
        )


def _add_fields(schema: object, data_type: object, dimension: int) -> None:
    """Define scalar filter fields and lossless JSON provenance."""

    add = schema.add_field  # type: ignore[attr-defined]
    add("chunk_id", data_type.VARCHAR, is_primary=True, max_length=512)
    add(VECTOR_FIELD, data_type.FLOAT_VECTOR, dim=dimension)
    for name in (
        "logical_chunk_id",
        "document_id",
        "content_type",
        "standard_code",
        "edition",
        "clause_id",
        "clause_number",
    ):
        add(name, data_type.VARCHAR, max_length=1024)
    add("content", data_type.VARCHAR, max_length=65535)
    add("standard_name", data_type.VARCHAR, max_length=4096)
    add("standard_revision", data_type.VARCHAR, max_length=1024)
    add("standard_language", data_type.VARCHAR, max_length=128)
    add("page_start", data_type.INT64)
    add("page_end", data_type.INT64)
    add("is_explanation", data_type.BOOL)
    add("mandatory_state", data_type.INT8)
    for name in ("source_refs", "source_block_ids", "section_path", "provenance"):
        add(name, data_type.JSON)
