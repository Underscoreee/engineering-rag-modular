"""Offline Expansion/HyDE tests. Synthetic hypotheses are never standard evidence."""

import json
from collections.abc import Callable
from copy import deepcopy

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.common import TraceContext
from engineering_rag.contracts.llm import (
    LLMTokenUsage,
    StructuredLLMConfig,
    StructuredLLMRequest,
    StructuredLLMResponse,
)
from engineering_rag.contracts.queries import ProcessingIntent, QueryRequest
from engineering_rag.modules.query.internal.enhancement import QueryEnhancement
from engineering_rag.modules.query.internal.enhancement_models import (
    EnhancementConfig,
    EnhancementInputError,
    QueryEnhancementResult,
    RelatedContext,
)
from engineering_rag.modules.query.internal.enhancement_prompts import (
    EXPANSION_SEPARATOR,
    HYDE_CONTEXT_SEPARATOR,
    HYDE_FOOTER,
    HYDE_HEADER,
)

from .test_rewrite import RewriteLLM, reply, rewriter, understanding

QUESTION = "比较设备设计规范的条件与要求？"
CONTEXTS = [
    RelatedContext(
        anchor="设计", phrase="设计条件与验算要求之间的关联", evidence_id="reviewed-context-a"
    ),
    RelatedContext(
        anchor="规范", phrase="规范适用范围与条文关联", evidence_id="reviewed-context-b"
    ),
    RelatedContext(
        anchor="比较", phrase="比较对象的适用条件与差异", evidence_id="reviewed-context-c"
    ),
]
Payload = dict[str, object] | Exception | Callable[[StructuredLLMRequest], StructuredLLMResponse]


def inputs(question: str = QUESTION, intent: str = "exploratory"):
    req = QueryRequest(question=question)
    und = understanding(question, intent=intent)
    rewritten = rewriter(RewriteLLM(reply(question))).rewrite(req, und)
    return req, und, rewritten


def expanded(query: str = QUESTION, index: int = 0) -> str:
    return query + EXPANSION_SEPARATOR + CONTEXTS[index].phrase


def hypothesis(query: str = QUESTION, phrases: list[str] | None = None) -> str:
    return (
        HYDE_HEADER
        + query
        + "".join(HYDE_CONTEXT_SEPARATOR + phrase for phrase in (phrases or []))
        + HYDE_FOOTER
    )


class FakeEnhancementLLM:
    def __init__(self, expansion: Payload | None = None, hyde: Payload | None = None) -> None:
        self.responses = {
            "query_expansion": expansion
            if expansion is not None
            else dict(expanded_queries=[expanded()]),
            "query_hyde": hyde
            if hyde is not None
            else dict(hypothetical_document=hypothesis(phrases=[CONTEXTS[0].phrase])),
        }
        self.requests: list[StructuredLLMRequest] = []

    def generate(self, request: StructuredLLMRequest) -> StructuredLLMResponse:
        self.requests.append(request.model_copy(deep=True))
        response = self.responses[request.stage]
        if isinstance(response, Exception):
            raise response
        if callable(response):
            return response(request)
        return StructuredLLMResponse(
            request_id=request.request_id,
            model_id=request.config.model_id,
            model_revision=request.config.model_revision,
            data=deepcopy(response),
        )


def enhancer(llm: FakeEnhancementLLM, **options: object) -> QueryEnhancement:
    cfg = StructuredLLMConfig(
        config_id="enhancement-fixture",
        model_id="offline-model",
        model_revision="fixture-v1",
        timeout_seconds=2,
        max_output_tokens=2048,
    )
    return QueryEnhancement(
        llm=llm,
        config=EnhancementConfig(
            expansion_llm=cfg, hyde_llm=cfg, related_contexts=CONTEXTS, **options
        ),
    )


@pytest.mark.parametrize(
    "question", [QUESTION, "第4.2.1条的公式是什么？", "分析多种约束并进行跨标准比较"]
)
def test_acquisition_skips_both_stages_without_keyword_reclassification(question):
    llm = FakeEnhancementLLM()
    req, und, rewritten = inputs(question, "acquisition")
    result = enhancer(llm).enhance(req, und, rewritten)
    assert result.expansion_status == result.hyde_status == "skipped_by_intent"
    assert result.expanded_queries == []
    assert result.hypothetical_document is None
    assert result.keyword_synonyms == rewritten.keyword_synonyms
    assert result.rewritten_query == rewritten.rewritten_query
    assert not result.degraded
    assert llm.requests == []


