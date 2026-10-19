"""Independent strict answer validation, without model calls or semantic claims."""

from dataclasses import replace

import pytest

from engineering_rag.contracts.answers import AnswerResult
from engineering_rag.modules.generation.internal.answer_validator import AnswerValidator
from engineering_rag.modules.generation.internal.citation_mapper import CitationMapper
from engineering_rag.modules.generation.internal.models import INSUFFICIENT_ANSWER, GenerationError

from .helpers import evidence
from .test_citation_mapper import context, output


def fixture():
    value = context()
    mapping = CitationMapper().map(output(), value)
    answer = AnswerResult(
        answer="检修间隔为7天。", citations=list(mapping.citations), grounding_status="grounded"
    )
    return value, mapping, answer


def validate(answer, value, mapping, **options):
    return AnswerValidator(max_answer_chars=12000).validate(
        answer, context=value, mapping=mapping, **options
    )


def test_valid_paraphrase_is_conservative_not_proven_by_citation_count():
    value, mapping, answer = fixture()
    before = answer.model_dump_json()
    result = validate(answer, value, mapping)
    assert result.grounding_status == "partially_grounded"
    assert any("individual claims" in w.message for w in result.warnings)
    assert answer.model_dump_json() == before
    assert AnswerResult.model_validate_json(result.model_dump_json()) == result
    assert validate(result, value, mapping) == result  # Deterministic, no warning inflation.


def test_whole_verbatim_answer_may_retain_grounded_but_not_semantic_proof():
    value, mapping, answer = fixture()
    answer.answer = value.registry["E1"].content
    result = validate(answer, value, mapping)
    assert result.grounding_status == "grounded"
    assert any("engineering/legal correctness" in warning.message for warning in result.warnings)
    limited = validate(answer, value, mapping, limitations=["来源未说明强制性"])
    assert limited.grounding_status == "partially_grounded"
    assert any("来源未说明强制性" in w.message for w in limited.warnings)


def test_literal_substring_does_not_prove_negation_or_conditions_preserved():
    value = context(evidence(content="在水下构件中不应施加荷载。"))
    mapping = CitationMapper().map(output(), value)
    answer = AnswerResult(
        answer="应施加荷载", citations=list(mapping.citations), grounding_status="grounded"
    )
    assert validate(answer, value, mapping).grounding_status == "partially_grounded"


@pytest.mark.parametrize("text", ["", "   ", "\n\t"])
def test_empty_answer_never_passes(text):
    value, mapping, answer = fixture()
    payload = answer.model_dump(mode="json")
    payload["answer"] = text
    with pytest.raises(GenerationError, match="invalid_answer"):
        validate(payload, value, mapping)


@pytest.mark.parametrize(
    ("field", "new_value", "code"),
    [
        ("page_start", "2", "invalid_answer"),
        ("page_start", True, "invalid_answer"),
        ("page_end", 0, "invalid_answer"),
        ("page_end", 9, "citation_mapping"),
        ("page_end", 2, "citation_mapping"),
        ("document_id", "forged", "citation_mapping"),
        ("clause_id", "forged", "citation_mapping"),
        ("citation_id", "C999", "citation_mapping"),
        ("evidence_chunk_id", "unprovided", "citation_mapping"),
    ],
)
def test_schema_and_authoritative_source_match_are_checked(field, new_value, code):
    value, mapping, answer = fixture()
    payload = answer.model_dump(mode="json")
    payload["citations"][0][field] = new_value
    with pytest.raises(GenerationError, match=code):
        validate(payload, value, mapping)


@pytest.mark.parametrize("field", ["page_start", "page_end", "document_id", "evidence_chunk_id"])
def test_missing_required_citation_source_is_not_fabricated(field):
    value, mapping, answer = fixture()
    payload = answer.model_dump(mode="json")
    del payload["citations"][0][field]
    with pytest.raises(GenerationError, match="invalid_answer"):
        validate(payload, value, mapping)


@pytest.mark.parametrize(
    "field",
    [
        "standard_name",
        "standard_code",
        "clause_number",
        "is_explanation",
        "is_mandatory",
        "claim_evidence_ids",
    ],
)
def test_unmapped_model_source_fields_and_new_public_claim_fields_are_rejected(field):
    value, mapping, answer = fixture()
    payload = answer.model_dump(mode="json")
    payload["citations"][0][field] = "forged"
    with pytest.raises(GenerationError, match="invalid_answer"):
        validate(payload, value, mapping)


