"""The metadata upgrade does not create parallel business DTOs or enums."""

import ast
from pathlib import Path
from typing import get_args

from engineering_rag.contracts.answers import GenerationRequest
from engineering_rag.contracts.chunks import ChunkContentType
from engineering_rag.contracts.retrieval import RetrievalResult
from engineering_rag.modules.hybrid_retrieval import api as hybrid
from engineering_rag.modules.keyword_retrieval import api as keyword
from engineering_rag.modules.vector_retrieval import api as vector


def test_only_one_canonical_retrieval_result_and_content_type_enum() -> None:
    root = Path(__file__).resolve().parents[2] / "src/engineering_rag"
    for class_name, expected_file in (
        ("RetrievalResult", "contracts/retrieval.py"),
        ("ChunkContentType", "contracts/chunks.py"),
    ):
        owners = [
            str(path.relative_to(root))
            for path in root.rglob("*.py")
            if any(
                isinstance(node, ast.ClassDef) and node.name == class_name
                for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            )
        ]
        assert owners == [expected_file]
    assert (
        hybrid.RetrievalResult
        is keyword.RetrievalResult
        is vector.RetrievalResult
        is RetrievalResult
    )
    assert get_args(GenerationRequest.model_fields["evidence"].annotation) == (RetrievalResult,)
    assert ChunkContentType in get_args(RetrievalResult.model_fields["content_type"].annotation)
