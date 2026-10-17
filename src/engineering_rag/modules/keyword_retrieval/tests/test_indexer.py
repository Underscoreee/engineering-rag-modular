import pytest
from pydantic import ValidationError

from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.retrieval import IndexRequest
from engineering_rag.modules.keyword_retrieval.internal.config import ElasticsearchKeywordConfig
from engineering_rag.modules.keyword_retrieval.internal.errors import (
    KeywordBackendError,
    KeywordIndexCompatibilityError,
)
from engineering_rag.modules.keyword_retrieval.internal.indexer import index_batch

from .helpers import FakeElasticsearchClient, make_batch, make_chunk


def test_first_index_creates_mapping_and_bulk_uses_chunk_id() -> None:
    client = FakeElasticsearchClient()
    chunk = make_chunk()

    result = index_batch(
        client,
        ElasticsearchKeywordConfig(),
        make_batch(chunk),
        IndexRequest(index_name="chunks", operation_id="op-1"),
    )

    assert result.attempted == result.indexed == 1
    assert not result.failures
    assert len(client.indices.create_calls) == 1
    operations = client.bulk_calls[0]["operations"]
    assert operations[0] == {"index": {"_index": "chunks", "_id": chunk.chunk_id}}
    assert operations[1]["search_text"] == chunk.embedding_text
    assert operations[1]["source_refs"][0]["block_id"] == chunk.source_block_ids[0]


def test_existing_compatible_index_is_not_created_again_and_upsert_is_idempotent() -> None:
    client = FakeElasticsearchClient()
    request = IndexRequest(index_name="chunks", operation_id="op-1", replace_document=False)
    batch = make_batch()
    config = ElasticsearchKeywordConfig()

    index_batch(client, config, batch, request)
    index_batch(client, config, batch, request.model_copy(update={"operation_id": "op-2"}))

    assert len(client.indices.create_calls) == 1
    assert list(client.documents["chunks"]) == ["chunk-1"]


def test_existing_incompatible_mapping_is_rejected() -> None:
    client = FakeElasticsearchClient()
    client.indices.mappings["chunks"] = {"properties": {}}

    with pytest.raises(KeywordIndexCompatibilityError):
        index_batch(
            client,
            ElasticsearchKeywordConfig(),
            make_batch(),
            IndexRequest(index_name="chunks", operation_id="op-1"),
        )


def test_bulk_partial_failure_is_reported_and_skips_stale_cleanup() -> None:
    client = FakeElasticsearchClient()
    client.bulk_response = {
        "errors": True,
        "items": [
            {"index": {"status": 201}},
            {
                "index": {
                    "status": 429,
                    "error": {"type": "rejected_execution", "reason": "busy"},
                }
            },
        ],
    }

    result = index_batch(
        client,
        ElasticsearchKeywordConfig(),
        make_batch(make_chunk("chunk-1"), make_chunk("chunk-2")),
        IndexRequest(index_name="chunks", operation_id="op-1"),
    )

    assert result.indexed == 1
    assert result.failures[0].chunk_id == "chunk-2"
    assert result.failures[0].error.retryable is True
    assert client.delete_calls == []


def test_bulk_complete_item_failure_reports_zero_indexed() -> None:
    client = FakeElasticsearchClient()
    client.bulk_response = {
        "errors": True,
        "items": [
            {
                "index": {
                    "status": 400,
                    "error": {"type": "mapper_parsing_exception", "reason": "bad field"},
                }
            }
        ],
    }

    result = index_batch(
        client,
        ElasticsearchKeywordConfig(),
        make_batch(),
        IndexRequest(index_name="chunks", operation_id="op-failed"),
    )

    assert result.indexed == 0
    assert len(result.failures) == 1
    assert result.failures[0].error.retryable is False
    assert client.delete_calls == []


def test_bulk_transport_failure_is_not_reported_as_success() -> None:
    client = FakeElasticsearchClient()
    client.bulk_exception = RuntimeError("bulk unavailable")

    with pytest.raises(KeywordBackendError):
        index_batch(
            client,
            ElasticsearchKeywordConfig(),
            make_batch(),
            IndexRequest(index_name="chunks", operation_id="op-1"),
        )


def test_replace_document_removes_only_stale_chunks_after_success() -> None:
    client = FakeElasticsearchClient()
    config = ElasticsearchKeywordConfig()
    additive = IndexRequest(index_name="chunks", operation_id="op-1", replace_document=False)
    index_batch(
        client,
        config,
        make_batch(make_chunk("old"), make_chunk("keep")),
        additive,
    )
    index_batch(
        client,
        config,
        make_batch(make_chunk("other", document_id="doc-other")),
        additive.model_copy(update={"operation_id": "op-other"}),
    )

    index_batch(
        client,
        config,
        make_batch(make_chunk("keep", content="更新后的内容")),
        IndexRequest(index_name="chunks", operation_id="op-2", replace_document=True),
    )

    assert set(client.documents["chunks"]) == {"keep", "other"}
    assert client.documents["chunks"]["keep"]["content"] == "更新后的内容"
    assert client.delete_calls[-1]["query"]["bool"]["must_not"] == [
        {"terms": {"chunk_id": ["keep"]}}
    ]


def test_empty_batch_does_not_create_index_or_delete_existing_document() -> None:
    client = FakeElasticsearchClient()
    empty = ChunkBatch(
        document_id="doc-1",
        chunks=[],
        chunking_version="clause-first-1.0.0",
        strategy_id="clause-first-v1",
    )

    result = index_batch(
        client,
        ElasticsearchKeywordConfig(),
        empty,
        IndexRequest(index_name="chunks", operation_id="op-empty"),
    )

    assert result.attempted == result.indexed == 0
    assert client.indices.create_calls == client.delete_calls == []


def test_revalidation_rejects_constructed_duplicate_chunk_ids() -> None:
    duplicate = make_chunk()
    invalid = ChunkBatch.model_construct(
        schema_version="1.0",
        document_id="doc-1",
        chunks=[duplicate, duplicate],
        chunking_version="clause-first-1.0.0",
        strategy_id="clause-first-v1",
        source_document_artifact=None,
    )

    with pytest.raises(ValidationError):
        index_batch(
            FakeElasticsearchClient(),
            ElasticsearchKeywordConfig(),
            invalid,
            IndexRequest(index_name="chunks", operation_id="op-invalid"),
        )