def test_exploratory_attempts_two_separate_bound_stages():
    llm = FakeEnhancementLLM()
    result = enhancer(llm).enhance(*inputs())
    assert result.expansion_status == result.hyde_status == "completed"
    assert result.expanded_queries == [expanded()]
    assert result.hypothetical_document == hypothesis(phrases=[CONTEXTS[0].phrase])
    assert result.hypothesis_is_evidence is False
    assert [item.stage for item in llm.requests] == ["query_expansion", "query_hyde"]
    assert llm.requests[0].output_schema != llm.requests[1].output_schema
    assert "keyword_synonyms" not in llm.requests[1].input
    assert "hyde_header" not in llm.requests[0].input
    assert llm.requests[0].request_id != llm.requests[1].request_id
    assert result.expansion_report.attempts[0].usage is None
    assert QueryEnhancementResult.model_validate_json(result.model_dump_json()) == result


def test_short_exploratory_question_still_attempts_both_stages():
    question = "参数？"
    llm = FakeEnhancementLLM(
        dict(expanded_queries=[]), dict(hypothetical_document=hypothesis(question))
    )
    result = enhancer(llm).enhance(*inputs(question, "exploratory"))
    assert result.expansion_status == result.hyde_status == "completed"
    assert len(llm.requests) == 2


@pytest.mark.parametrize(("expansion", "hyde"), [(False, True), (True, False), (False, False)])
def test_independent_feature_switches(expansion, hyde):
    llm = FakeEnhancementLLM()
    result = enhancer(llm, enable_expansion=expansion, enable_hyde=hyde).enhance(*inputs())
    assert result.expansion_status == ("completed" if expansion else "skipped_by_config")
    assert result.hyde_status == ("completed" if hyde else "skipped_by_config")
    assert len(llm.requests) == int(expansion) + int(hyde)
    assert not result.degraded


@pytest.mark.parametrize("intent", ["unknown", "requirement", None, 1])
def test_invalid_intent_fails_before_extra_model_calls(intent):
    req, und, rewritten = inputs()
    und = und.model_copy(update={"processing_intent": intent})
    llm = FakeEnhancementLLM()
    with pytest.raises(EnhancementInputError):
        enhancer(llm).enhance(req, und, rewritten)
    assert llm.requests == []


@pytest.mark.parametrize("mutation", ["question", "intent", "filters", "blank"])
def test_mismatched_prior_stage_results_fail_not_optional_degradation(mutation):
    req, und, rewritten = inputs()
    if mutation == "question":
        rewritten.original_question = "different question"
    if mutation == "intent":
        rewritten.processing_intent = ProcessingIntent.ACQUISITION
    if mutation == "filters":
        rewritten.filters.is_mandatory = True
    if mutation == "blank":
        rewritten.rewritten_query = "  "
    llm = FakeEnhancementLLM()
    with pytest.raises(EnhancementInputError):
        enhancer(llm).enhance(req, und, rewritten)
    assert llm.requests == []


def test_multiple_expansions_and_stable_deduplication():
    candidates = [expanded(index=0), expanded(index=0), expanded(index=1), expanded(index=2)]
    result = enhancer(FakeEnhancementLLM(dict(expanded_queries=candidates))).enhance(*inputs())
    assert result.expanded_queries == [expanded(index=i) for i in range(3)]
    assert result.expansion_status == "completed"
    assert any(item.reason == "duplicate" for item in result.expansion_report.decisions)


def test_empty_expansion_is_completed_not_failed():
    result = enhancer(FakeEnhancementLLM(dict(expanded_queries=[]))).enhance(*inputs())
    assert result.expansion_status == "completed"
    assert result.expanded_queries == []
    assert not result.degraded


def test_expansion_count_limit_preserves_prefix_and_reports_discard():
    result = enhancer(
        FakeEnhancementLLM(dict(expanded_queries=[expanded(index=i) for i in range(3)])),
        max_expansions=2,
    ).enhance(*inputs())
    assert result.expanded_queries == [expanded(index=0), expanded(index=1)]
    assert any(item.reason == "count_budget" for item in result.expansion_report.decisions)
    assert result.degraded


