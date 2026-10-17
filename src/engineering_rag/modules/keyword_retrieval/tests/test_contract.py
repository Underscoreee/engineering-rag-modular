from engineering_rag.modules.keyword_retrieval.api import (
    ElasticsearchKeywordConfig,
    ElasticsearchKeywordRetrievalService,
    KeywordRetrievalService,
)

from .helpers import FakeElasticsearchClient


def test_protocol_is_declaration_only() -> None:
    assert KeywordRetrievalService.__name__ == "KeywordRetrievalService"
    assert getattr(KeywordRetrievalService, "_is_protocol", False)


def test_real_service_implements_runtime_protocol() -> None:
    service = ElasticsearchKeywordRetrievalService(
        FakeElasticsearchClient(), ElasticsearchKeywordConfig()
    )

    assert isinstance(service, KeywordRetrievalService)
