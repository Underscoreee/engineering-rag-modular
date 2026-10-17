from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.retrieval import (
    IndexRequest,
    SearchFilters,
    VectorSearchRequest,
)
from engineering_rag.modules.vector_retrieval.api import (
    CollectionCompatibilityError,
    InvalidEmbeddingError,
    MilvusConnectionError,
    VectorRetrievalConfig,
    VectorTimeoutError,
    create_vector_retrieval_service,
)
from engineering_rag.modules.vector_retrieval.internal.collection_schema import (
    REQUIRED_FIELDS,
    compatibility_metadata,
)
from engineering_rag.modules.vector_retrieval.internal.embeddings import validate_vectors
from engineering_rag.modules.vector_retrieval.internal.milvus_client import translated_milvus_error
from engineering_rag.modules.vector_retrieval.internal.searcher import build_filter_expression


class DeterministicEmbeddingProvider:
    model_id = "test/engineering-embedding"
    model_revision = "1"
    dimension = 3

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [[float(position + 1), 0.5, 0.25] for position, _ in enumerate(texts)]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.5, 0.25]


class FakeMilvusClient:
    def __init__(self, config: VectorRetrievalConfig, provider: DeterministicEmbeddingProvider):
        self.rows: dict[str, dict[str, object]] = {}
        self.description = json.dumps(
            compatibility_metadata(config, provider), ensure_ascii=False, sort_keys=True
        )
        self.dimension = provider.dimension
        self.closed = False
        self.delete_calls = 0
        self.last_filter = ""
        self.fail_upsert = False

    def has_collection(self, collection_name: str, **kwargs: object) -> bool:
        return True

    def describe_collection(self, collection_name: str, **kwargs: object) -> dict[str, object]:
        fields = [
            {"name": name, "params": {}, "is_primary": name == "chunk_id"}
            for name in sorted(REQUIRED_FIELDS)
        ]
        next(field for field in fields if field["name"] == "embedding")["params"] = {
            "dim": self.dimension
        }
        return {"description": self.description, "fields": fields}

    def create_schema(self, **kwargs: object) -> object:
        raise AssertionError("existing fake collection must not be recreated")

    def prepare_index_params(self, **kwargs: object) -> object:
        raise AssertionError("existing fake collection must not be recreated")

    def create_collection(self, collection_name: str, **kwargs: object) -> None:
        raise AssertionError("existing fake collection must not be recreated")

    def load_collection(self, collection_name: str, **kwargs: object) -> None:
        return None

    def upsert(
        self, collection_name: str, data: Sequence[dict[str, object]], **kwargs: object
    ) -> object:
        if self.fail_upsert:
            raise RuntimeError("injected upsert failure")
        for row in data:
            self.rows[str(row["chunk_id"])] = dict(row)
        return {"upsert_count": len(data)}

    def query(self, collection_name: str, **kwargs: object) -> list[dict[str, object]]:
        expression = str(kwargs.get("filter", ""))
        document_id = _expression_value(expression)
        return [
            {"chunk_id": row["chunk_id"]}
            for row in self.rows.values()
            if row["document_id"] == document_id
        ]

    def search(self, collection_name: str, **kwargs: object) -> list[list[dict[str, object]]]:
        self.last_filter = str(kwargs.get("filter", ""))
        limit = int(kwargs["limit"])
        hits = [
            {"distance": 0.95 - position * 0.1, "entity": row}
            for position, row in enumerate(self.rows.values())
        ]
        return [hits[:limit]]

    def delete(self, collection_name: str, **kwargs: object) -> object:
        self.delete_calls += 1
        expression = str(kwargs.get("filter", ""))
        document_id = _expression_value(expression)
        self.rows = {
            chunk_id: row
            for chunk_id, row in self.rows.items()
            if row["document_id"] != document_id
        }
        return {"delete_count": 0}

    def close(self) -> None:
        self.closed = True


def _expression_value(expression: str) -> str:
    if "==" not in expression:
        return ""
    return json.loads(expression.split("==", maxsplit=1)[1].strip())


def _batch() -> ChunkBatch:
    path = Path(__file__).parents[5] / "examples/chunk_batch.example.json"
    return ChunkBatch.model_validate_json(path.read_text(encoding="utf-8"))


def _components() -> tuple[VectorRetrievalConfig, DeterministicEmbeddingProvider, FakeMilvusClient]:
    config = VectorRetrievalConfig(expected_dimension=3, write_batch_size=1)
    provider = DeterministicEmbeddingProvider()
    return config, provider, FakeMilvusClient(config, provider)