@pytest.mark.parametrize(
    "bad",
    [
        "",
        " ",
        "无关的音乐检索问题",
        "\n",  # distinct blank/whitespace cases
        QUESTION + EXPANSION_SEPARATOR + "抗震等级等价于抗震设防类别",
        QUESTION + EXPANSION_SEPARATOR + "GB 00000-2099",
        QUESTION + EXPANSION_SEPARATOR + "公式6.2.1-1",
        QUESTION + EXPANSION_SEPARATOR + "参数应为0.2",
        QUESTION + EXPANSION_SEPARATOR + "所有标准的要求",
        QUESTION + "正确答案是采用该方法",
    ],
)
def test_unsafe_or_unrelated_expansion_is_rejected_without_breaking_hyde(bad):
    result = enhancer(FakeEnhancementLLM(dict(expanded_queries=[bad]))).enhance(*inputs())
    assert result.expansion_status == "failed"
    assert result.expanded_queries == []
    assert result.hyde_status == "completed"
    assert result.degraded


@pytest.mark.parametrize(
    ("query", "changed"),
    [
        (
            "GB 00001-2026第4.2.1条不应超过0.20 mm，设计如何验算？",
            "GB 00002-2026第4.2.1条不应超过0.20 mm，设计如何验算？",
        ),
        ("第4.2.1条公式6.2.1-1与表5.2.4的设计要求？", "第4.2.2条公式6.2.1-1与表5.2.4的设计要求？"),
        ("图6.2.1中的条件x≤h_0用于设计时不应删除", "图6.2.1中的条件x<h_0用于设计时不应删除"),
        ("设计长度0.20 mm", "设计长度0.2 mm"),
        ("设计长度20 mm", "设计长度2 cm"),
        ("设计时不应超过限值", "设计时应超过限值"),
        ("设计时宜满足条件", "设计时必须满足条件"),
        ("当A且B成立时设计方法", "当A或B成立时设计方法"),
        ("比较混凝土与钢筋的设计条件", "比较钢筋与混凝土的设计条件"),
        ("仅分析当前规范的设计条件", "分析全行业规范的设计条件"),
    ],
)
@pytest.mark.parametrize("stage", ["query_expansion", "query_hyde"])
def test_all_original_technical_and_scope_constraints_are_preserved(query, changed, stage):
    # Typed prior-stage fixtures isolate candidate protection; no new directory is created.
    req, und, rewritten = inputs()
    req.question = query
    rewritten.original_question = query
    rewritten.rewritten_query = query
    from engineering_rag.modules.query.internal.rewrite_protection import extract_protected_spans

    rewritten.protected_spans = extract_protected_spans(query)
    llm = FakeEnhancementLLM(
        dict(expanded_queries=[expanded(changed)]), dict(hypothetical_document=hypothesis(changed))
    )
    result = enhancer(llm).enhance(req, und, rewritten)
    assert (
        result.expansion_status if stage == "query_expansion" else result.hyde_status
    ) == "failed"


@pytest.mark.parametrize(
    "bad",
    [
        "",
        " ",
        "设备基础设计应取安全系数1.2。",
        "根据GB 00000-2099第4.2.1条规定，必须采用该方法。",
        "假设该要求来自某真实规范的原文。",
        "检索音乐艺术相关内容。",
        hypothesis() + "出处：规范原文",
        hypothesis(phrases=["参数为20 mm"]),
        hypothesis(phrases=["应按公式6.2.1-2取值"]),
        hypothesis(phrases=["结构承载力满足要求"]),
    ],
)
def test_hyde_empty_fake_sources_facts_and_parameters_are_rejected(bad):
    result = enhancer(FakeEnhancementLLM(hyde=dict(hypothetical_document=bad))).enhance(*inputs())
    assert result.expansion_status == "completed"
    assert result.hyde_status == "failed"
    assert result.hypothetical_document is None
    assert result.degraded


def test_failed_stages_preserve_safe_base_and_synonyms():
    req, und, rewritten = inputs()
    rewritten.keyword_synonyms = ["已验证的虚构同义词"]
    llm = FakeEnhancementLLM(TimeoutError("expansion timeout"), ConnectionError("hyde offline"))
    result = enhancer(llm).enhance(req, und, rewritten)
    assert result.expansion_status == result.hyde_status == "failed"
    assert result.expanded_queries == [] and result.hypothetical_document is None
    assert result.rewritten_query == QUESTION
    assert result.keyword_synonyms == rewritten.keyword_synonyms
    assert result.filters == und.filters
    assert len(llm.requests) == 2
    assert result.expansion_report.error_code == "timeout"
    assert result.hyde_report.error_code == "connection"


