"""Generation owns only local business logic and imports canonical contracts."""

import ast
from pathlib import Path

from engineering_rag.contracts.answers import AnswerResult, GenerationRequest
from engineering_rag.modules.generation import api


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
