"""OFFLINE client-injection tests: these are not real backend integration results."""

from __future__ import annotations

import copy
import json
from collections.abc import Sequence

import pytest
from scripts._query_smoke_backends import BackendInspectionError, inspect_backends

from engineering_rag.contracts.catalog import CatalogIndexScope, StandardMetadataLookup
from engineering_rag.contracts.chunks import Chunk, ChunkBatch
from engineering_rag.modules.keyword_retrieval.api import ElasticsearchKeywordConfig
from engineering_rag.modules.vector_retrieval.api import VectorRetrievalConfig

KEYWORD = "fictional-smoke-chunks"
VECTOR = "fictional_smoke_vectors"
CORPUS_SHA = "a" * 64


def batch(count: int = 3) -> ChunkBatch:
    chunks = [
        Chunk.model_validate(
            {
                "chunk_id": f"chunk-{index}",
                "logical_chunk_id": f"logical-{index}",
                "document_id": "fictional-document",
                "content": "虚构设备检索演示，不是真实规范条文。",
                "embedding_text": "虚构设备检索演示，不是真实规范条文。",
                "token_count": 20,
                "content_type": "clause",
                "page_start": 1,
                "page_end": 1,
                "source_refs": [
                    {
                        "document_id": "fictional-document",
                        "page_number": 1,
                        "block_id": f"block-{index}",
                    }
                ],
                "source_block_ids": [f"block-{index}"],
                "standard": {
                    "standard_name": "虚构设备标准",
                    "standard_code": "DEMO 0001-2026",
                    "edition": "2026-demo",
                },
                "clause_number": "1.1.1",
                "chunking_version": "fictional-chunker-1",
            }
        )
        for index in range(count)
    ]
    return ChunkBatch(
        document_id="fictional-document",
        chunks=chunks,
        chunking_version="fictional-chunker-1",
        strategy_id="fictional-strategy",
    )


def keyword_mapping() -> dict[str, object]:
    properties = {
        **{
            field: {"type": "keyword"}
            for field in (
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
            )
        },
        **{
            field: {"type": "text", "analyzer": "standard"}
            for field in ("content", "context_header", "embedding_text", "search_text")
        },
        **{field: {"type": "integer"} for field in ("token_count", "page_start", "page_end")},
        **{
            field: {"type": "boolean"}
            for field in ("is_explanation", "is_mandatory", "exceeds_max_tokens")
        },
        "source_refs": {"type": "object", "enabled": False},
        "standard": {
            "type": "object",
            "dynamic": "strict",
            "properties": {
                field: {"type": "keyword"}
                for field in ("standard_name", "standard_code", "edition", "revision", "language")
            },
        },
    }
    return {
        KEYWORD: {
            "mappings": {
                "dynamic": "strict",
                "properties": properties,
                "_meta": {
                    "engineering_rag_mapping_version": "keyword-index-v1",
                    "analyzer": "standard",
                },
            }
        }
    }


def vector_row(chunk: Chunk) -> dict[str, object]:
    return {
        "chunk_id": chunk.chunk_id,
        "logical_chunk_id": chunk.logical_chunk_id,
        "document_id": chunk.document_id,
        "content": chunk.content,
        "content_type": "clause",
        "standard_name": chunk.standard.standard_name,
        "standard_code": chunk.standard.standard_code,
        "edition": chunk.standard.edition,
        "standard_revision": "",
        "standard_language": "",
        "clause_id": "",
        "clause_number": chunk.clause_number,
        "page_start": 1,
        "page_end": 1,
        "is_explanation": False,
        "mandatory_state": -1,
        "source_refs": [ref.model_dump(mode="json") for ref in chunk.source_refs],
        "source_block_ids": chunk.source_block_ids,
        "section_path": [],
        "provenance": {
            "schema_version": "1.0",
            "section_id": None,
            "parent_chunk_id": None,
            "table_id": None,
            "figure_id": None,
            "formula_ids": [],
            "related_asset_ids": [],
            "chunking_version": "fictional-chunker-1",
        },
    }


