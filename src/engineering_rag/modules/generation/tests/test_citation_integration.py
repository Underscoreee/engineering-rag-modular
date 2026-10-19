"""Actual Context -> fake LLM -> Mapper -> Validator -> AnswerResult pipeline."""

import pytest

from engineering_rag.contracts.answers import AnswerResult
from engineering_rag.modules.generation.api import GenerationError, create_generation_service
from engineering_rag.modules.generation.internal.answer_validator import AnswerValidator
from engineering_rag.modules.generation.internal.citation_mapper import CitationMapper
from engineering_rag.modules.generation.internal.context import ContextBuilder

from .helpers import FakeLLM, evidence, request, settings


def test_real_components_validate_quotes_multi_chunk_metadata_and_json():
    llm = FakeLLM()
    llm.data.update(
        answer=evidence().content,
        evidence_ids=["E2", "E1", "E2"],
        quotes=[
            {"evidence_id": "E1", "quoted_text": "检查间隔不应超过7天"},
            {"evidence_id": "E2", "quoted_text": "不适用于水下构件"},
        ],
    )
    value = request(
        evidence=[
            evidence(),
            evidence(
                chunk_id="explanation",
                document_id="second-doc",
                rank=2,
                is_explanation=True,
                is_mandatory=None,
                clause_id=None,
            ),
        ]
    )
    before = value.model_dump_json()
    answer = create_generation_service(llm=llm, settings=settings()).generate(value)
    assert answer.grounding_status == "grounded"  # Whole answer is verbatim, not just an ID.
    assert [c.evidence_chunk_id for c in answer.citations] == ["explanation", "fictional-chunk-1"]
    assert answer.citations[0].document_id == "second-doc" and answer.citations[0].clause_id is None
    assert answer.citations[1].quoted_text == "检查间隔不应超过7天"
    assert value.model_dump_json() == before
    assert AnswerResult.model_validate_json(answer.model_dump_json()) == answer
    prompt = llm.requests[0].input["evidence"]
    assert prompt[1]["is_explanation"] is True and prompt[1]["is_mandatory"] is None


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"evidence_ids": ["missing"]}, "unknown_evidence_id"),
        ({"quotes": [{"evidence_id": "E1", "quoted_text": "应超过8天"}]}, "quote_mismatch"),
        ({"quotes": [{"evidence_id": "outside", "quoted_text": "7天"}]}, "unknown_evidence_id"),
    ],
)
def test_invalid_id_or_quote_fails_without_retrieval_or_fake_fallback(changes, code):
    llm = FakeLLM()
    llm.data.update(changes)
    service = create_generation_service(llm=llm, settings=settings())
    with pytest.raises(GenerationError) as caught:
        service.generate(request())
    assert caught.value.code == code
    assert len(llm.requests) == 1  # Deterministic bad references are not retried.
    assert service.calls[-1]["status"] == code
    assert service.calls[-1]["grounding_status"] is None


@pytest.mark.parametrize("field", ["standard_code", "standard_name", "clause_number", "page_start"])
def test_model_freely_generated_source_descriptions_are_schema_errors(field):
    llm = FakeLLM()
    llm.data["quotes"] = [{"evidence_id": "E1", "quoted_text": "7天", field: "invented"}]
    with pytest.raises(GenerationError, match="invalid_output"):
        create_generation_service(llm=llm, settings=settings(max_attempts=1)).generate(request())


def test_budget_omitted_chunk_cannot_be_cited_even_if_retrieved():
    value = request(evidence=[evidence(content="长" * 10000), evidence(chunk_id="small", rank=2)])
    budget = ContextBuilder(settings()).build(request()).estimated_chars + 50
    llm = FakeLLM()  # Attempts E1, which was retrieved but not sent to the LLM.
    with pytest.raises(GenerationError, match="unknown_evidence_id"):
        create_generation_service(llm=llm, settings=settings(max_context_chars=budget)).generate(
            value
        )
    assert [row["evidence_id"] for row in llm.requests[0].input["evidence"]] == ["E2"]


def test_service_cannot_bypass_answer_validator(monkeypatch):
    seen = []

    def reject(self, answer, **kwargs):
        seen.append(kwargs)
        raise GenerationError("invalid_answer")

    monkeypatch.setattr(AnswerValidator, "validate", reject)
    service = create_generation_service(llm=FakeLLM(), settings=settings())
    with pytest.raises(GenerationError, match="invalid_answer"):
        service.generate(request())
    assert len(seen) == 1
    assert seen[0]["mapping"].context is seen[0]["context"]


def test_empty_evidence_safe_path_is_validated_without_llm(monkeypatch):
    validator = AnswerValidator.validate
    seen = []

    def observe(self, answer, **kwargs):
        seen.append(answer)
        return validator(self, answer, **kwargs)

    monkeypatch.setattr(AnswerValidator, "validate", observe)
    llm = FakeLLM()
    answer = create_generation_service(llm=llm, settings=settings()).generate(request(evidence=[]))
    assert len(seen) == 1 and not llm.requests
    assert answer.grounding_status == "insufficient_evidence"


def test_no_evidence_fallback_preserves_policy_even_with_tiny_model_output_budget():
    llm = FakeLLM()
    answer = create_generation_service(llm=llm, settings=settings(max_answer_chars=1)).generate(
        request(evidence=[])
    )
    assert answer.grounding_status == "insufficient_evidence" and not llm.requests


def test_llm_never_receives_mutable_source_registry(monkeypatch):
    original = CitationMapper.map
    contexts = []

    def collect(self, output, context):
        contexts.append(context)
        return original(self, output, context)

    monkeypatch.setattr(CitationMapper, "map", collect)
    llm = FakeLLM()
    service = create_generation_service(llm=llm, settings=settings())
    first = service.generate(request())
    service.generate(request(evidence=[evidence(chunk_id="another")]))
    assert contexts[0] is not contexts[1]
    assert contexts[0].registry is not contexts[1].registry
    assert first.citations[0].evidence_chunk_id == "fictional-chunk-1"
    assert "registry" not in llm.requests[0].input
