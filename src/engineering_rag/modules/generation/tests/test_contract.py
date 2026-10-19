from pathlib import Path

from engineering_rag.contracts.answers import GenerationRequest
from engineering_rag.modules.generation.api import GenerationService


def test_protocol_is_declaration_only() -> None:
    assert GenerationService.__name__ == "GenerationService"
    assert getattr(GenerationService, "_is_protocol", False)


def test_fictional_generation_example_round_trip() -> None:
    root = next(
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "AGENTS.md").is_file() and (parent / "pyproject.toml").is_file()
    )
    value = GenerationRequest.model_validate_json(
        (root / "examples/generation_request.example.json").read_bytes()
    )
    assert GenerationRequest.model_validate_json(value.model_dump_json()) == value
    assert "虚构" in value.evidence[0].content