class OfflineProvider:
    model_id = VectorRetrievalConfig().embedding_model_id
    model_revision = VectorRetrievalConfig().embedding_model_revision
    dimension = 3

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise AssertionError("inventory must not compute or store embeddings")

    def embed_query(self, text: str) -> list[float]:
        raise AssertionError("inventory must not run semantic searches")


class OfflineKeyword:
    """Fictional read-only Elasticsearch response simulator."""

    def __init__(self, corpus: ChunkBatch) -> None:
        self.indices = self
        self.rows = [
            {**chunk.model_dump(mode="json"), "search_text": chunk.embedding_text}
            for chunk in corpus.chunks
        ]
        self.mapping = keyword_mapping()
        self.index_exists = True
        self.uuid = "fictional-uuid"
        self.offset = 0
        self.size = 500
        self.cleared = False
        self.calls: list[str] = []
        self.failed_shards = 0
        self.count_override: int | None = None

    def exists(self, **kwargs: object) -> bool:
        self.calls.append("exists")
        return self.index_exists

    def get_mapping(self, **kwargs: object) -> object:
        self.calls.append("get_mapping")
        return copy.deepcopy(self.mapping)

    def get_settings(self, **kwargs: object) -> object:
        self.calls.append("get_settings")
        return {KEYWORD: {"settings": {"index": {"uuid": self.uuid}}}}

    def count(self, **kwargs: object) -> object:
        self.calls.append("count")
        return {"count": self.count_override if self.count_override is not None else len(self.rows)}

    def _page(self) -> object:
        selected = self.rows[self.offset : self.offset + self.size]
        self.offset += self.size
        return {
            "_scroll_id": "fictional-scroll",
            "timed_out": False,
            "_shards": {"failed": self.failed_shards},
            "hits": {
                "total": {"value": len(self.rows), "relation": "eq"},
                "hits": [
                    {"_id": row["chunk_id"], "_index": KEYWORD, "_source": copy.deepcopy(row)}
                    for row in selected
                ],
            },
        }

    def search(self, **kwargs: object) -> object:
        self.calls.append("search")
        assert kwargs["track_total_hits"] is True and kwargs["query"] == {"match_all": {}}
        self.size = kwargs["size"]
        self.offset = 0
        return self._page()

    def scroll(self, **kwargs: object) -> object:
        self.calls.append("scroll")
        return self._page()

    def clear_scroll(self, **kwargs: object) -> object:
        self.calls.append("clear_scroll")
        self.cleared = True
        return {"succeeded": True}


class OfflineIterator:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.offset = 0
        self.closed = False
        self.call_count = 0

    def next(self) -> list[dict[str, object]]:
        self.call_count += 1
        rows = copy.deepcopy(self.rows[self.offset : self.offset + 500])
        self.offset += 500
        return rows

    def close(self) -> None:
        self.closed = True


