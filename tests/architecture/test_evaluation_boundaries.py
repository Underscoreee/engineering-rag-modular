"""Evaluation stays protocol-driven; only its explicit demo composition imports APIs."""

import ast
import inspect
import sys
from importlib.util import resolve_name
from pathlib import Path
from typing import get_type_hints

from engineering_rag.contracts.evaluation import EvaluationReport, EvaluationRequest
from engineering_rag.contracts.protocols import EvaluationService
from engineering_rag.infrastructure.evaluation import api


def repository_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "pyproject.toml").is_file() and (candidate / "AGENTS.md").is_file():
            return candidate
    raise AssertionError("test file is not inside the expected repository")


def production_paths(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*.py") if "tests" not in path.relative_to(root).parts
    )


def imported_names(tree: ast.AST, path: Path) -> list[str]:
    names: list[str] = []
    module_parts = path.relative_to(repository_root() / "src").with_suffix("").parts
    package = ".".join(module_parts[:-1])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = (
                resolve_name("." * node.level + (node.module or ""), package)
                if node.level
                else node.module
            )
            if module:
                names.append(module)
                names.extend(f"{module}.{alias.name}" for alias in node.names)
    return names


def test_evaluation_reuses_canonical_request_report_and_protocol() -> None:
    assert api.EvaluationRequest is EvaluationRequest
    assert api.EvaluationReport is EvaluationReport
    assert api.EvaluationService is EvaluationService
    assert getattr(EvaluationService, "_is_protocol", False)
    assert list(inspect.signature(EvaluationService.evaluate).parameters) == ["self", "request"]
    implementation = api.QueryPipelineEvaluator.evaluate
    assert list(inspect.signature(implementation).parameters) == ["self", "request"]
    assert get_type_hints(implementation) == {
        "request": EvaluationRequest,
        "return": EvaluationReport,
    }
    assert list(inspect.signature(api.create_evaluation_service).parameters) == ["runtime"]
    assert inspect.signature(api.create_evaluation_service).parameters["runtime"].kind is (
        inspect.Parameter.KEYWORD_ONLY
    )


def test_evaluation_core_uses_only_contracts_own_code_stdlib_and_pydantic() -> None:
    root = Path(api.__file__).resolve().parent
    public_composition_imports = {
        "engineering_rag.modules.query.api",
        "engineering_rag.modules.hybrid_retrieval.api",
    }
    forbidden_clones = {
        "Document",
        "Chunk",
        "ChunkBatch",
        "SearchFilters",
        "RetrievalResult",
        "EvaluationRequest",
        "EvaluationReport",
        "EvaluationService",
    }
    for path in production_paths(root):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert node.name not in forbidden_clones, (path, node.name)
        for imported in imported_names(tree, path):
            assert "engineering_rag.modules.generation" not in imported, (path, imported)
            if imported.startswith("engineering_rag.modules."):
                assert path.name == "offline.py", (path, imported)
                assert any(
                    imported == public or imported.startswith(public + ".")
                    for public in public_composition_imports
                ), (path, imported)
                assert ".internal" not in imported, (path, imported)
            else:
                assert (
                    imported == "engineering_rag.contracts"
                    or imported.startswith("engineering_rag.contracts.")
                    or imported.startswith("engineering_rag.infrastructure.evaluation.")
                    or imported.split(".")[0] in sys.stdlib_module_names | {"pydantic"}
                ), (path, imported)


def test_query_and_hybrid_do_not_depend_on_evaluation_internals() -> None:
    modules_root = repository_root() / "src" / "engineering_rag" / "modules"
    for module in ("query", "hybrid_retrieval"):
        for path in production_paths(modules_root / module):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            assert not any(
                imported.startswith("engineering_rag.infrastructure.evaluation")
                for imported in imported_names(tree, path)
            ), path


def test_evaluation_has_no_database_or_model_sdk_imports() -> None:
    banned = {
        "elasticsearch",
        "pymilvus",
        "sentence_transformers",
        "transformers",
        "torch",
        "openai",
        "anthropic",
        "litellm",
        "httpx",
        "requests",
    }
    root = Path(api.__file__).resolve().parent
    for path in production_paths(root):
        names = imported_names(ast.parse(path.read_text(encoding="utf-8")), path)
        assert not {name.split(".")[0] for name in names} & banned, path