def test_no_history_or_complete_upstream_object_is_sent_to_models():
    req, und, rewritten = inputs()
    req.history = [dict(role="assistant", content="private history not needed by enhancement")]
    llm = FakeEnhancementLLM()
    enhancer(llm).enhance(req, und, rewritten)
    for request in llm.requests:
        assert "history" not in request.input
        assert "options" not in request.input
        assert "catalog_matches" not in request.input
        assert "private history" not in request.model_dump_json()


@pytest.mark.parametrize("stage", ["query_expansion", "query_hyde"])
@pytest.mark.parametrize(
    "fault",
    ["request_id", "model_id", "model_revision", "extra", "missing", "wrong_type", "invalid_json"],
)
def test_independent_schema_and_binding_validation(stage, fault):
    def invalid(request):
        data = (
            dict(expanded_queries=[expanded()])
            if stage == "query_expansion"
            else dict(hypothetical_document=hypothesis())
        )
        if fault == "extra":
            data["filters"] = {}
        if fault == "missing":
            data = {}
        if fault == "wrong_type":
            data = (
                dict(expanded_queries="not-list")
                if stage == "query_expansion"
                else dict(hypothetical_document=[])
            )
        if fault == "invalid_json":
            data = "not-a-json-object"
        kwargs = dict(
            request_id=request.request_id,
            model_id=request.config.model_id,
            model_revision=request.config.model_revision,
            data=data,
        )
        if fault in {"request_id", "model_id", "model_revision"}:
            kwargs[fault] = "wrong"
        return StructuredLLMResponse(**kwargs)

    llm = FakeEnhancementLLM(**{("expansion" if stage == "query_expansion" else "hyde"): invalid})
    result = enhancer(llm).enhance(*inputs())
    failed = result.expansion_report if stage == "query_expansion" else result.hyde_report
    assert failed.error_code == "invalid_output"
    assert (
        result.expansion_status if stage == "query_expansion" else result.hyde_status
    ) == "failed"
    assert (
        result.hyde_status if stage == "query_expansion" else result.expansion_status
    ) == "completed"
    assert len(llm.requests) == 2


def test_budget_is_shared_and_correction_does_not_prevent_other_normal_attempt():
    llm = FakeEnhancementLLM(TimeoutError("first"), dict(hypothetical_document="unsafe"))
    result = enhancer(llm, max_corrections=1).enhance(*inputs())
    assert len(llm.requests) == 3
    assert [req.stage for req in llm.requests] == [
        "query_expansion",
        "query_expansion",
        "query_hyde",
    ]
    assert result.expansion_status == result.hyde_status == "failed"


def test_one_corrected_stage_can_recover_but_other_stage_remains_independent():
    calls = 0

    def corrected(request):
        nonlocal calls
        calls += 1
        return StructuredLLMResponse(
            request_id=request.request_id,
            model_id=request.config.model_id,
            model_revision=request.config.model_revision,
            data={"wrong": True} if calls == 1 else dict(expanded_queries=[expanded()]),
        )

    result = enhancer(FakeEnhancementLLM(expansion=corrected), max_corrections=1).enhance(*inputs())
    assert result.expansion_status == result.hyde_status == "completed"
    assert len(result.expansion_report.attempts) == 2
    assert len(result.hyde_report.attempts) == 1
    assert result.degraded


@pytest.mark.parametrize("budget", [0, 1, True, 2])
def test_correction_budget_strictly_allows_only_zero_or_one(budget):
    if type(budget) is int and budget in {0, 1}:
        enhancer(FakeEnhancementLLM(), max_corrections=budget)
    else:
        with pytest.raises(ValidationError):
            enhancer(FakeEnhancementLLM(), max_corrections=budget)


@pytest.mark.parametrize(
    ("option", "value", "stage"),
    [
        ("max_expanded_query_chars", 2, "expansion"),
        ("max_hyde_chars", 2, "hyde"),
    ],
)
def test_output_budgets_do_not_truncate_base(option, value, stage):
    result = enhancer(FakeEnhancementLLM(), **{option: value}).enhance(*inputs())
    assert (result.expansion_status if stage == "expansion" else result.hyde_status) == "failed"
    assert result.rewritten_query == QUESTION