class OfflineVector:
    """Fictional read-only Milvus response simulator."""

    def __init__(self, corpus: ChunkBatch) -> None:
        config = VectorRetrievalConfig()
        self.rows = [vector_row(chunk) for chunk in corpus.chunks]
        self.collection_exists = True
        self.index = {
            "field_name": "embedding",
            "index_type": "HNSW",
            "metric_type": "COSINE",
            "M": "16",
            "efConstruction": "200",
            "pending_index_rows": 0,
            "state": "Finished",
        }
        metadata = {
            "schema_version": "vector-collection-v1",
            "embedding_model_id": config.embedding_model_id,
            "embedding_model_revision": config.embedding_model_revision,
            "dimension": 3,
            "metric_type": "COSINE",
            "normalized": True,
            "query_instruction": config.query_instruction,
        }
        fields = [
            {"name": name, "type": 21}
            for name in (
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
            )
        ]
        fields += [
            {"name": name, "type": 23}
            for name in ("source_refs", "source_block_ids", "section_path", "provenance")
        ]
        fields += [{"name": name, "type": 5} for name in ("page_start", "page_end")]
        fields += [
            {"name": "is_explanation", "type": 1},
            {"name": "mandatory_state", "type": 2},
            {"name": "embedding", "type": 101, "params": {"dim": "3"}},
        ]
        fields[0]["is_primary"] = True
        self.description = {
            "collection_id": 123456,
            "description": json.dumps(metadata),
            "fields": fields,
        }
        self.iterator: OfflineIterator | None = None
        self.calls: list[str] = []
        self.count_override: int | None = None

    def has_collection(self, **kwargs: object) -> bool:
        self.calls.append("has_collection")
        return self.collection_exists

    def describe_collection(self, **kwargs: object) -> object:
        self.calls.append("describe_collection")
        return copy.deepcopy(self.description)

    def get_collection_stats(self, **kwargs: object) -> object:
        self.calls.append("get_collection_stats")
        return {
            "row_count": self.count_override if self.count_override is not None else len(self.rows)
        }

    def list_indexes(self, **kwargs: object) -> object:
        self.calls.append("list_indexes")
        return ["embedding"]

    def describe_index(self, **kwargs: object) -> object:
        self.calls.append("describe_index")
        return copy.deepcopy(self.index)

    def query_iterator(self, **kwargs: object) -> object:
        self.calls.append("query_iterator")
        assert (
            kwargs["consistency_level"] == "Strong" and "embedding" not in kwargs["output_fields"]
        )
        assert "limit" not in kwargs and kwargs["filter"] == ""
        self.iterator = OfflineIterator(self.rows)
        return self.iterator

    def query(self, **kwargs: object) -> object:
        self.calls.append("query_count")
        assert kwargs["output_fields"] == ["count(*)"]
        assert kwargs["consistency_level"] == "Strong"
        return [{"count(*)": len(self.rows)}]


def inspect(corpus: ChunkBatch, es: OfflineKeyword, mv: OfflineVector, **options: object):
    kwargs = {
        "keyword_client": es,
        "vector_client": mv,
        "keyword_config": ElasticsearchKeywordConfig(),
        "vector_config": VectorRetrievalConfig(expected_dimension=3),
        "provider": OfflineProvider(),
        "keyword_index": KEYWORD,
        "vector_collection": VECTOR,
        "corpus_sha256": CORPUS_SHA,
    }
    kwargs.update(options)
    return inspect_backends(corpus, **kwargs)


def lookup(snapshot, **selectors: str):
    return snapshot.catalog.lookup(
        StandardMetadataLookup(
            request_id="fictional-lookup",
            scope=CatalogIndexScope(keyword_index=KEYWORD, vector_collection=VECTOR),
            **selectors,
        )
    )


def test_offline_exact_inventory_mints_bound_immutable_catalog() -> None:
    corpus = batch()
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    snapshot = inspect(corpus, es, mv)
    assert es.cleared and mv.iterator.closed
    assert snapshot.diagnostics["chunk_count"] == 3
    assert snapshot.diagnostics["embedding_values_independently_recomputed"] is False
    found = lookup(snapshot, standard_code="DEMO 0001-2026")
    assert found.status == "unique" and found.is_test_fixture is False
    assert found.candidates[0].aliases == []
    assert found.candidates[0].document_id == corpus.document_id
    assert found.snapshot_id == snapshot.snapshot_id
    altered = snapshot.diagnostics
    altered["keyword"]["count"] = 999
    assert snapshot.diagnostics["keyword"]["count"] == 3
    found.candidates[0].standard.standard_code = "mutated"
    assert lookup(snapshot, standard_code="DEMO 0001-2026").status == "unique"
    assert inspect(corpus, es, mv).snapshot_id == snapshot.snapshot_id


def test_offline_more_than_ten_thousand_records_not_silently_capped() -> None:
    corpus = batch(10005)
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    snapshot = inspect(corpus, es, mv)
    assert snapshot.diagnostics["chunk_count"] == 10005
    assert es.calls.count("scroll") > 20 and mv.iterator.call_count > 20


@pytest.mark.parametrize("side", ["keyword", "vector"])
def test_offline_missing_or_extra_chunk_rejected_even_if_counts_seem_plausible(side: str) -> None:
    corpus = batch()
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    target = es.rows if side == "keyword" else mv.rows
    target[0]["chunk_id"] = "wrong-same-count"
    with pytest.raises(BackendInspectionError, match=f"{side}_corpus_inventory_identity_mismatch"):
        inspect(corpus, es, mv)


