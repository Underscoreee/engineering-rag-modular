from engineering_rag.modules.vector_retrieval.api import VectorRetrievalService


def test_protocol_is_declaration_only() -> None:
    assert VectorRetrievalService.__name__ == "VectorRetrievalService"
    assert getattr(VectorRetrievalService, "_is_protocol", False)
