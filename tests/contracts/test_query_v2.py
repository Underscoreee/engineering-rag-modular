"""Query V2 shape, explicit migration, and strict old-reader compatibility."""

import copy

import pytest
from pydantic import Field, ValidationError

from engineering_rag.contracts.common import SCHEMA_VERSION, ContractModel, NonEmptyStr
from engineering_rag.contracts.queries import (
    ProcessingIntent,
    QueryIntent,
    QueryOptions,
    QueryRequest,
    QueryResult,
    RetrievalPlan,
)
from engineering_rag.contracts.query_migrations import (
    migrate_query_result_v1,
    migrate_retrieval_plan_v1,
)
from engineering_rag.contracts.retrieval import (
    HybridSearchRequest,
    RetrievalMode,
    RetrievalResult,
)


def legacy_plan() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "original_question": "虚构设备检修条件是什么？",
        "rewritten_queries": ["虚构设备检修条件"],
        "hypothetical_document": None,
        "intent": "requirement",
        "retrieval_mode": "hybrid",
        "hybrid_request": {
            "keyword": {"query": "检修 条件", "index_name": "fiction_keyword"},
            "vector": {"query": "设备的检修条件", "index_name": "fiction_vector"},
            "fusion_strategy": "rrf",
        },
    }


class StrictOldPlanReader(ContractModel):
    """Independent copy of the original strict reader, including its string version field."""

    schema_version: NonEmptyStr = "1.0"
    original_question: NonEmptyStr
    rewritten_queries: list[NonEmptyStr] = Field(default_factory=list)
    hypothetical_document: str | None = None
    intent: QueryIntent = QueryIntent.UNKNOWN
    retrieval_mode: RetrievalMode
    hybrid_request: HybridSearchRequest | None = None


@pytest.mark.parametrize("value", ["acquisition", "exploratory"])
def test_processing_intent_values_and_plan_round_trip(value: str) -> None:
    data = {**legacy_plan(), "schema_version": "2.0", "processing_intent": value}
    plan = RetrievalPlan.model_validate(data)
    assert set(ProcessingIntent) == {ProcessingIntent.ACQUISITION, ProcessingIntent.EXPLORATORY}
    assert plan.intent == QueryIntent.REQUIREMENT
    assert plan.processing_intent.value == value
    assert RetrievalPlan.model_validate_json(plan.model_dump_json()) == plan
    result = QueryResult(plan=plan)
    assert result.schema_version == "2.0"
    assert QueryResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("value", [None, "unknown", "fact_lookup", "", 1, True])
def test_null_unknown_or_invalid_processing_intent_is_rejected(value: object) -> None:
    with pytest.raises(ValidationError):
        RetrievalPlan.model_validate(
            {**legacy_plan(), "schema_version": "2.0", "processing_intent": value}
        )


def test_missing_processing_intent_and_old_version_require_explicit_migration() -> None:
    with pytest.raises(ValidationError, match="processing_intent"):
        RetrievalPlan.model_validate({**legacy_plan(), "schema_version": "2.0"})
    with pytest.raises(ValidationError, match="schema_version"):
        RetrievalPlan.model_validate(legacy_plan())
    with pytest.raises(TypeError):
        migrate_retrieval_plan_v1(legacy_plan())  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        migrate_retrieval_plan_v1(legacy_plan(), processing_intent=None)  # type: ignore[arg-type]


def test_explicit_migration_preserves_semantic_intent_requests_and_original_input() -> None:
    payload = legacy_plan()
    before = copy.deepcopy(payload)
    migrated = migrate_retrieval_plan_v1(payload, processing_intent=ProcessingIntent.EXPLORATORY)
    assert payload == before
    assert migrated.intent == QueryIntent.REQUIREMENT
    assert migrated.processing_intent == ProcessingIntent.EXPLORATORY
    assert migrated.original_question == payload["original_question"]
    assert migrated.hybrid_request is not None
    assert migrated.hybrid_request.keyword.query == "检修 条件"
    assert migrated.hybrid_request.vector.query == "设备的检修条件"
    assert migrated.rewritten_queries == payload["rewritten_queries"]
    with pytest.raises(ValidationError, match="extra_forbidden"):
        StrictOldPlanReader.model_validate_json(migrated.model_dump_json())


