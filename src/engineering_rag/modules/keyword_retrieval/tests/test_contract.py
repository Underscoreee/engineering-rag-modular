from engineering_rag.modules.keyword_retrieval.api import KeywordRetrievalService


def test_protocol_is_declaration_only() -> None:
    assert KeywordRetrievalService.__name__ == "KeywordRetrievalService"
    assert getattr(KeywordRetrievalService, "_is_protocol", False)
