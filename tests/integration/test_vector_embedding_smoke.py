"""Opt-in real BGE model plus real Milvus smoke test."""

from __future__ import annotations

import math
import os
import uuid
from pathlib import Path
from urllib.parse import urlparse

import pytest

from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.retrieval import IndexRequest, VectorSearchRequest
from engineering_rag.modules.vector_retrieval.api import (
    SentenceTransformerEmbeddingProvider,
    VectorRetrievalConfig,
    create_vector_retrieval_service,
)
from engineering_rag.modules.vector_retrieval.internal.config import DEFAULT_EMBEDDING_REVISION
from engineering_rag.modules.vector_retrieval.internal.milvus_client import create_milvus_client

MILVUS_URI = os.getenv("MILVUS_URI")
RUN_REAL_MODEL = os.getenv("ENGINEERING_RAG_RUN_REAL_EMBEDDING") == "1"
pytestmark = [
    pytest.mark.real_embedding,
    pytest.mark.real_milvus,
    pytest.mark.skipif(not RUN_REAL_MODEL, reason="real embedding smoke is not enabled"),
    pytest.mark.skipif(not MILVUS_URI, reason="MILVUS_URI is not configured"),
]


def test_real_bge_vectors_enter_real_milvus_search() -> None:
    assert MILVUS_URI is not None
    parsed = urlparse(MILVUS_URI)
    assert parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    collection = f"engineering_rag_task4_embedding_{uuid.uuid4().hex}"
    config = VectorRetrievalConfig(
        milvus_uri=MILVUS_URI,
        embedding_model_id="BAAI/bge-small-zh-v1.5",
        embedding_model_revision=DEFAULT_EMBEDDING_REVISION,
        embedding_device="cpu",
        embedding_cache_dir=Path(".local/embedding-models"),
        write_batch_size=2,
    )
    provider = SentenceTransformerEmbeddingProvider(config)
    documents = ["混凝土构件应满足承载力要求。", "设备检修空间应便于维护。"]
    vectors = provider.embed_documents(documents)
    query_vector = provider.embed_query("混凝土承载力")
    assert provider.dimension == 512
    assert len(vectors) == 2
    assert all(len(vector) == provider.dimension for vector in [*vectors, query_vector])
    assert all(math.isfinite(value) for vector in [*vectors, query_vector] for value in vector)

    batch = _load_example_batch()
    try:
        with create_vector_retrieval_service(config, embedding_provider=provider) as service:
            indexed = service.index(
                batch,
                IndexRequest(index_name=collection, operation_id="real-bge-smoke"),
            )
            assert indexed.indexed == len(batch.chunks)
            hits = service.search(
                VectorSearchRequest(
                    query="检修空间",
                    top_k=2,
                    index_name=collection,
                    embedding_model_id=provider.model_id,
                )
            )
            assert len(hits) == 2
            assert hits[0].score >= hits[1].score
    finally:
        cleanup = create_milvus_client(config)
        try:
            if cleanup.has_collection(collection_name=collection):
                cleanup.drop_collection(collection_name=collection)  # type: ignore[attr-defined]
        finally:
            cleanup.close()


def _load_example_batch() -> ChunkBatch:
    path = Path(__file__).parents[2] / "examples/chunk_batch.example.json"
    return ChunkBatch.model_validate_json(path.read_text(encoding="utf-8"))
