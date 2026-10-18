"""Query stages and the authorized planner remain vendor-free and dependency-injected."""

import ast
import inspect
import sys
from pathlib import Path

from engineering_rag.contracts import (
    ProcessingIntent,
    StandardMetadataCatalog,
    StructuredLLMClient,
)
from engineering_rag.contracts.protocols import HybridRetrievalService, QueryService
from engineering_rag.modules.query import api


def test_query_reexports_canonical_dependencies_and_protocols_only() -> None:
    assert api.ProcessingIntent is ProcessingIntent
    assert api.StructuredLLMClient is StructuredLLMClient
    assert api.StandardMetadataCatalog is StandardMetadataCatalog
    assert api.QueryService is QueryService
    assert all(
        getattr(protocol, "_is_protocol", False)
        for protocol in (QueryService, StructuredLLMClient, StandardMetadataCatalog)
    )
    assert list(inspect.signature(StructuredLLMClient.generate).parameters) == ["self", "request"]
    assert list(inspect.signature(StandardMetadataCatalog.lookup).parameters) == ["self", "request"]


def test_task6_4_orchestration_is_the_only_retrieval_caller() -> None:
    """Local stages remain isolated; only the service may plan and call public Hybrid."""
    root = Path(api.__file__).parent
    from engineering_rag.modules.query.internal.enhancement import QueryEnhancement
    from engineering_rag.modules.query.internal.rewrite import QueryRewrite
    from engineering_rag.modules.query.internal.understanding import QueryUnderstanding

    assert callable(QueryUnderstanding.understand)
    assert list(inspect.signature(QueryEnhancement.enhance).parameters) == [
        "self",
        "request",
        "understanding",
        "rewrite",
    ]
    assert list(inspect.signature(QueryEnhancement.__init__).parameters) == [
        "self",
        "llm",
        "config",
    ]
    assert list(inspect.signature(QueryRewrite.rewrite).parameters) == [
        "self",
        "request",
        "understanding",
    ]
    assert list(inspect.signature(QueryRewrite.__init__).parameters) == ["self", "llm", "config"]
    assert list(inspect.signature(api.DefaultQueryService.plan).parameters) == ["self", "request"]
    assert list(inspect.signature(api.DefaultQueryService.execute).parameters) == [
        "self",
        "request",
    ]
    assert (
        inspect.signature(api.DefaultQueryService.__init__).parameters["hybrid_service"].annotation
        is HybridRetrievalService
    )
    definitions = {
        ("rewrite.py", "QueryRewrite", "rewrite"),
        ("planning_models.py", "RewriteStage", "rewrite"),
        ("service.py", "DefaultQueryService", "plan"),
        ("service.py", "DefaultQueryService", "execute"),
    }
    forbidden = {"plan", "execute", "rewrite", "expand", "hyde", "search"}
    for path in (root / "internal").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        allowed_entries = [
            method
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            for method in node.body
            if isinstance(method, ast.FunctionDef)
            and (path.name, node.name, method.name) in definitions
        ]
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                assert node.name not in forbidden or node in allowed_entries, (path, node.name)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                regex_search = (
                    node.func.attr == "search"
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id == "re"
                )
                service_call = path.name == "service.py" and ast.unparse(node.func) in {
                    "self._rewrite.rewrite",
                    "self.plan",
                    "self._hybrid_service.search",
                }
                assert node.func.attr not in forbidden or regex_search or service_call, (
                    path,
                    node.func.attr,
                )
                if path.name.startswith("rewrite"):
                    assert node.func.attr not in {"understand", "lookup"}, (path, node.func.attr)
                if path.name.startswith("enhancement"):
                    assert node.func.attr not in {
                        "understand",
                        "rewrite",
                        "lookup",
                        "embed_query",
                        "embed_documents",
                        "index",
                    }, (path, node.func.attr)
            if path.name.startswith("enhancement") and isinstance(node, ast.ImportFrom):
                forbidden_types = {
                    "HybridSearchRequest",
                    "VectorSearchRequest",
                    "KeywordSearchRequest",
                    "RetrievalPlan",
                    "RetrievalResult",
                    "Document",
                    "Chunk",
                    "QueryUnderstanding",
                    "QueryRewrite",
                }
                assert not {name.name for name in node.names} & forbidden_types, path
            if isinstance(node, ast.Import):
                imports = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imports = [node.module]
            else:
                continue
            for name in imports:
                assert (
                    name.startswith("engineering_rag.contracts.")
                    or name.startswith("engineering_rag.modules.query.internal.")
                    or name.split(".")[0] in sys.stdlib_module_names | {"pydantic"}
                ), (path, name)


def test_query_v2_example_validates() -> None:
    from engineering_rag.contracts.queries import QueryResult

    path = Path(__file__).parents[2] / "examples" / "query_result.v2.example.json"
    result = QueryResult.model_validate_json(path.read_text(encoding="utf-8"))
    assert result.plan.processing_intent == ProcessingIntent.ACQUISITION
    assert QueryResult.model_validate_json(result.model_dump_json()) == result