def test_result_migration_upgrades_plan_and_legacy_evidence_without_inferring_metadata() -> None:
    evidence = {
        "schema_version": "1.0",
        "chunk_id": "fixture-chunk",
        "logical_chunk_id": "fixture-logical",
        "document_id": "fixture-doc",
        "content": "虚构的检修条件。",
        "standard": {"standard_name": "虚构标准", "standard_code": "TEST 000-2026"},
        "page_start": 2,
        "page_end": 3,
        "score": 0.01,
        "rank": 1,
        "retrieval_source": "hybrid",
        "score_type": "rrf",
        "index_name": "fixture-index",
    }
    payload = {"schema_version": "1.0", "plan": legacy_plan(), "evidence": [evidence]}
    migrated = migrate_query_result_v1(payload, processing_intent=ProcessingIntent.ACQUISITION)
    assert migrated.schema_version == migrated.plan.schema_version == "2.0"
    assert migrated.evidence[0].schema_version == "2.0"
    assert migrated.evidence[0].is_explanation is None
    assert migrated.evidence[0].is_mandatory is None
    assert migrated.evidence[0].content_type is None
    assert evidence["schema_version"] == "1.0"  # Original archival input is unchanged.
    assert migrated.evidence == [RetrievalResult.model_validate(evidence)]
    assert QueryResult.model_validate_json(migrated.model_dump_json()) == migrated


@pytest.mark.parametrize("version", ["1.0", "3.0", "2.4"])
def test_result_version_must_match_v2_plan(version: str) -> None:
    plan = migrate_retrieval_plan_v1(legacy_plan(), processing_intent=ProcessingIntent.ACQUISITION)
    with pytest.raises(ValidationError, match="schema_version"):
        QueryResult(schema_version=version, plan=plan)  # type: ignore[arg-type]


@pytest.mark.parametrize("changes", [{"schema_version": "9.0"}, {"unexpected": True}])
def test_migration_rejects_unknown_versions_and_extra_fields(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        migrate_retrieval_plan_v1(
            {**legacy_plan(), **changes}, processing_intent=ProcessingIntent.ACQUISITION
        )


def test_semantic_enum_request_options_and_global_version_are_unchanged() -> None:
    assert {item.value for item in QueryIntent} == {
        "fact_lookup",
        "requirement",
        "comparison",
        "explanation",
        "unknown",
    }
    assert SCHEMA_VERSION == "1.0"
    assert set(QueryRequest.model_fields) == {"question", "history", "filters", "options", "trace"}
    for mode in ("keyword", "vector", "hybrid"):
        assert QueryOptions(mode=mode).mode == mode
    with pytest.raises(ValidationError, match="extra_forbidden"):
        QueryRequest(question="q", processing_intent="acquisition")


def test_no_processing_intent_is_inferred_from_any_legacy_semantic_intent() -> None:
    for intent in QueryIntent:
        payload = {**legacy_plan(), "intent": intent.value}
        migrated = migrate_retrieval_plan_v1(
            payload, processing_intent=ProcessingIntent.EXPLORATORY
        )
        assert migrated.intent == intent
        assert migrated.processing_intent == ProcessingIntent.EXPLORATORY


def test_migration_accepts_legacy_omitted_default_versions_but_not_mixed_shapes() -> None:
    payload = legacy_plan()
    payload.pop("schema_version")
    assert (
        migrate_retrieval_plan_v1(
            payload, processing_intent=ProcessingIntent.ACQUISITION
        ).schema_version
        == "2.0"
    )
    with pytest.raises(ValidationError):
        migrate_retrieval_plan_v1(
            {**payload, "processing_intent": "acquisition"},
            processing_intent=ProcessingIntent.ACQUISITION,
        )
