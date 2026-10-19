"""Generation owns only local business logic and imports canonical contracts."""

import ast
from pathlib import Path

from engineering_rag.contracts.answers import AnswerResult, Citation, GenerationRequest
from engineering_rag.modules.generation import api
from engineering_rag.modules.generation.internal.answer_validator import AnswerValidator
from engineering_rag.modules.generation.internal.citation_mapper import CitationMapper


def test_generation_has_no_provider_database_or_other_business_imports():
    root = Path(__file__).resolve().parents[2] / "src/engineering_rag/modules/generation"
    for path in root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                assert not (node.module or "").startswith("engineering_rag.infrastructure")
                assert not (node.module or "").startswith("engineering_rag.modules.")
            if isinstance(node, ast.Import):
                for name in node.names:
                    assert name.name.split(".")[0] not in {
                        "openai",
                        "elasticsearch",
                        "pymilvus",
                        "requests",
                        "httpx",
                        "urllib",
                    }
    assert api.AnswerResult is AnswerResult
    assert api.GenerationRequest is GenerationRequest


def test_citation_components_are_private_and_public_dtos_are_not_duplicated():
    assert CitationMapper.__module__.startswith("engineering_rag.modules.generation.internal.")
    assert AnswerValidator.__module__.startswith("engineering_rag.modules.generation.internal.")
    root = Path(__file__).resolve().parents[2] / "src/engineering_rag/modules/generation"
    for path in root.rglob("*.py"):
        if "tests" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ClassDef):
                assert node.name not in {
                    "Citation",
                    "AnswerResult",
                    "GenerationRequest",
                    "GroundingStatus",
                }
    assert set(Citation.model_fields) == {
        "citation_id",
        "evidence_chunk_id",
        "document_id",
        "clause_id",
        "page_start",
        "page_end",
        "quoted_text",
    }
    assert set(AnswerResult.model_fields) == {
        "schema_version",
        "answer",
        "citations",
        "grounding_status",
        "model",
        "warnings",
    }
