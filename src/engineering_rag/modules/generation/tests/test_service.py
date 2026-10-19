"""Generation orchestration with injected, offline StructuredLLMClient only."""

import json

import pytest

from engineering_rag.contracts.answers import AnswerResult, validate_answer_citations
from engineering_rag.contracts.protocols import GenerationService
from engineering_rag.modules.generation.api import GenerationError, create_generation_service
from engineering_rag.modules.generation.internal.context import ContextBuilder

from .helpers import FakeLLM, evidence, request, settings


def test_normal_generation_and_source_mapping_no_mutation():
    llm = FakeLLM()
    service = create_generation_service(llm=llm, settings=settings())
    assert isinstance(service, GenerationService)
    value = request(trace={"trace_id": "fictional-trace"})
    before = value.model_dump_json()
    answer = service.generate(value)
    assert answer.grounding_status == "grounded"
    assert AnswerResult.model_validate_json(answer.model_dump_json()) == answer
    assert value.model_dump_json() == before
    assert not validate_answer_citations(answer, value.evidence)
    citation = answer.citations[0]
    assert citation.document_id == value.evidence[0].document_id
    assert citation.clause_id == value.evidence[0].clause_id
    assert (citation.page_start, citation.page_end) == (2, 3)
    assert citation.quoted_text is None
    call = service.calls[0]
    assert call["usage"] == {"input_tokens": 20, "output_tokens": 10, "total_tokens": 30}
    assert call["elapsed_seconds"] >= 0
    assert call["trace_id"] == "fictional-trace"
    assert call["grounding_status"] == "grounded"
    assert value.question not in json.dumps(call, ensure_ascii=False)
    assert value.evidence[0].content not in json.dumps(call, ensure_ascii=False)
    clone = service.calls
    clone.clear()
    assert len(service.calls) == 1


def test_multiple_sources_and_duplicate_ids_keep_first_use_order():
    llm = FakeLLM()
    llm.data["evidence_ids"] = ["E2", "E1", "E2"]
    value = request(
        evidence=[
            evidence(),
            evidence(chunk_id="second", document_id="another", rank=2, clause_id=None),
        ]
    )
    answer = create_generation_service(llm=llm, settings=settings()).generate(value)
    assert [c.evidence_chunk_id for c in answer.citations] == ["second", "fictional-chunk-1"]
    assert answer.citations[0].clause_id is None
    assert answer.citations[0].document_id == "another"


def test_empty_and_all_omitted_evidence_do_not_call_model():
    llm = FakeLLM()
    service = create_generation_service(llm=llm, settings=settings())
    answer = service.generate(request(evidence=[]))
    assert answer.grounding_status == "insufficient_evidence" and not answer.citations
    assert answer.model is None and llm.requests == []
    base = ContextBuilder(settings()).build(request(evidence=[])).estimated_chars
    tiny = create_generation_service(llm=llm, settings=settings(max_context_chars=base + 1))
    assert tiny.generate(request()).grounding_status == "insufficient_evidence"
    assert llm.requests == []


@pytest.mark.parametrize("status", ["grounded", "partially_grounded"])
def test_partial_support_and_model_limitations(status):
    llm = FakeLLM()
    llm.data.update(grounding_status=status, limitations=["仅可回答检修间隔"])
    answer = create_generation_service(llm=llm, settings=settings()).generate(request())
    assert answer.grounding_status == "partially_grounded" and answer.warnings


def test_omitted_evidence_prevents_unqualified_grounded():
    base = ContextBuilder(settings()).build(request()).estimated_chars
    llm = FakeLLM()
    value = request(evidence=[evidence(), evidence(chunk_id="long", rank=2, content="长" * 10000)])
    answer = create_generation_service(
        llm=llm, settings=settings(max_context_chars=base + 10)
    ).generate(value)
    assert answer.grounding_status == "partially_grounded"
    assert any("omitted" in w.message for w in answer.warnings)