@pytest.mark.parametrize("side", ["keyword", "vector"])
def test_offline_unexpected_document_never_filtered_away(side: str) -> None:
    corpus = batch()
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    target = es.rows if side == "keyword" else mv.rows
    target[0]["document_id"] = "unexpected-document"
    with pytest.raises(BackendInspectionError, match=f"{side}_corpus_content_or_metadata_mismatch"):
        inspect(corpus, es, mv)


@pytest.mark.parametrize("side", ["keyword", "vector"])
@pytest.mark.parametrize(
    "field", ["content", "logical_chunk_id", "clause_number", "page_start", "source_refs"]
)
def test_offline_content_and_provenance_drift_rejected(side: str, field: str) -> None:
    corpus = batch()
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    target = es.rows if side == "keyword" else mv.rows
    target[0][field] = "wrong"
    with pytest.raises(BackendInspectionError, match=f"{side}_corpus_content_or_metadata_mismatch"):
        inspect(corpus, es, mv)


@pytest.mark.parametrize("side", ["keyword", "vector"])
def test_offline_duplicate_chunk_is_not_hidden_by_dictionary(side: str) -> None:
    corpus = batch()
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    target = es.rows if side == "keyword" else mv.rows
    target.append(copy.deepcopy(target[0]))
    with pytest.raises(BackendInspectionError, match=f"{side}_duplicate_chunk_id"):
        inspect(corpus, es, mv)
    assert es.cleared
    if side == "vector":
        assert mv.iterator.closed


@pytest.mark.parametrize("side", ["keyword", "vector"])
def test_offline_backend_missing_is_not_an_empty_success(side: str) -> None:
    corpus = batch()
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    es.index_exists = side != "keyword"
    mv.collection_exists = side != "vector"
    with pytest.raises(BackendInspectionError, match=f"{side}_(index|collection)_missing"):
        inspect(corpus, es, mv)


def test_offline_mapping_type_and_version_are_checked() -> None:
    corpus = batch()
    for bad in ("version", "field"):
        es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
        mapping = es.mapping[KEYWORD]["mappings"]
        if bad == "version":
            mapping["_meta"]["engineering_rag_mapping_version"] = "wrong"
        else:
            mapping["properties"]["is_mandatory"]["type"] = "keyword"
        with pytest.raises(BackendInspectionError, match="keyword_.*incompatible"):
            inspect(corpus, es, mv)


@pytest.mark.parametrize(
    "field,value",
    [("dimension", 4), ("embedding_model_revision", "wrong"), ("query_instruction", "wrong")],
)
def test_offline_same_dimension_does_not_bypass_embedding_identity(
    field: str, value: object
) -> None:
    corpus = batch()
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    metadata = json.loads(mv.description["description"])
    metadata[field] = value
    mv.description["description"] = json.dumps(metadata)
    with pytest.raises(BackendInspectionError, match="vector_embedding_or_schema_incompatible"):
        inspect(corpus, es, mv)


@pytest.mark.parametrize(
    "field,value",
    [("metric_type", "L2"), ("index_type", "FLAT"), ("M", "32"), ("pending_index_rows", 2)],
)
def test_offline_actual_index_type_metric_parameters_and_readiness(
    field: str, value: object
) -> None:
    corpus = batch()
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    mv.index[field] = value
    with pytest.raises(BackendInspectionError, match="vector_index_"):
        inspect(corpus, es, mv)


def test_offline_failed_shard_is_rejected_and_scroll_context_closed() -> None:
    corpus = batch()
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    es.failed_shards = 1
    with pytest.raises(BackendInspectionError, match="keyword_inventory_shard_failure"):
        inspect(corpus, es, mv)
    assert es.cleared


def test_offline_exception_messages_cannot_leak_server_secret() -> None:
    class SecretFailure(OfflineKeyword):
        def get_mapping(self, **kwargs: object) -> object:
            raise RuntimeError("SECRET_API_KEY=do-not-log https://user:password@server")

    corpus = batch()
    with pytest.raises(BackendInspectionError) as captured:
        inspect(corpus, SecretFailure(corpus), OfflineVector(corpus))
    assert captured.value.code == "backend_unavailable_or_invalid_response"
    assert "SECRET" not in str(captured.value) and "password" not in str(captured.value)