def test_validate_vectors_rejects_count_dimension_and_nonfinite_values() -> None:
    with pytest.raises(InvalidEmbeddingError, match="count"):
        validate_vectors([], expected_count=1, dimension=3)
    with pytest.raises(InvalidEmbeddingError, match="dimension"):
        validate_vectors([[1.0]], expected_count=1, dimension=3)
    with pytest.raises(InvalidEmbeddingError, match="finite"):
        validate_vectors([[1.0, float("nan"), 2.0]], expected_count=1, dimension=3)


def test_backend_error_translation_distinguishes_timeout_and_connection() -> None:
    assert isinstance(
        translated_milvus_error(RuntimeError("deadline exceeded"), "search failed"),
        VectorTimeoutError,
    )
    assert isinstance(
        translated_milvus_error(RuntimeError("connection unavailable"), "search failed"),
        MilvusConnectionError,
    )


def test_index_is_batched_idempotent_and_preserves_metadata() -> None:
    config, provider, client = _components()
    service = create_vector_retrieval_service(config, client=client, embedding_provider=provider)
    batch = _batch()
    request = IndexRequest(index_name="test_chunks", operation_id="op-1")

    first = service.index(batch, request)
    second = service.index(batch, request.model_copy(update={"operation_id": "op-2"}))

    assert first.indexed == second.indexed == len(batch.chunks)
    assert len(client.rows) == len(batch.chunks)
    first_row = client.rows[batch.chunks[0].chunk_id]
    assert first_row["embedding"] == [1.0, 0.5, 0.25]
    assert first_row["source_refs"]
    assert first_row["standard_code"] == batch.chunks[0].standard.standard_code


def test_failed_upsert_never_runs_snapshot_cleanup() -> None:
    config, provider, client = _components()
    client.fail_upsert = True
    service = create_vector_retrieval_service(config, client=client, embedding_provider=provider)
    with pytest.raises(Exception, match="upsert failed"):
        service.index(
            _batch(),
            IndexRequest(index_name="test_chunks", operation_id="op-fail"),
        )
    assert client.delete_calls == 0


def test_search_returns_vector_results_and_forwards_safe_filters() -> None:
    config, provider, client = _components()
    service = create_vector_retrieval_service(config, client=client, embedding_provider=provider)
    batch = _batch()
    service.index(batch, IndexRequest(index_name="test_chunks", operation_id="op-1"))

    results = service.search(
        VectorSearchRequest(
            query="检修空间",
            top_k=1,
            index_name="test_chunks",
            embedding_model_id=provider.model_id,
            filters=SearchFilters(
                document_ids=[batch.document_id],
                standard_codes=[batch.chunks[0].standard.standard_code],
                content_types=[batch.chunks[0].content_type],
                is_explanation=False,
                is_mandatory=True,
            ),
        )
    )

    assert len(results) == 1
    assert results[0].score == 0.95
    assert results[0].rank == 1
    assert results[0].retrieval_source == "vector"
    assert results[0].score_type == "cosine_similarity"
    assert "document_id in" in client.last_filter
    assert "mandatory_state == 1" in client.last_filter


def test_filter_builder_escapes_values_and_combines_fields() -> None:
    expression = build_filter_expression(
        SearchFilters(document_ids=['doc" or true'], clause_numbers=["3.3.2"])
    )
    assert 'document_id in ["doc\\" or true"]' in expression
    assert 'clause_number in ["3.3.2"]' in expression
    assert " and " in expression


def test_incompatible_collection_is_rejected_without_deletion() -> None:
    config, provider, client = _components()
    client.description = json.dumps({"schema_version": "wrong"})
    service = create_vector_retrieval_service(config, client=client, embedding_provider=provider)
    with pytest.raises(CollectionCompatibilityError):
        service.index(_batch(), IndexRequest(index_name="test_chunks", operation_id="op-conflict"))
    assert client.delete_calls == 0


def test_delete_document_is_scoped_and_returns_count() -> None:
    config, provider, client = _components()
    service = create_vector_retrieval_service(config, client=client, embedding_provider=provider)
    batch = _batch()
    service.index(batch, IndexRequest(index_name="test_chunks", operation_id="op-1"))

    deleted = service.delete_document(batch.document_id, "test_chunks")

    assert deleted.index_existed is True
    assert deleted.deleted_count == len(batch.chunks)
    assert client.rows == {}
