from engineering_rag.modules.generation.api import GenerationService


def test_protocol_is_declaration_only() -> None:
    assert GenerationService.__name__ == "GenerationService"
    assert getattr(GenerationService, "_is_protocol", False)
