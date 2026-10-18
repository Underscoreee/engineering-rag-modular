"""Public dependency declarations remain vendor-free and do not implement Query flows."""

import inspect
from pathlib import Path

from engineering_rag.contracts import (
    ProcessingIntent,
    StandardMetadataCatalog,
    StructuredLLMClient,
)
from engineering_rag.contracts.protocols import QueryService
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


def test_task6_0_1_keeps_query_without_business_implementation() -> None:
    root = Path(api.__file__).parent
    assert list((root / "internal").glob("*.py")) == [root / "internal" / "__init__.py"]


def test_query_v2_example_validates() -> None:
    from engineering_rag.contracts.queries import QueryResult

    path = Path(__file__).parents[2] / "examples" / "query_result.v2.example.json"
    result = QueryResult.model_validate_json(path.read_text(encoding="utf-8"))
    assert result.plan.processing_intent == ProcessingIntent.ACQUISITION
    assert QueryResult.model_validate_json(result.model_dump_json()) == result