def test_mapping_is_bound_to_exact_context_not_global_e1_name():
    original, mapping, answer = fixture()
    other = context(evidence(document_id="other-document"))
    assert set(original.registry) == set(other.registry) == {"E1"}
    with pytest.raises(GenerationError, match="citation_scope"):
        validate(answer, other, mapping)
    # Even identical evidence/question in a different request is not this binding.
    with pytest.raises(GenerationError, match="citation_scope"):
        validate(answer, context(), mapping)


def test_registry_cannot_change_after_mapping_including_source_flags():
    value, mapping, answer = fixture()
    value.registry["E1"].is_mandatory = False
    with pytest.raises(GenerationError, match="source_metadata_conflict"):
        validate(answer, value, mapping)


def test_prompt_false_cannot_be_replaced_by_numeric_zero():
    value, mapping, answer = fixture()
    value.payload["evidence"][0]["is_explanation"] = 0
    with pytest.raises(GenerationError, match="source_metadata_conflict"):
        validate(answer, value, mapping)


@pytest.mark.parametrize("conflict", [False, True])
def test_duplicate_citations_are_not_silently_removed(conflict):
    value, mapping, answer = fixture()
    payload = answer.model_dump(mode="json")
    duplicate = dict(payload["citations"][0])
    if conflict:
        duplicate["document_id"] = "another-document"
    payload["citations"].append(duplicate)
    with pytest.raises(GenerationError):
        validate(payload, value, mapping)


@pytest.mark.parametrize("text", ["8天", " ", "0.1"])
def test_forged_mapping_quotes_are_rechecked_not_just_id_validated(text):
    value, mapping, answer = fixture()
    forged_citation = mapping.citations[0].model_copy(update={"quoted_text": text})
    forged_mapping = replace(mapping, citations=(forged_citation,))
    answer.citations = [forged_citation]
    with pytest.raises(GenerationError, match="quote_mismatch"):
        validate(answer, value, forged_mapping)


def test_valid_quote_retained_unchanged():
    value = context(evidence(content="荷载\n 不应超过 7 天"))
    mapping = CitationMapper().map(
        output(quotes=[{"evidence_id": "E1", "quoted_text": "荷载 不应超过 7 天"}]), value
    )
    answer = AnswerResult(
        answer="荷载 不应超过 7 天", citations=list(mapping.citations), grounding_status="grounded"
    )
    result = validate(answer, value, mapping)
    assert result.citations[0].quoted_text == "荷载 不应超过 7 天"
    assert result.grounding_status == "grounded"


@pytest.mark.parametrize("status", ["grounded", "partially_grounded"])
def test_no_authorized_evidence_cannot_support_normative_answer(status):
    from engineering_rag.modules.generation.internal.context import ContextBuilder

    from .helpers import request, settings

    value = ContextBuilder(settings()).build(request(evidence=[]))
    mapping = CitationMapper().map(output(ids=[]), value)
    answer = AnswerResult(answer="检查间隔确定为8天。", citations=[], grounding_status=status)
    with pytest.raises(GenerationError, match="grounding_conflict"):
        validate(answer, value, mapping)


def test_insufficient_requires_existing_safe_answer_policy():
    value = context()
    mapping = CitationMapper().map(output(ids=[]), value)
    for text in ("确定必须7天，无需证据", "无法确认但是必须8天"):
        answer = AnswerResult(answer=text, grounding_status="insufficient_evidence")
        with pytest.raises(GenerationError, match="grounding_conflict"):
            validate(answer, value, mapping)
    answer = AnswerResult(answer=INSUFFICIENT_ANSWER, grounding_status="insufficient_evidence")
    assert validate(answer, value, mapping).grounding_status == "insufficient_evidence"


def test_insufficient_cannot_include_used_citations():
    value, mapping, answer = fixture()
    answer.grounding_status = "insufficient_evidence"
    answer.answer = INSUFFICIENT_ANSWER
    with pytest.raises(GenerationError, match="grounding_conflict"):
        validate(answer, value, mapping)
