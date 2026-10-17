import pytest

from engineering_rag.contracts.retrieval import IndexRequest
from engineering_rag.modules.keyword_retrieval.api import (
    ElasticsearchKeywordConfig,
    ElasticsearchKeywordRetrievalService,
    create_keyword_retrieval_service,
)
from engineering_rag.modules.keyword_retrieval.internal.errors import KeywordTimeoutError
from engineering_rag.modules.keyword_retrieval.internal.mapping import build_index_definition

from .helpers import FakeElasticsearchClient, make_batch, make_chunk


def test_factory_accepts_injected_client_without_network_or_ownership() -> None:
    client = FakeElasticsearchClient()
    service = create_keyword_retrieval_service(ElasticsearchKeywordConfig(), client=client)

    service.close()

    assert client.closed is False


def test_delete_document_removes_only_target_document() -> None:
    client = FakeElasticsearchClient()
    service = ElasticsearchKeywordRetrievalService(client, ElasticsearchKeywordConfig())
    service.index(
        make_batch(make_chunk("a")),
        IndexRequest(index_name="chunks", operation_id="op-a", replace_document=False),
    )
    service.index(
        make_batch(make_chunk("b", document_id="doc-2")),
        IndexRequest(index_name="chunks", operation_id="op-b", replace_document=False),
    )

    result = service.delete_document("doc-1", "chunks")

    assert result.index_existed is True
    assert result.deleted_count == 1
    assert list(client.documents["chunks"]) == ["b"]


def test_delete_from_missing_index_reports_contract_state() -> None:
    service = ElasticsearchKeywordRetrievalService(
        FakeElasticsearchClient(), ElasticsearchKeywordConfig()
    )

    result = service.delete_document("doc-1", "missing")

    assert result.index_existed is False
    assert result.deleted_count == 0


def test_existing_analyzer_mismatch_is_detected_through_service() -> None:
    client = FakeElasticsearchClient()
    definition = build_index_definition(ElasticsearchKeywordConfig(analyzer="standard"))
    client.indices.mappings["chunks"] = definition["mappings"]
    service = ElasticsearchKeywordRetrievalService(
        client, ElasticsearchKeywordConfig(analyzer="ik_max_word")
    )

    from engineering_rag.modules.keyword_retrieval.api import KeywordIndexCompatibilityError

    try:
        service.index(make_batch(), IndexRequest(index_name="chunks", operation_id="op-mismatch"))
    except KeywordIndexCompatibilityError:
        pass
    else:
        raise AssertionError("analyzer mismatch must be rejected")


def test_delete_by_query_timeout_is_not_reported_as_success() -> None:
    client = FakeElasticsearchClient()
    definition = build_index_definition(ElasticsearchKeywordConfig())
    client.indices.mappings["chunks"] = definition["mappings"]
    client.delete_response = {"timed_out": True, "deleted": 0}
    service = ElasticsearchKeywordRetrievalService(client, ElasticsearchKeywordConfig())

    with pytest.raises(KeywordTimeoutError):
        service.delete_document("doc-1", "chunks")
