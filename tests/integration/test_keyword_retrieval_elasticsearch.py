"""Optional persistence test against a real, explicitly configured Elasticsearch 8.x."""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from urllib.parse import urlparse

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
    assert config.url is not None
    _require_local_test_service(config.url)
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

        inspection_client = create_elasticsearch_client(config)
        try:
            mapping_response = inspection_client.indices.get_mapping(index=index_name)
            mapping_body = getattr(mapping_response, "body", mapping_response)
            assert isinstance(mapping_body, Mapping)
            index_mapping = mapping_body[index_name]["mappings"]
            assert index_mapping["_meta"]["engineering_rag_mapping_version"] == ("keyword-index-v1")
            assert index_mapping["properties"]["search_text"]["analyzer"] == "standard"
        finally:
            inspection_client.close()

        with create_keyword_retrieval_service(config) as reconnected:
            top_hit = reconnected.search(
                KeywordSearchRequest(
                    query="TASK3PERSISTENT",
                    top_k=1,
                    index_name=index_name,
                )
            )
            assert len(top_hit) == 1
            assert top_hit[0].score > 0

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
            assert hits[0].document_id == "doc-1"
            assert hits[0].content == first.content
            assert (hits[0].page_start, hits[0].page_end) == (2, 2)
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


def _require_local_test_service(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(
            "real Elasticsearch integration tests only allow an http:// localhost service"
        )
    if parsed.username is not None or parsed.password is not None:
        raise RuntimeError("real Elasticsearch integration test URL must not contain credentials")