def test_read_only_inputs_keyword_boundary_json_roundtrip_and_safe_logs(caplog):
    caplog.set_level("INFO", logger="engineering_rag.modules.query.internal.enhancement")
    req, und, rewritten = inputs()
    req.trace = TraceContext(trace_id="trace-enhance", task_id="task-enhance")
    rewritten.trace = req.trace
    before = tuple(item.model_dump_json() for item in (req, und, rewritten))
    result = enhancer(FakeEnhancementLLM()).enhance(req, und, rewritten)
    assert before == tuple(item.model_dump_json() for item in (req, und, rewritten))
    assert result.keyword_synonyms == rewritten.keyword_synonyms
    assert "keyword_query" not in type(result).model_fields
    assert "vector_query" not in type(result).model_fields
    assert result.filters == rewritten.filters
    assert result.filters is not rewritten.filters
    assert QUESTION not in caplog.text
    for record in caplog.records:
        if record.name.endswith(".enhancement"):
            assert QUESTION not in str(record.__dict__)
    assert "query_hyde" in caplog.text
    assert QueryEnhancementResult.model_validate_json(result.model_dump_json()) == result


def test_model_cannot_mutate_verified_inputs_or_schema_used_by_validator():
    def mutate(request):
        request.input["verified_filters"] = dict(document_ids=["fake-id"])
        request.output_schema = {}
        return StructuredLLMResponse(
            request_id=request.request_id,
            model_id=request.config.model_id,
            model_revision=request.config.model_revision,
            data=dict(expanded_queries=[expanded()]),
        )

    req, und, rewritten = inputs()
    result = enhancer(FakeEnhancementLLM(expansion=mutate)).enhance(req, und, rewritten)
    assert result.expansion_status == "completed"
    assert result.filters.document_ids == und.filters.document_ids == []


def test_known_usage_and_per_call_state_are_not_fabricated_or_shared():
    def known(request):
        return StructuredLLMResponse(
            request_id=request.request_id,
            model_id=request.config.model_id,
            model_revision=request.config.model_revision,
            data=dict(hypothetical_document=hypothesis()),
            usage=LLMTokenUsage(input_tokens=2, output_tokens=3, total_tokens=5),
        )

    sut = enhancer(FakeEnhancementLLM(hyde=known))
    a = sut.enhance(*inputs())
    b = sut.enhance(*inputs())
    assert a.hyde_report.attempts[0].usage.total_tokens == 5
    assert a.expansion_report.attempts[0].usage is None
    assert len(a.hyde_report.attempts) == len(b.hyde_report.attempts) == 1
    assert a.policy_fingerprint == b.policy_fingerprint


def test_partial_candidate_rejection_is_explicit_but_valid_candidates_survive():
    llm = FakeEnhancementLLM(dict(expanded_queries=["音乐艺术检索", expanded(), "标准取值为1.2"]))
    result = enhancer(llm).enhance(*inputs())
    assert result.expansion_status == "completed"
    assert result.expanded_queries == [expanded()]
    assert result.degraded
    assert [item.adopted for item in result.expansion_report.decisions] == [False, True, False]


def test_duplicates_of_primary_mean_no_useful_expansion_not_model_failure():
    result = enhancer(FakeEnhancementLLM(dict(expanded_queries=[QUESTION, QUESTION]))).enhance(
        *inputs()
    )
    assert result.expanded_queries == []
    assert result.expansion_status == "completed"
    assert not result.degraded


def test_more_than_transport_schema_candidate_limit_fails_without_unsafe_truncation():
    result = enhancer(FakeEnhancementLLM(dict(expanded_queries=[expanded()] * 17))).enhance(
        *inputs()
    )
    assert result.expansion_status == "failed"
    assert result.expansion_report.error_code == "invalid_output"
    assert result.hyde_status == "completed"


@pytest.mark.parametrize(
    "bad",
    ["参数为0.2", "依据GB 00000-2099", "公式6.2.1-1", "全部标准", "抗震等级等同于抗震设防类别"],
)
def test_caller_context_policy_cannot_inject_parameters_sources_or_equivalence_claims(bad):
    cfg = StructuredLLMConfig(
        config_id="fixture", model_id="fixture", timeout_seconds=1, max_output_tokens=100
    )
    with pytest.raises(ValueError):
        QueryEnhancement(
            llm=FakeEnhancementLLM(),
            config=EnhancementConfig(
                expansion_llm=cfg,
                hyde_llm=cfg,
                related_contexts=[
                    RelatedContext(anchor="设计", phrase=bad, evidence_id="misconfigured-fixture")
                ],
            ),
        )