def test_insufficient_does_not_publish_untrusted_normative_answer():
    llm = FakeLLM()
    llm.data.update(
        answer="没有依据的确定结论", grounding_status="insufficient_evidence", evidence_ids=[]
    )
    answer = create_generation_service(llm=llm, settings=settings()).generate(request())
    assert answer.grounding_status == "insufficient_evidence"
    assert "没有依据的确定结论" not in answer.answer
    assert not answer.citations


@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"evidence_ids": ["invented"]}, "unknown_evidence_id"),
        ({"evidence_ids": []}, "grounding_conflict"),
        ({"grounding_status": "partially_grounded", "evidence_ids": []}, "grounding_conflict"),
        ({"grounding_status": "insufficient_evidence"}, "grounding_conflict"),
        ({"answer": "a" * 13000}, "output_budget"),
    ],
)
def test_semantic_output_contradictions_fail_explicitly(updates, code):
    llm = FakeLLM()
    llm.data.update(updates)
    service = create_generation_service(llm=llm, settings=settings())
    with pytest.raises(GenerationError) as caught:
        service.generate(request())
    assert caught.value.code == code
    assert service.calls[-1]["status"] == code


@pytest.mark.parametrize(
    "updates",
    [
        {"answer": ""},
        {"answer": "  "},
        {"citations": [{"document_id": "forged"}]},
        {"grounding_status": "approved"},
        {"evidence_ids": [7]},
    ],
)
def test_schema_errors_are_not_accepted_as_answers(updates):
    llm = FakeLLM()
    llm.data.update(updates)
    service = create_generation_service(llm=llm, settings=settings())
    with pytest.raises(GenerationError, match="invalid_output"):
        service.generate(request())
    assert len(llm.requests) == 2


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("secret raw failure"),
        ConnectionError("secret raw failure"),
        ValueError("secret output"),
    ],
)
def test_retryable_errors_are_bounded_and_can_recover(failure):
    llm = FakeLLM(failures=[failure])
    service = create_generation_service(llm=llm, settings=settings())
    assert service.generate(request()).citations
    assert len(llm.requests) == 2
    assert "secret" not in json.dumps(service.calls)
    assert service.calls[0]["status"] == (
        "timeout"
        if isinstance(failure, TimeoutError)
        else "connection"
        if isinstance(failure, ConnectionError)
        else "invalid_output"
    )


def test_failure_is_not_a_fabricated_answer_and_no_infinite_retry():
    llm = FakeLLM(failures=[TimeoutError(), TimeoutError(), TimeoutError()])
    service = create_generation_service(llm=llm, settings=settings())
    with pytest.raises(GenerationError):
        service.generate(request())
    assert len(llm.requests) == 2


@pytest.mark.parametrize("code", ["rate_limit", "authentication", "permission", "server_error"])
def test_nonretryable_existing_provider_error_categories_are_preserved(code):
    class ProviderFailure(RuntimeError):
        pass

    failure = ProviderFailure("secret provider body")
    failure.code = code
    llm = FakeLLM(failures=[failure])
    service = create_generation_service(llm=llm, settings=settings())
    with pytest.raises(GenerationError) as caught:
        service.generate(request())
    assert caught.value.code == code
    assert len(llm.requests) == 1
    assert "secret" not in str(caught.value)


def test_request_config_overrides_only_existing_generation_options():
    llm = FakeLLM()
    service = create_generation_service(llm=llm, settings=settings())
    service.generate(
        request(config={"config_id": "caller", "max_output_tokens": 99, "temperature": 0.3})
    )
    config = llm.requests[0].config
    assert config.model_id == "fictional-model" and config.timeout_seconds == 5
    assert config.max_output_tokens == 99 and config.temperature == 0.3


def test_response_binding_cannot_be_bypassed():
    class WrongResponse(FakeLLM):
        def generate(self, value):
            result = super().generate(value)
            return result.model_copy(update={"request_id": "different"})

    service = create_generation_service(llm=WrongResponse(), settings=settings())
    with pytest.raises(GenerationError, match="invalid_output"):
        service.generate(request())
