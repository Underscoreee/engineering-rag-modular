"""Versioned retrieval evidence, legacy reads and nested public contract propagation."""

import copy
import json

import pytest
from pydantic import ValidationError, create_model

from engineering_rag.contracts import retrieval
from engineering_rag.contracts.answers import GenerationRequest
from engineering_rag.contracts.chunks import ChunkContentType
from engineering_rag.contracts.common import ContractModel
from engineering_rag.contracts.queries import QueryResult, RetrievalPlan
from engineering_rag.contracts.retrieval import RetrievalResult

METADATA = ("is_explanation", "is_mandatory", "content_type")


def legacy_payload() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "chunk_id": "fictional-chunk",
        "logical_chunk_id": "fictional-logical",
        "document_id": "fictional-document",
        "content": "虚构示例内容，不是真实规范要求。",
        "standard": {"standard_name": "虚构标准", "standard_code": "DEMO 000-2026"},
        "clause_id": None,
        "clause_number": None,
        "page_start": 2,
        "page_end": 3,
        "score": 0.2,
        "rank": 1,
        "retrieval_source": "hybrid",
        "score_type": "rrf",
        "index_name": "fictional-index",
    }


def test_legacy_read_defaults_are_unknown_and_serialization_is_current() -> None:
    payload = legacy_payload()
    before = copy.deepcopy(payload)
    result = RetrievalResult.model_validate_json(json.dumps(payload))
    assert result.schema_version == "2.0"
    assert all(getattr(result, field) is None for field in METADATA)
    assert payload == before
    assert result.model_dump(mode="json")["schema_version"] == "2.0"
    assert RetrievalResult.model_validate_json(result.model_dump_json()) == result


@pytest.mark.parametrize("explanation", [None, False, True])
@pytest.mark.parametrize("mandatory", [None, False, True])
@pytest.mark.parametrize("content_type", [None, *ChunkContentType])
def test_all_metadata_states_round_trip(explanation, mandatory, content_type) -> None:
    result = RetrievalResult.model_validate(
        {
            **legacy_payload(),
            "schema_version": "2.0",
            "is_explanation": explanation,
            "is_mandatory": mandatory,
            "content_type": content_type,
        }
    )
    restored = RetrievalResult.model_validate_json(result.model_dump_json())
    assert (restored.is_explanation, restored.is_mandatory, restored.content_type) == (
        explanation,
        mandatory,
        content_type,
    )


@pytest.mark.parametrize("field", ["is_explanation", "is_mandatory"])
@pytest.mark.parametrize("value", ["true", "false", 0, 1, -1, 0.0, [], {}])
def test_boolean_metadata_does_not_coerce(field, value) -> None:
    with pytest.raises(ValidationError):
        RetrievalResult.model_validate({**legacy_payload(), "schema_version": "2.0", field: value})


@pytest.mark.parametrize("value", ["title", "body", "unknown", "", True, 7, {}, [], b"clause"])
def test_invalid_content_type_is_not_relabelled(value) -> None:
    with pytest.raises(ValidationError):
        RetrievalResult.model_validate(
            {**legacy_payload(), "schema_version": "2.0", "content_type": value}
        )


@pytest.mark.parametrize("version", ["3.0", "1.1", "", None, 2])
def test_unknown_versions_are_not_silently_accepted(version) -> None:
    with pytest.raises(ValidationError):
        RetrievalResult.model_validate({**legacy_payload(), "schema_version": version})


@pytest.mark.parametrize("field", METADATA)
def test_v1_tag_with_v2_fields_is_a_mixed_format_error(field) -> None:
    with pytest.raises(ValidationError):
        RetrievalResult.model_validate({**legacy_payload(), field: None})


def test_explicit_migration_for_persisted_v1_never_overwrites_input() -> None:
    payload = legacy_payload()
    before = copy.deepcopy(payload)
    result = retrieval.migrate_retrieval_result_v1(payload)
    assert result.schema_version == "2.0" and payload == before
    with pytest.raises(ValueError):
        retrieval.migrate_retrieval_result_v1(result.model_dump(mode="json"))


def test_old_strict_consumer_rejects_v2_extra_fields() -> None:
    # A test-only historical reader, not a second production RetrievalResult DTO.
    definitions = {
        name: (field.annotation, ... if field.is_required() else field.default)
        for name, field in RetrievalResult.model_fields.items()
        if name not in METADATA
    }
    definitions["schema_version"] = (str, "1.0")
    old_reader = create_model("HistoricalStrictConsumer", __base__=ContractModel, **definitions)
    old_reader.model_validate(legacy_payload())
    with pytest.raises(ValidationError, match="extra_forbidden"):
        old_reader.model_validate_json(
            RetrievalResult.model_validate(legacy_payload()).model_dump_json()
        )


def test_query_and_generation_nested_round_trips_preserve_metadata() -> None:
    evidence = RetrievalResult.model_validate(
        {
            **legacy_payload(),
            "schema_version": "2.0",
            "is_explanation": True,
            "is_mandatory": False,
            "content_type": "formula",
        }
    )
    plan = RetrievalPlan(
        original_question="虚构问题",
        processing_intent="acquisition",
        retrieval_mode="hybrid",
        hybrid_request={
            "keyword": {"query": "虚构问题", "index_name": "fiction-keyword"},
            "vector": {"query": "虚构问题", "index_name": "fiction-vector"},
            "fusion_strategy": "rrf",
        },
    )
    query = QueryResult.model_validate_json(
        QueryResult(plan=plan, evidence=[evidence]).model_dump_json()
    )
    generation = GenerationRequest.model_validate_json(
        GenerationRequest(
            question=query.plan.original_question, evidence=query.evidence
        ).model_dump_json()
    )
    assert generation.evidence == [evidence]
    assert query.schema_version == "2.0"  # Outer Query format and fields are unchanged.


def test_legacy_evidence_nested_in_generation_also_reads_as_unknown() -> None:
    request = GenerationRequest.model_validate(
        {"question": "虚构问题", "evidence": [legacy_payload()]}
    )
    assert request.evidence[0].schema_version == "2.0"
    assert request.evidence[0].is_explanation is None
