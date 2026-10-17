"""Explicit Elasticsearch mapping for physical Chunk V1 documents."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from .config import ElasticsearchKeywordConfig
from .errors import KeywordIndexCompatibilityError, KeywordResponseError

INDEX_MAPPING_VERSION = "keyword-index-v1"


def build_index_definition(config: ElasticsearchKeywordConfig) -> dict[str, object]:
    """Build deterministic settings and a strict mapping for Chunk V1."""

    text = {"type": "text", "analyzer": config.analyzer}
    keyword = {"type": "keyword"}
    properties: dict[str, object] = {
        "schema_version": keyword,
        "chunk_id": keyword,
        "logical_chunk_id": keyword,
        "document_id": keyword,
        "content": text,
        "context_header": text,
        "embedding_text": text,
        "search_text": text,
        "token_count": {"type": "integer"},
        "content_type": keyword,
        "page_start": {"type": "integer"},
        "page_end": {"type": "integer"},
        "source_refs": {"type": "object", "enabled": False},
        "source_block_ids": keyword,
        "standard": {
            "type": "object",
            "dynamic": "strict",
            "properties": {
                "standard_name": keyword,
                "standard_code": keyword,
                "edition": keyword,
                "revision": keyword,
                "language": keyword,
            },
        },
        "section_path": keyword,
        "section_id": keyword,
        "clause_id": keyword,
        "clause_number": keyword,
        "is_explanation": {"type": "boolean"},
        "is_mandatory": {"type": "boolean"},
        "parent_chunk_id": keyword,
        "table_id": keyword,
        "figure_id": keyword,
        "formula_ids": keyword,
        "related_asset_ids": keyword,
        "chunking_version": keyword,
        "exceeds_max_tokens": {"type": "boolean"},
    }
    return {
        "settings": {"index": {"similarity": {"default": {"type": "BM25"}}}},
        "mappings": {
            "dynamic": "strict",
            "_meta": {
                "engineering_rag_mapping_version": INDEX_MAPPING_VERSION,
                "analyzer": config.analyzer,
            },
            "properties": properties,
        },
    }


def validate_existing_mapping(
    response: object,
    *,
    index_name: str,
    config: ElasticsearchKeywordConfig,
) -> None:
    """Reject indexes not explicitly created for this mapping/analyzer version."""

    body = getattr(response, "body", response)
    if not isinstance(body, Mapping):
        raise KeywordResponseError("get_mapping returned a non-object response")
    index_entry = body.get(index_name)
    if not isinstance(index_entry, Mapping):
        raise KeywordIndexCompatibilityError(
            f"index {index_name!r} mapping response does not identify that index"
        )
    mappings = index_entry.get("mappings")
    if not isinstance(mappings, Mapping):
        raise KeywordIndexCompatibilityError(f"index {index_name!r} has no mappings object")
    metadata = mappings.get("_meta")
    if not isinstance(metadata, Mapping):
        raise KeywordIndexCompatibilityError(
            f"index {index_name!r} is missing Engineering RAG mapping metadata"
        )
    if metadata.get("engineering_rag_mapping_version") != INDEX_MAPPING_VERSION:
        raise KeywordIndexCompatibilityError(
            f"index {index_name!r} uses an incompatible mapping version"
        )
    if metadata.get("analyzer") != config.analyzer:
        raise KeywordIndexCompatibilityError(
            f"index {index_name!r} analyzer differs from configured {config.analyzer!r}"
        )
    expected_mappings = cast(Mapping[str, object], build_index_definition(config)["mappings"])
    expected_properties = cast(Mapping[str, object], expected_mappings["properties"])
    actual_properties = mappings.get("properties")
    if not isinstance(actual_properties, Mapping):
        raise KeywordIndexCompatibilityError(f"index {index_name!r} has no properties mapping")
    for field, expected in expected_properties.items():
        if not _field_mapping_matches(expected, actual_properties.get(field)):
            raise KeywordIndexCompatibilityError(
                f"index {index_name!r} field {field!r} has an incompatible mapping"
            )


def _field_mapping_matches(expected: object, actual: object) -> bool:
    """Accept Elasticsearch's omission of the implied ``object`` type only."""

    if not isinstance(expected, Mapping) or not isinstance(actual, Mapping):
        return actual == expected
    normalized_actual = dict(actual)
    if expected.get("type") == "object" and "type" not in normalized_actual:
        normalized_actual["type"] = "object"
    return normalized_actual == expected
