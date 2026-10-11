from engineering_rag.modules.hybrid_retrieval.api import HybridRetrievalService


def test_protocol_is_declaration_only() -> None:
    assert HybridRetrievalService.__name__ == "HybridRetrievalService"
    assert getattr(HybridRetrievalService, "_is_protocol", False)