def test_offline_catalog_rejects_untrusted_aliases_and_other_scope() -> None:
    corpus = batch()
    snapshot = inspect(corpus, OfflineKeyword(corpus), OfflineVector(corpus))
    assert lookup(snapshot, standard_name="虚构设备标准").status == "unique"
    assert lookup(snapshot, standard_name="设备规范简称").status == "not_found"
    assert lookup(snapshot, standard_code="DEMO 0001-2026", edition="other").status == "not_found"
    request = StandardMetadataLookup(
        request_id="different-scope",
        scope=CatalogIndexScope(keyword_index="other", vector_collection=VECTOR),
        document_id=corpus.document_id,
    )
    answer = snapshot.catalog.lookup(request)
    assert answer.status == "unavailable" and answer.candidates == []


def test_offline_empty_corpus_and_bad_hash_not_attested() -> None:
    corpus = batch(0)
    with pytest.raises(BackendInspectionError, match="empty_corpus"):
        inspect(corpus, OfflineKeyword(corpus), OfflineVector(corpus))
    corpus = batch()
    with pytest.raises(BackendInspectionError, match="corpus_sha256_invalid"):
        inspect(corpus, OfflineKeyword(corpus), OfflineVector(corpus), corpus_sha256="invalid")


def test_offline_inconsistent_document_standard_fails_before_reading_backend() -> None:
    corpus = batch()
    corpus.chunks[1].standard.edition = "different"
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    with pytest.raises(BackendInspectionError, match="inconsistent_document_standard_metadata"):
        inspect(corpus, es, mv)
    assert es.calls == [] and mv.calls == []


def test_offline_physical_upsert_statistics_not_mistaken_for_duplicate_live_chunks() -> None:
    corpus = batch()
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    mv.count_override = 2 * len(corpus.chunks)
    snapshot = inspect(corpus, es, mv)
    assert snapshot.diagnostics["vector"]["count"] == 3
    assert snapshot.diagnostics["vector"]["physical_row_count_statistics_before"] == 6
    assert snapshot.diagnostics["vector"]["physical_row_count_is_not_logical_inventory"] is True


def test_offline_unfinished_index_is_not_declared_ready() -> None:
    corpus = batch()
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    mv.index["state"] = "InProgress"
    with pytest.raises(BackendInspectionError, match="vector_index_not_ready"):
        inspect(corpus, es, mv)


def test_offline_strong_count_must_match_live_iterator_not_storage_statistics() -> None:
    class BadLogicalCount(OfflineVector):
        def query(self, **kwargs: object) -> object:
            return [{"count(*)": 2}]

    corpus = batch()
    es, mv = OfflineKeyword(corpus), BadLogicalCount(corpus)
    with pytest.raises(BackendInspectionError, match="vector_inventory_count_or_identity_changed"):
        inspect(corpus, es, mv)
    assert mv.iterator.closed


@pytest.mark.parametrize("kind", ["type", "dimension", "primary"])
def test_offline_actual_vector_field_definitions_not_only_description_checked(kind: str) -> None:
    corpus = batch()
    es, mv = OfflineKeyword(corpus), OfflineVector(corpus)
    fields = {field["name"]: field for field in mv.description["fields"]}
    if kind == "type":
        fields["is_explanation"]["type"] = 21
    elif kind == "dimension":
        fields["embedding"]["params"]["dim"] = "4"
    else:
        fields["chunk_id"]["is_primary"] = False
    with pytest.raises(
        BackendInspectionError, match="vector_(field_types|dimension|primary_key)_incompatible"
    ):
        inspect(corpus, es, mv)


def test_offline_provider_identity_cannot_disagree_with_active_configuration() -> None:
    provider = OfflineProvider()
    provider.model_revision = "different-model-revision"
    corpus = batch()
    with pytest.raises(
        BackendInspectionError, match="configured_embedding_provider_identity_mismatch"
    ):
        inspect(corpus, OfflineKeyword(corpus), OfflineVector(corpus), provider=provider)
