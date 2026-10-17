"""Real Milvus integration; enabled only with an explicit local service URI."""

from __future__ import annotations

import os
import uuid
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlparse

import pytest

from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.retrieval import IndexRequest, SearchFilters, VectorSearchRequest
from engineering_rag.modules.vector_retrieval.api import (
    VectorRetrievalConfig,
    create_vector_retrieval_service,
)
from engineering_rag.modules.vector_retrieval.internal.collection_schema import (
    SCALAR_FILTER_FIELDS,
    VECTOR_FIELD,
)
from engineering_rag.modules.vector_retrieval.internal.milvus_client import create_milvus_client

MILVUS_URI = os.getenv("MILVUS_URI")
pytestmark = [
    pytest.mark.real_milvus,
    pytest.mark.skipif(not MILVUS_URI, reason="MILVUS_URI is not configured"),
]


class DeterministicProvider:
    model_id = "integration/deterministic-v1"
    model_revision = "1"
    dimension = 4

    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._encode(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._encode(text)

    @staticmethod
    def _encode(text: str) -> list[float]:
        # Stable semantic-ish fixture: the first two dimensions distinguish our two example chunks.
        return [
            1.0 if "检修" in text else 0.0,
            1.0 if "说明" in text else 0.0,
            min(len(text), 1000) / 1000,
            0.5,
        ]


def test_real_milvus_index_search_filter_persistence_and_delete() -> None:
    assert MILVUS_URI is not None
    _require_local_service(MILVUS_URI)
    collection = f"engineering_rag_task4_test_{uuid.uuid4().hex}"
    batch = _load_example_batch()
    provider = DeterministicProvider()
    config = VectorRetrievalConfig(
        milvus_uri=MILVUS_URI,
        expected_dimension=provider.dimension,
        embedding_model_id=provider.model_id,
        embedding_model_revision=provider.model_revision,
        write_batch_size=1,
    )

    try:
        # First service creates schema/HNSW and writes through the public index() API.
        with create_vector_retrieval_service(config, embedding_provider=provider) as first:
            result = first.index(
                batch,
                IndexRequest(
                    index_name=collection,
                    operation_id="real-milvus-index-1",
                    replace_document=True,
                ),
            )
            assert result.attempted == result.indexed == len(batch.chunks)
            assert result.failures == []

        inspection = create_milvus_client(config)
        try:
            actual_indexes = set(
                inspection.list_indexes(collection_name=collection)  # type: ignore[attr-defined]
            )
            assert actual_indexes == {VECTOR_FIELD, *SCALAR_FILTER_FIELDS}
        finally:
            inspection.close()

        # A newly constructed client/service proves persistence outside the first client lifecycle.
        with create_vector_retrieval_service(config, embedding_provider=provider) as reconnected:
            hits = reconnected.search(
                VectorSearchRequest(
                    query="检修空间",
                    top_k=1,
                    index_name=collection,
                    embedding_model_id=provider.model_id,
                    filters=SearchFilters(
                        document_ids=[batch.document_id],
                        standard_codes=[batch.chunks[0].standard.standard_code],
                        editions=[batch.chunks[0].standard.edition],
                        clause_numbers=[batch.chunks[0].clause_number],
                        content_types=[batch.chunks[0].content_type],
                        is_explanation=batch.chunks[0].is_explanation,
                        is_mandatory=batch.chunks[0].is_mandatory,
                    ),
                )
            )
            assert len(hits) == 1
            assert hits[0].chunk_id == batch.chunks[0].chunk_id
            assert hits[0].score > 0
            assert hits[0].retrieval_source == "vector"
            assert hits[0].content == batch.chunks[0].content
            assert (hits[0].page_start, hits[0].page_end) == (
                batch.chunks[0].page_start,
                batch.chunks[0].page_end,
            )

            deleted = reconnected.delete_document(batch.document_id, collection)
            assert deleted.deleted_count == len(batch.chunks)
            assert (
                reconnected.search(
                    VectorSearchRequest(query="检修空间", top_k=5, index_name=collection)
                )
                == []
            )
    finally:
        # The UUID collection is the only resource this test is authorized to remove.
        cleanup = create_milvus_client(config)
        try:
            if cleanup.has_collection(collection_name=collection):
                cleanup.drop_collection(collection_name=collection)  # type: ignore[attr-defined]
        finally:
            cleanup.close()


def _load_example_batch() -> ChunkBatch:
    path = Path(__file__).parents[2] / "examples/chunk_batch.example.json"
    return ChunkBatch.model_validate_json(path.read_text(encoding="utf-8"))


def _require_local_service(uri: str) -> None:
    parsed = urlparse(uri)
    if parsed.scheme not in {"http", "https"}:
        raise RuntimeError("real Milvus test requires an explicit HTTP(S) URI")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("real Milvus test only allows a localhost service")
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeError("real Milvus test URI must not contain credentials")
