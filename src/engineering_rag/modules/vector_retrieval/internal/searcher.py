"""Milvus filter construction, ANN search, and public result conversion."""

from __future__ import annotations

from collections.abc import Mapping

from engineering_rag.contracts.documents import StandardMetadata
from engineering_rag.contracts.retrieval import (
    RetrievalResult,
    SearchFilters,
    VectorSearchRequest,
)

from .collection_schema import compatibility_metadata, validate_collection
from .config import VectorRetrievalConfig
from .embeddings import EmbeddingProvider, validate_vectors
from .errors import CollectionNotFoundError, VectorResponseError
from .indexer import json_string_list
from .milvus_client import MilvusClientProtocol, translated_milvus_error

OUTPUT_FIELDS = [
    "chunk_id",
    "logical_chunk_id",
    "document_id",
    "content",
    "standard_name",
    "standard_code",
    "edition",
    "standard_revision",
    "standard_language",
    "clause_id",
    "clause_number",
    "page_start",
    "page_end",
]


def search_chunks(
    client: MilvusClientProtocol,
    provider: EmbeddingProvider,
    config: VectorRetrievalConfig,
    request: VectorSearchRequest,
) -> list[RetrievalResult]:
    validated = VectorSearchRequest.model_validate(request.model_dump(mode="json"))
    if validated.top_k > config.max_top_k:
        raise ValueError(f"top_k exceeds configured maximum {config.max_top_k}")
    if validated.embedding_model_id not in {None, provider.model_id}:
        raise ValueError("request embedding_model_id differs from configured provider")
    try:
        exists = client.has_collection(collection_name=validated.index_name)
    except Exception as exc:
        raise translated_milvus_error(exc, "failed to inspect Milvus collection") from exc
    if not exists:
        raise CollectionNotFoundError(f"collection {validated.index_name!r} does not exist")
    validate_collection(
        client,
        validated.index_name,
        compatibility_metadata(config, provider),
    )
    vector = validate_vectors(
        [provider.embed_query(validated.query)], expected_count=1, dimension=provider.dimension
    )[0]
    try:
        raw = client.search(
            collection_name=validated.index_name,
            data=[vector],
            anns_field="embedding",
            filter=build_filter_expression(validated.filters),
            limit=validated.top_k,
            output_fields=OUTPUT_FIELDS,
            search_params={"metric_type": config.metric_type, "params": {"ef": config.search_ef}},
            consistency_level="Strong",
        )
    except Exception as exc:
        raise translated_milvus_error(exc, "Milvus vector search failed") from exc
    if not isinstance(raw, list) or len(raw) != 1 or not isinstance(raw[0], list):
        raise VectorResponseError("Milvus search returned an unexpected response shape")
    return [
        _to_result(hit, rank=rank, index_name=validated.index_name)
        for rank, hit in enumerate(raw[0], start=1)
    ]


def build_filter_expression(filters: SearchFilters) -> str:
    clauses: list[str] = []
    list_fields = (
        ("document_id", filters.document_ids),
        ("standard_code", filters.standard_codes),
        ("edition", filters.editions),
        ("clause_number", filters.clause_numbers),
        ("content_type", [item.value for item in filters.content_types]),
    )
    for field, values in list_fields:
        if values:
            clauses.append(f"{field} in {json_string_list(values)}")
    if filters.is_explanation is not None:
        clauses.append(f"is_explanation == {str(filters.is_explanation).lower()}")
    if filters.is_mandatory is not None:
        clauses.append(f"mandatory_state == {int(filters.is_mandatory)}")
    return " and ".join(clauses)


def _to_result(hit: object, *, rank: int, index_name: str) -> RetrievalResult:
    if not isinstance(hit, Mapping):
        raise VectorResponseError("Milvus hit is not an object")
    entity = hit.get("entity")
    distance = hit.get("distance")
    if not isinstance(entity, Mapping) or not isinstance(distance, (int, float)):
        raise VectorResponseError("Milvus hit lacks entity or distance")
    try:
        return RetrievalResult(
            chunk_id=str(entity["chunk_id"]),
            logical_chunk_id=str(entity["logical_chunk_id"]),
            document_id=str(entity["document_id"]),
            content=str(entity["content"]),
            standard=StandardMetadata(
                standard_name=str(entity["standard_name"]),
                standard_code=str(entity["standard_code"]),
                edition=_optional_string(entity.get("edition")),
                revision=_optional_string(entity.get("standard_revision")),
                language=_optional_string(entity.get("standard_language")),
            ),
            clause_id=_optional_string(entity.get("clause_id")),
            clause_number=_optional_string(entity.get("clause_number")),
            page_start=int(entity["page_start"]),
            page_end=int(entity["page_end"]),
            score=float(distance),
            rank=rank,
            retrieval_source="vector",
            score_type="cosine_similarity",
            index_name=index_name,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise VectorResponseError("Milvus hit cannot form RetrievalResult") from exc


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