def test_context_anchor_cannot_be_a_substring_inside_another_identifier():
    cfg = StructuredLLMConfig(
        config_id="fixture", model_id="fixture", timeout_seconds=1, max_output_tokens=100
    )
    context = RelatedContext(anchor="BC", phrase="虚构关联检索概念", evidence_id="reviewed-fixture")
    question = "分析ABC的关联"
    llm = FakeEnhancementLLM(
        dict(expanded_queries=[question + EXPANSION_SEPARATOR + context.phrase]),
        dict(hypothetical_document=hypothesis(question, [context.phrase])),
    )
    result = QueryEnhancement(
        llm=llm,
        config=EnhancementConfig(expansion_llm=cfg, hyde_llm=cfg, related_contexts=[context]),
    ).enhance(*inputs(question))
    assert result.expansion_status == result.hyde_status == "failed"


@pytest.mark.parametrize(
    "hypo",
    [
        hypothesis(phrases=[CONTEXTS[0].phrase, CONTEXTS[0].phrase]),
        hypothesis(phrases=[CONTEXTS[0].phrase, CONTEXTS[1].phrase]),
    ],
)
def test_hypothesis_context_count_and_duplicates_are_enforced(hypo):
    result = enhancer(
        FakeEnhancementLLM(hyde=dict(hypothetical_document=hypo)), max_hyde_contexts=1
    ).enhance(*inputs())
    assert result.hyde_status == "failed"
    assert result.expansion_status == "completed"


def test_input_budgets_stop_before_model_without_changing_original():
    upstream = inputs()
    llm = FakeEnhancementLLM()
    before = upstream[0].question
    with pytest.raises(EnhancementInputError) as error:
        enhancer(llm, max_primary_chars=2).enhance(*upstream)
    assert error.value.code == "input_budget"
    assert upstream[0].question == before
    assert not llm.requests


def test_other_model_errors_are_reported_without_spending_correction_on_them():
    result = enhancer(
        FakeEnhancementLLM(
            RuntimeError("fixture auth failure"), RuntimeError("fixture unavailable")
        ),
        max_corrections=1,
    ).enhance(*inputs())
    assert result.expansion_report.error_code == result.hyde_report.error_code == "model_failure"
    assert len(result.expansion_report.attempts) == len(result.hyde_report.attempts) == 1


def test_correction_budget_can_be_spent_on_hyde_when_expansion_is_disabled():
    llm = FakeEnhancementLLM(hyde=TimeoutError("timeout"))
    result = enhancer(llm, enable_expansion=False, max_corrections=1).enhance(*inputs())
    assert [item.stage for item in llm.requests] == ["query_hyde", "query_hyde"]
    assert result.expansion_status == "skipped_by_config"
    assert result.hyde_status == "failed"


@pytest.mark.parametrize("bad_field", ["statuses", "hypothesis", "fact", "report", "degradation"])
def test_persisted_result_cannot_misrepresent_skips_failures_or_synthetic_evidence(bad_field):
    result = enhancer(FakeEnhancementLLM(TimeoutError("timeout"), TimeoutError("timeout"))).enhance(
        *inputs()
    )
    payload = result.model_dump(mode="json")
    if bad_field == "statuses":
        payload["hyde_status"] = "completed"
    if bad_field == "hypothesis":
        payload["hypothetical_document"] = "fabricated text on failure"
    if bad_field == "fact":
        payload["hypothesis_is_evidence"] = True
    if bad_field == "report":
        payload["expansion_report"]["stage"] = "query_hyde"
    if bad_field == "degradation":
        payload["degraded"] = False
    with pytest.raises(ValidationError):
        QueryEnhancementResult.model_validate_json(json.dumps(payload))


def test_config_and_returned_data_are_not_shared_across_requests():
    llm = FakeEnhancementLLM()
    sut = enhancer(llm)
    a = sut.enhance(*inputs())
    a.filters.document_ids.append("mutated-return-value")
    a.keyword_synonyms.append("mutated-return-value")
    b = sut.enhance(*inputs())
    assert b.filters.document_ids == []
    assert b.keyword_synonyms == []


def test_input_delimiters_cannot_escape_the_full_anchor_or_create_false_contexts():
    question = QUESTION + EXPANSION_SEPARATOR + "原问题中的标签文本"
    llm = FakeEnhancementLLM(
        dict(expanded_queries=[expanded(question)]),
        dict(hypothetical_document=hypothesis(question, [CONTEXTS[0].phrase])),
    )
    result = enhancer(llm).enhance(*inputs(question))
    assert result.expansion_status == result.hyde_status == "completed"
    assert question in result.expanded_queries[0]
    assert question in result.hypothetical_document
