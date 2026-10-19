"""Read-only, exact-corpus backend inspection for the real Query smoke CLI.

This composition helper intentionally uses public module exports and official
client operations only. It neither indexes data nor changes retrieval algorithms.
Catalog trust is established by inspecting both inventories, not by relabeling a
fictional catalog as a production adapter.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from engineering_rag.contracts.catalog import (
    CatalogIndexScope,
    StandardMetadataLookup,
    StandardMetadataMatch,
    StandardMetadataRecord,
)
from engineering_rag.contracts.chunks import Chunk, ChunkBatch
from engineering_rag.modules.keyword_retrieval.api import ElasticsearchKeywordConfig
from engineering_rag.modules.vector_retrieval.api import EmbeddingProvider, VectorRetrievalConfig

_PAGE_SIZE = 500
_ES_VERSION = "keyword-index-v1"
_VECTOR_VERSION = "vector-collection-v1"
_KEYWORD_FIELDS = frozenset(
    {
        "schema_version",
        "chunk_id",
        "logical_chunk_id",
        "document_id",
        "content_type",
        "source_block_ids",
        "section_path",
        "section_id",
        "clause_id",
        "clause_number",
        "parent_chunk_id",
        "table_id",
        "figure_id",
        "formula_ids",
        "related_asset_ids",
        "chunking_version",
    }
)
_TEXT_FIELDS = frozenset({"content", "context_header", "embedding_text", "search_text"})
_INTEGER_FIELDS = frozenset({"token_count", "page_start", "page_end"})
_BOOLEAN_FIELDS = frozenset({"is_explanation", "is_mandatory", "exceeds_max_tokens"})
_VECTOR_STRINGS = frozenset(
    {
        "chunk_id",
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
    }
)
_VECTOR_JSON = frozenset({"source_refs", "source_block_ids", "section_path", "provenance"})
_VECTOR_FIELDS = frozenset(
    {*_VECTOR_STRINGS, *_VECTOR_JSON, "page_start", "page_end", "is_explanation", "mandatory_state"}
)


class BackendInspectionError(RuntimeError):
    """Sanitized failure: no server message, URI, authentication data or content."""

    def __init__(self, code: str) -> None:
        super().__init__(f"backend inspection failed: {code}")
        self.code = code


class KeywordInspectionClient(Protocol):
    @property
    def indices(self) -> object: ...

    def count(self, **kwargs: object) -> object: ...
    def search(self, **kwargs: object) -> object: ...
    def scroll(self, **kwargs: object) -> object: ...
    def clear_scroll(self, **kwargs: object) -> object: ...


class VectorInspectionClient(Protocol):
    def has_collection(self, **kwargs: object) -> bool: ...
    def describe_collection(self, **kwargs: object) -> object: ...
    def get_collection_stats(self, **kwargs: object) -> object: ...
    def list_indexes(self, **kwargs: object) -> object: ...
    def describe_index(self, **kwargs: object) -> object: ...
    def query(self, **kwargs: object) -> object: ...
    def query_iterator(self, **kwargs: object) -> object: ...


def _canonical(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _mapping(value: object, code: str) -> Mapping[str, object]:
    body = getattr(value, "body", value)
    if not isinstance(body, Mapping):
        raise BackendInspectionError(code)
    return body


def _integer(value: object, code: str) -> int:
    if type(value) is not int or value < 0:
        raise BackendInspectionError(code)
    return value


def _nonblank(value: object, code: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BackendInspectionError(code)
    return value


def _es_mapping(raw: object, index: str, config: ElasticsearchKeywordConfig) -> None:
    root = _mapping(raw, "keyword_mapping_response")
    if set(root) != {index}:
        raise BackendInspectionError("keyword_index_alias_or_scope_mismatch")
    entry = _mapping(root[index], "keyword_mapping_response")
    mapping = _mapping(entry.get("mappings"), "keyword_mapping_response")
    meta = _mapping(mapping.get("_meta"), "keyword_mapping_metadata")
    if (
        meta.get("engineering_rag_mapping_version") != _ES_VERSION
        or meta.get("analyzer") != config.analyzer
        or mapping.get("dynamic") != "strict"
    ):
        raise BackendInspectionError("keyword_mapping_incompatible")
    properties = _mapping(mapping.get("properties"), "keyword_mapping_properties")
    expectations = {
        **dict.fromkeys(_KEYWORD_FIELDS, "keyword"),
        **dict.fromkeys(_TEXT_FIELDS, "text"),
        **dict.fromkeys(_INTEGER_FIELDS, "integer"),
        **dict.fromkeys(_BOOLEAN_FIELDS, "boolean"),
        "source_refs": "object",
        "standard": "object",
    }
    if set(properties) != set(expectations):
        raise BackendInspectionError("keyword_mapping_fields_incompatible")
    for name, expected in expectations.items():
        item = _mapping(properties[name], "keyword_field_mapping_incompatible")
        actual = item.get("type", "object" if "properties" in item or "enabled" in item else None)
        if actual != expected:
            raise BackendInspectionError("keyword_field_mapping_incompatible")
        if name in _TEXT_FIELDS and item.get("analyzer") != config.analyzer:
            raise BackendInspectionError("keyword_text_analyzer_incompatible")
    source = _mapping(properties["source_refs"], "keyword_source_mapping_incompatible")
    standard = _mapping(properties["standard"], "keyword_standard_mapping_incompatible")
    standard_fields = _mapping(standard.get("properties"), "keyword_standard_mapping_incompatible")
    if source.get("enabled") is not False or standard.get("dynamic") != "strict":
        raise BackendInspectionError("keyword_provenance_mapping_incompatible")
    if set(standard_fields) != {
        "standard_name",
        "standard_code",
        "edition",
        "revision",
        "language",
    }:
        raise BackendInspectionError("keyword_standard_mapping_incompatible")
    if any(
        _mapping(value, "keyword_standard_mapping_incompatible").get("type") != "keyword"
        for value in standard_fields.values()
    ):
        raise BackendInspectionError("keyword_standard_mapping_incompatible")


def _index_uuid(client: KeywordInspectionClient, index: str) -> str:
    settings = _mapping(client.indices.get_settings(index=index), "keyword_settings_response")  # type: ignore[attr-defined]
    if set(settings) != {index}:
        raise BackendInspectionError("keyword_settings_scope_mismatch")
    entry = _mapping(settings[index], "keyword_settings_response")
    outer = _mapping(entry.get("settings"), "keyword_settings_response")
    inner = _mapping(outer.get("index"), "keyword_settings_response")
    return _nonblank(inner.get("uuid"), "keyword_index_uuid_missing")


def _es_page(raw: object) -> tuple[list[object], str | None, int | None]:
    body = _mapping(raw, "keyword_search_response")
    if body.get("timed_out") is True:
        raise BackendInspectionError("keyword_inventory_timeout")
    shards = _mapping(body.get("_shards"), "keyword_shard_status_missing")
    if _integer(shards.get("failed"), "keyword_shard_status_missing"):
        raise BackendInspectionError("keyword_inventory_shard_failure")
    hits = _mapping(body.get("hits"), "keyword_hits_missing")
    rows = hits.get("hits")
    if not isinstance(rows, list):
        raise BackendInspectionError("keyword_hits_missing")
    total = hits.get("total")
    count = None
    if isinstance(total, Mapping):
        if total.get("relation") != "eq":
            raise BackendInspectionError("keyword_inventory_total_not_exact")
        count = _integer(total.get("value"), "keyword_inventory_total_invalid")
    scroll_id = body.get("_scroll_id")
    if scroll_id is not None:
        scroll_id = _nonblank(scroll_id, "keyword_scroll_id_invalid")
    return rows, scroll_id, count


def _read_keyword(
    client: KeywordInspectionClient, index: str, config: ElasticsearchKeywordConfig
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    if not bool(client.indices.exists(index=index)):  # type: ignore[attr-defined]
        raise BackendInspectionError("keyword_index_missing")
    _es_mapping(client.indices.get_mapping(index=index), index, config)  # type: ignore[attr-defined]
    uuid = _index_uuid(client, index)
    count = _integer(
        _mapping(client.count(index=index), "keyword_count_response").get("count"),
        "keyword_count_response",
    )
    records: dict[str, dict[str, object]] = {}
    scroll_id = None
    try:
        page = client.search(
            index=index,
            query={"match_all": {}},
            size=_PAGE_SIZE,
            sort=["_doc"],
            scroll="1m",
            track_total_hits=True,
        )
        first = True
        while True:
            candidate_id = _mapping(page, "keyword_search_response").get("_scroll_id")
            if isinstance(candidate_id, str) and candidate_id.strip():
                scroll_id = candidate_id
            rows, next_scroll, total = _es_page(page)
            scroll_id = next_scroll or scroll_id
            if first and total != count:
                raise BackendInspectionError("keyword_inventory_count_changed")
            first = False
            if not rows:
                break
            if scroll_id is None:
                raise BackendInspectionError("keyword_scroll_id_missing")
            for row in rows:
                hit = _mapping(row, "keyword_hit_invalid")
                source = dict(_mapping(hit.get("_source"), "keyword_source_missing"))
                identity = _nonblank(source.get("chunk_id"), "keyword_chunk_id_invalid")
                if hit.get("_id") != identity or hit.get("_index") != index:
                    raise BackendInspectionError("keyword_hit_identity_mismatch")
                if identity in records:
                    raise BackendInspectionError("keyword_duplicate_chunk_id")
                records[identity] = source
            page = client.scroll(scroll_id=scroll_id, scroll="1m")
    finally:
        if scroll_id is not None:
            client.clear_scroll(scroll_id=scroll_id)
    after = _integer(
        _mapping(client.count(index=index), "keyword_count_response").get("count"),
        "keyword_count_response",
    )
    if count != after or count != len(records) or _index_uuid(client, index) != uuid:
        raise BackendInspectionError("keyword_inventory_count_or_identity_changed")
    return records, {"index_uuid": uuid, "count": count, "mapping_version": _ES_VERSION}


def _vector_metadata(
    config: VectorRetrievalConfig, provider: EmbeddingProvider
) -> dict[str, object]:
    if (
        provider.model_id != config.embedding_model_id
        or provider.model_revision != config.embedding_model_revision
    ):
        raise BackendInspectionError("configured_embedding_provider_identity_mismatch")
    dimension = provider.dimension
    if (
        type(dimension) is not int
        or dimension <= 0
        or (config.expected_dimension is not None and dimension != config.expected_dimension)
    ):
        raise BackendInspectionError("configured_embedding_dimension_mismatch")
    return {
        "schema_version": _VECTOR_VERSION,
        "embedding_model_id": provider.model_id,
        "embedding_model_revision": provider.model_revision,
        "dimension": dimension,
        "metric_type": config.metric_type,
        "normalized": config.normalize_embeddings,
        "query_instruction": config.query_instruction,
    }


def _vector_description(raw: object, metadata: dict[str, object]) -> str:
    description = _mapping(raw, "vector_collection_description")
    try:
        actual = json.loads(description.get("description", ""))
    except (ValueError, TypeError):
        raise BackendInspectionError("vector_compatibility_metadata_invalid") from None
    if actual != metadata:
        raise BackendInspectionError("vector_embedding_or_schema_incompatible")
    fields = description.get("fields")
    if not isinstance(fields, list):
        raise BackendInspectionError("vector_field_schema_invalid")
    by_name = {}
    for field in fields:
        item = _mapping(field, "vector_field_schema_invalid")
        name = item.get("name")
        if not isinstance(name, str) or name in by_name:
            raise BackendInspectionError("vector_field_schema_invalid")
        by_name[name] = item
    if set(by_name) != {*_VECTOR_FIELDS, "embedding"}:
        raise BackendInspectionError("vector_field_schema_incompatible")
    expected_types = {
        **dict.fromkeys(_VECTOR_STRINGS, 21),
        **dict.fromkeys(_VECTOR_JSON, 23),
        "page_start": 5,
        "page_end": 5,
        "is_explanation": 1,
        "mandatory_state": 2,
        "embedding": 101,
    }
    if any(by_name[name].get("type") != expected for name, expected in expected_types.items()):
        raise BackendInspectionError("vector_field_types_incompatible")
    vector = _mapping(by_name["embedding"].get("params"), "vector_dimension_missing")
    if str(vector.get("dim")) != str(metadata["dimension"]):
        raise BackendInspectionError("vector_dimension_incompatible")
    if by_name["chunk_id"].get("is_primary") is not True:
        raise BackendInspectionError("vector_primary_key_incompatible")
    collection_id = description.get("collection_id")
    if not isinstance(collection_id, (int, str)) or isinstance(collection_id, bool):
        raise BackendInspectionError("vector_collection_identity_missing")
    return str(collection_id)


def _vector_index(client: VectorInspectionClient, name: str, config: VectorRetrievalConfig) -> None:
    indexes = client.list_indexes(collection_name=name)
    if not isinstance(indexes, list) or not indexes:
        raise BackendInspectionError("vector_index_missing")
    vector_indexes = []
    for index_name in indexes:
        item = _mapping(
            client.describe_index(collection_name=name, index_name=index_name),
            "vector_index_description",
        )
        if item.get("field_name") == "embedding":
            vector_indexes.append(item)
    if len(vector_indexes) != 1:
        raise BackendInspectionError("vector_index_missing_or_ambiguous")
    item = vector_indexes[0]
    if item.get("metric_type") != config.metric_type or item.get("index_type") != config.index_type:
        raise BackendInspectionError("vector_index_incompatible")
    if str(item.get("M")) != str(config.hnsw_m) or str(item.get("efConstruction")) != str(
        config.hnsw_ef_construction
    ):
        raise BackendInspectionError("vector_index_parameters_incompatible")
    if item.get("pending_index_rows", 0) != 0:
        raise BackendInspectionError("vector_index_not_ready")
    state = item.get("state")
    if state is not None and getattr(state, "name", str(state)) != "Finished":
        raise BackendInspectionError("vector_index_not_ready")


def _vector_logical_count(client: VectorInspectionClient, name: str) -> int:
    rows = client.query(
        collection_name=name,
        filter="",
        output_fields=["count(*)"],
        consistency_level="Strong",
    )
    if not isinstance(rows, list) or len(rows) != 1:
        raise BackendInspectionError("vector_strong_count_invalid")
    return _integer(
        _mapping(rows[0], "vector_strong_count_invalid").get("count(*)"),
        "vector_strong_count_invalid",
    )


def _read_vector(
    client: VectorInspectionClient,
    name: str,
    config: VectorRetrievalConfig,
    provider: EmbeddingProvider,
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    if not client.has_collection(collection_name=name):
        raise BackendInspectionError("vector_collection_missing")
    metadata = _vector_metadata(config, provider)
    collection_id = _vector_description(client.describe_collection(collection_name=name), metadata)
    _vector_index(client, name, config)
    stats = _mapping(client.get_collection_stats(collection_name=name), "vector_stats_invalid")
    physical_count = int(str(stats.get("row_count")))
    if physical_count < 0:
        raise BackendInspectionError("vector_stats_invalid")
    # Physical statistics may include historical upserts/tombstones until
    # compaction. Strong count(*) and the full iterator establish live identity.
    count = _vector_logical_count(client, name)
    iterator = client.query_iterator(
        collection_name=name,
        batch_size=_PAGE_SIZE,
        filter="",
        output_fields=sorted(_VECTOR_FIELDS),
        consistency_level="Strong",
    )
    records: dict[str, dict[str, object]] = {}
    try:
        while True:
            rows = iterator.next()  # type: ignore[attr-defined]
            if not isinstance(rows, list):
                raise BackendInspectionError("vector_iterator_response_invalid")
            if not rows:
                break
            for raw in rows:
                row = dict(_mapping(raw, "vector_row_invalid"))
                identity = _nonblank(row.get("chunk_id"), "vector_chunk_id_invalid")
                if identity in records:
                    raise BackendInspectionError("vector_duplicate_chunk_id")
                records[identity] = row
    finally:
        iterator.close()  # type: ignore[attr-defined]
    stats_after = _mapping(
        client.get_collection_stats(collection_name=name), "vector_stats_invalid"
    )
    physical_after = int(str(stats_after.get("row_count")))
    if physical_after < 0:
        raise BackendInspectionError("vector_stats_invalid")
    if (
        _vector_logical_count(client, name) != count
        or len(records) != count
        or _vector_description(client.describe_collection(collection_name=name), metadata)
        != collection_id
    ):
        raise BackendInspectionError("vector_inventory_count_or_identity_changed")
    return records, {
        "collection_id": collection_id,
        "count": count,
        "count_method": "Strong_count_star_and_complete_query_iterator",
        "physical_row_count_statistics_before": physical_count,
        "physical_row_count_statistics_after": physical_after,
        "physical_row_count_is_not_logical_inventory": True,
        "compatibility": metadata,
    }


def _expected_vector(chunk: Chunk) -> dict[str, object]:
    """Document the existing stored-row projection; do not generate embeddings."""
    return {
        "chunk_id": chunk.chunk_id,
        "logical_chunk_id": chunk.logical_chunk_id,
        "document_id": chunk.document_id,
        "content": chunk.content,
        "content_type": chunk.content_type.value,
        "standard_name": chunk.standard.standard_name,
        "standard_code": chunk.standard.standard_code,
        "edition": chunk.standard.edition or "",
        "standard_revision": chunk.standard.revision or "",
        "standard_language": chunk.standard.language or "",
        "clause_id": chunk.clause_id or "",
        "clause_number": chunk.clause_number or "",
        "page_start": chunk.page_start,
        "page_end": chunk.page_end,
        "is_explanation": chunk.is_explanation,
        "mandatory_state": -1 if chunk.is_mandatory is None else int(chunk.is_mandatory),
        "source_refs": [source.model_dump(mode="json") for source in chunk.source_refs],
        "source_block_ids": chunk.source_block_ids,
        "section_path": chunk.section_path,
        "provenance": {
            "schema_version": chunk.schema_version,
            "section_id": chunk.section_id,
            "parent_chunk_id": chunk.parent_chunk_id,
            "table_id": chunk.table_id,
            "figure_id": chunk.figure_id,
            "formula_ids": chunk.formula_ids,
            "related_asset_ids": chunk.related_asset_ids,
            "chunking_version": chunk.chunking_version,
        },
    }


@dataclass(frozen=True)
class VerifiedCorpusCatalog:
    """Immutable exact-selector catalog, minted only after dual inventory checks."""

    snapshot_id: str
    _scope_json: str
    _records_json: tuple[str, ...]

    def lookup(self, request: StandardMetadataLookup) -> StandardMetadataMatch:
        request = StandardMetadataLookup.model_validate_json(request.model_dump_json())
        scope = CatalogIndexScope.model_validate_json(self._scope_json)
        matches = []
        status = "unavailable"
        reason = "requested_index_scope_was_not_verified"
        if request.scope == scope:
            for raw in self._records_json:
                item = StandardMetadataRecord.model_validate_json(raw)
                checks = (
                    (request.document_id, item.document_id),
                    (request.standard_code, item.standard.standard_code),
                    (request.standard_name, item.standard.standard_name),
                    (request.edition, item.standard.edition),
                    (request.revision, item.standard.revision),
                )
                if all(expected is None or expected == actual for expected, actual in checks):
                    matches.append(item)
            status = "not_found" if not matches else "unique" if len(matches) == 1 else "ambiguous"
            reason = None
        return StandardMetadataMatch(
            request_id=request.request_id,
            catalog_id="verified-dual-backend-corpus",
            snapshot_id=self.snapshot_id,
            is_test_fixture=False,
            status=status,
            candidates=matches,
            reason=reason,
        ).validate_for(request)


@dataclass(frozen=True)
class BackendSnapshot:
    snapshot_id: str
    catalog: VerifiedCorpusCatalog
    _diagnostics_json: str

    @property
    def diagnostics(self) -> dict[str, object]:
        """Return a copy so callers cannot mutate the attested snapshot."""
        return json.loads(self._diagnostics_json)


def inspect_backends(
    batch: ChunkBatch,
    *,
    keyword_client: KeywordInspectionClient,
    vector_client: VectorInspectionClient,
    keyword_config: ElasticsearchKeywordConfig,
    vector_config: VectorRetrievalConfig,
    provider: EmbeddingProvider,
    keyword_index: str,
    vector_collection: str,
    corpus_sha256: str,
) -> BackendSnapshot:
    """Inspect complete inventories and reject even same-count identity/content drift.

    Caller must hash the original corpus bytes before constructing ChunkBatch.
    SHA here is an identity declaration, not a claim of independent file access.
    No index, collection, vector or database mutation is created. The injected
    provider's dimension property can initialize its real model; the composition
    root owns that provider's cache/download policy.
    """
    try:
        if re.fullmatch(r"[0-9a-f]{64}", corpus_sha256) is None:
            raise BackendInspectionError("corpus_sha256_invalid")
        batch = ChunkBatch.model_validate_json(batch.model_dump_json())
        if not batch.chunks:
            raise BackendInspectionError("empty_corpus")
        standards = {chunk.standard.model_dump_json() for chunk in batch.chunks}
        if len(standards) != 1:
            raise BackendInspectionError("inconsistent_document_standard_metadata")
        keyword, keyword_evidence = _read_keyword(keyword_client, keyword_index, keyword_config)
        vector, vector_evidence = _read_vector(
            vector_client, vector_collection, vector_config, provider
        )
        expected = {chunk.chunk_id: chunk for chunk in batch.chunks}
        for name, records in (("keyword", keyword), ("vector", vector)):
            if set(records) != set(expected):
                raise BackendInspectionError(f"{name}_corpus_inventory_identity_mismatch")
        for identity, chunk in expected.items():
            expected_keyword = chunk.model_dump(mode="json")
            expected_keyword["search_text"] = chunk.embedding_text
            if _canonical(keyword[identity]) != _canonical(expected_keyword):
                raise BackendInspectionError("keyword_corpus_content_or_metadata_mismatch")
            if _canonical(vector[identity]) != _canonical(_expected_vector(chunk)):
                raise BackendInspectionError("vector_corpus_content_or_metadata_mismatch")
        diagnostics = {
            "corpus_sha256": corpus_sha256,
            "document_ids": [batch.document_id],
            "chunking_version": batch.chunking_version,
            "chunk_count": len(expected),
            "keyword_index": keyword_index,
            "vector_collection": vector_collection,
            "keyword": keyword_evidence,
            "vector": vector_evidence,
            "keyword_inventory_sha256": _digest(keyword),
            "vector_inventory_sha256": _digest(vector),
            "verification": "exact_full_corpus_ids_content_metadata_and_compatibility",
            "embedding_values_independently_recomputed": False,
            "corpus_original_bytes_hashed_by": "composition_root",
        }
        snapshot_id = f"live-{_digest(diagnostics)}"
        scope = CatalogIndexScope(keyword_index=keyword_index, vector_collection=vector_collection)
        record = StandardMetadataRecord(
            record_id=f"corpus-{batch.document_id}",
            document_id=batch.document_id,
            standard=batch.chunks[0].standard.model_copy(deep=True),
            aliases=[],
            indexed_scopes=[scope],
        )
        catalog = VerifiedCorpusCatalog(
            snapshot_id, scope.model_dump_json(), (record.model_dump_json(),)
        )
        return BackendSnapshot(snapshot_id, catalog, _canonical(diagnostics))
    except BackendInspectionError:
        raise
    except Exception:
        raise BackendInspectionError("backend_unavailable_or_invalid_response") from None
