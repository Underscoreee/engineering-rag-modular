"""Optional persistence test against a real, explicitly configured Elasticsearch 8.x."""

from __future__ import annotations

import os
import uuid

import pytest

from engineering_rag.contracts.retrieval import IndexRequest, KeywordSearchRequest, SearchFilters
from engineering_rag.modules.keyword_retrieval.api import (
    ElasticsearchKeywordConfig,
    create_keyword_retrieval_service,
)
from engineering_rag.modules.keyword_retrieval.internal.client import create_elasticsearch_client
from engineering_rag.modules.keyword_retrieval.tests.helpers import make_batch, make_chunk

pytestmark = [
    pytest.mark.real_elasticsearch,
    pytest.mark.skipif(
        not os.getenv("ELASTICSEARCH_URL"),
        reason="set ELASTICSEARCH_URL to run real Elasticsearch persistence tests",
    ),
]


def test_real_bm25_persistence_filter_and_delete() -> None:
    index_name = f"engineering-rag-task3-test-{uuid.uuid4().hex}"
    config = ElasticsearchKeywordConfig.from_env()
    first = make_chunk("chunk-real-a", content="TASK3PERSISTENT 检修空间测试内容。")
    second = make_chunk(
        "chunk-real-b",
        document_id="doc-2",
        content="TASK3PERSISTENT 另一份文档测试内容。",
    )

    try:
        with create_keyword_retrieval_service(config) as service:
            indexed = service.index(
                make_batch(first),
                IndexRequest(index_name=index_name, operation_id="real-index-a"),
            )
            service.index(
                make_batch(second),
                IndexRequest(
                    index_name=index_name,
                    operation_id="real-index-b",
                    replace_document=False,
                ),
            )
            assert indexed.indexed == 1

        with create_keyword_retrieval_service(config) as reconnected:
            hits = reconnected.search(
                KeywordSearchRequest(
                    query="TASK3PERSISTENT",
                    top_k=5,
                    index_name=index_name,
                    filters=SearchFilters(document_ids=["doc-1"]),
                )
            )
            assert [hit.chunk_id for hit in hits] == ["chunk-real-a"]
            assert hits[0].score > 0
            assert hits[0].standard.standard_code == "DEMO 1-2026"

            deleted = reconnected.delete_document("doc-1", index_name)
            assert deleted.deleted_count == 1
            assert (
                reconnected.search(
                    KeywordSearchRequest(
                        query="TASK3PERSISTENT",
                        index_name=index_name,
                        filters=SearchFilters(document_ids=["doc-1"]),
                    )
                )
                == []
            )
    finally:
        cleanup_client = create_elasticsearch_client(config)
        try:
            if bool(cleanup_client.indices.exists(index=index_name)):
                cleanup_client.indices.delete(index=index_name)
        finally:
            cleanup_client.close()
