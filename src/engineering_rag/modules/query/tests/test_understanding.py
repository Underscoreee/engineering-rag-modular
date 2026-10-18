"""Offline Understanding acceptance tests; all standard records are fictional."""

from copy import deepcopy

import pytest

from engineering_rag.contracts.catalog import (
    CatalogIndexScope,
    StandardMetadataLookup,
    StandardMetadataMatch,
    StandardMetadataRecord,
)
from engineering_rag.contracts.documents import StandardMetadata
from engineering_rag.contracts.llm import (
    StructuredLLMConfig,
    StructuredLLMRequest,
    StructuredLLMResponse,
)
from engineering_rag.contracts.queries import QueryRequest
from engineering_rag.contracts.retrieval import SearchFilters
from engineering_rag.modules.query.internal.config import UnderstandingConfig
from engineering_rag.modules.query.internal.errors import UnderstandingError
from engineering_rag.modules.query.internal.understanding import QueryUnderstanding

SCOPE = CatalogIndexScope(keyword_index="fixture_keyword", vector_collection="fixture_vector")
CODE_A = "GB/T 00001-2026"
CODE_B = "GB/T 00002-2025"


def record(code: str = CODE_A, edition: str = "2026", suffix: str = "a"):
    return StandardMetadataRecord(
        record_id=f"record-{suffix}",
        document_id=f"document-{suffix}",
        standard=StandardMetadata(
            standard_code=code,
            standard_name="虚构设备设计标准" if code == CODE_A else "虚构基础设计标准",
            edition=edition,
            revision="演示修订",
        ),
        aliases=["设备示范规范"] if code == CODE_A else [],
        indexed_scopes=[SCOPE],
    )


class FixtureCatalog:
    def __init__(self, records=None, status=None):
        self.records = records if records is not None else [record()]
        self.status = status
        self.requests = []

    def lookup(self, request: StandardMetadataLookup) -> StandardMetadataMatch:
        self.requests.append(request.model_copy(deep=True))
        candidates = [
            item
            for item in self.records
            if all(
                expected is None or expected == actual
                for expected, actual in (
                    (request.document_id, item.document_id),
                    (request.standard_code, item.standard.standard_code),
                    (request.edition, item.standard.edition),
                    (request.revision, item.standard.revision),
                )
            )
            and (
                request.standard_name is None
                or request.standard_name in [item.standard.standard_name, *item.aliases]
            )
        ]
        status = self.status or (
            "unique" if len(candidates) == 1 else "ambiguous" if candidates else "not_found"
        )
        if status in {"unavailable", "not_found"}:
            candidates = []
        return StandardMetadataMatch(
            request_id=request.request_id,
            catalog_id="fixture-catalog",
            snapshot_id="snapshot-1",
            is_test_fixture=True,
            status=status,
            candidates=candidates,
            reason="offline fixture" if status == "unavailable" else None,
        )


def output(intent="acquisition", **overrides):
    return dict(
        processing_intent=intent,
        context_sufficient=True,
        standards=[],
        clause_numbers=[],
        content_types=[],
        is_explanation=None,
        is_mandatory=None,
        **overrides,
    )


def evidence(text, quote, source="question", history_index=None):
    start = text.index(quote)
    return dict(
        source=source, history_index=history_index, start=start, end=start + len(quote), quote=quote
    )


def value(text, value_, **kwargs):
    return dict(value=value_, evidence=evidence(text, value_, **kwargs))


def standard(text, code=CODE_A):
    return dict(standard_code=value(text, code))


class FixtureLLM:
    def __init__(self, *responses):
        self.responses = list(responses or [output()])
        self.requests = []

    def generate(self, request: StructuredLLMRequest) -> StructuredLLMResponse:
        self.requests.append(request.model_copy(deep=True))
        response = self.responses[min(len(self.requests) - 1, len(self.responses) - 1)]
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


def service(payload=None, *, catalog=None, llm=None, **config):
    return QueryUnderstanding(
        llm=llm or FixtureLLM(payload or output()),
        catalog=catalog or FixtureCatalog(),
        config=UnderstandingConfig(
            llm=StructuredLLMConfig(
                config_id="offline",
                model_id="fixture-model",
                model_revision="fixture-v1",
                timeout_seconds=3,
                max_output_tokens=2048,
            ),
            scope=SCOPE,
            allow_test_catalog=True,
            **config,
        ),
    )


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("检修通道宽度限值是多少？", "acquisition"),
        ("分析设备荷载、基础刚度和维护空间之间的关联", "exploratory"),
        ("请综合分析多类约束", "exploratory"),
        ("分析给定温度、荷载和适用条件下这一条文的确切限值", "acquisition"),
    ],
)
def test_intent_is_structured_model_decision_not_keyword_mapping(question, intent):
    llm = FixtureLLM(output(intent))
    result = service(llm=llm).understand(QueryRequest(question=question))
    assert result.processing_intent == intent
    assert result.semantic_intent == "unknown"
    assert result.attempts[0].usage is None
    assert llm.requests[0].stage == "query_understanding"
    assert llm.requests[0].input["question"] == question
    assert result.prompt_version


def test_unique_scope_clause_content_and_flags():
    q = f"查询{CODE_A}第1.2.3条的公式、表格及条文说明，仅强制性条文"
    payload = output()
    payload.update(
        standards=[standard(q)],
        clause_numbers=[value(q, "1.2.3")],
        content_types=[
            dict(value="formula", evidence=evidence(q, "公式")),
            dict(value="table", evidence=evidence(q, "表格")),
        ],
        is_explanation=dict(value=True, evidence=evidence(q, "条文说明")),
        is_mandatory=dict(value=True, evidence=evidence(q, "强制性条文")),
    )
    request = QueryRequest(question=q)
    before = request.model_dump_json()
    result = service(payload).understand(request)
    assert result.filters.document_ids == ["document-a"]
    assert result.filters.standard_codes == [CODE_A]
    assert result.filters.clause_numbers == ["1.2.3"]
    assert result.filters.content_types == ["formula", "table"]
    assert result.filters.is_explanation is result.filters.is_mandatory is True
    assert result.clause_existence_verified is False
    assert result.catalog_matches[0].snapshot_id == "snapshot-1"
    assert request.model_dump_json() == before
    assert result.filters is not request.filters


@pytest.mark.parametrize("selector", ["standard_name", "alias"])
def test_name_and_trusted_alias(selector):
    name = "设备示范规范" if selector == "alias" else "虚构设备设计标准"
    q = f"查询《{name}》的规定"
    payload = output()
    payload["standards"] = [dict(standard_name=value(q, name))]
    assert service(payload).understand(QueryRequest(question=q)).filters.document_ids == [
        "document-a"
    ]


def test_multiple_explicit_standards_preserve_version_pairs():
    q = f"比较{CODE_A}与{CODE_B}的规定"
    payload = output("exploratory")
    payload["standards"] = [standard(q), standard(q, CODE_B)]
    catalog = FixtureCatalog([record(), record(CODE_B, "2025", "b")])
    result = service(payload, catalog=catalog).understand(QueryRequest(question=q))
    assert result.filters.document_ids == ["document-a", "document-b"]
    assert len(catalog.requests) == 2
    assert len({item.request_id for item in catalog.requests}) == 2
    assert all(item.scope == SCOPE for item in catalog.requests)


@pytest.mark.parametrize(
    ("status", "code"),
    [
        ("not_found", "unmatched_scope"),
        ("unavailable", "catalog_unavailable"),
        ("ambiguous", "ambiguous_scope"),
    ],
)
def test_explicit_scope_failures_never_broaden(status, code):
    q = f"查询{CODE_A}"
    payload = output()
    payload["standards"] = [standard(q)]
    catalog = FixtureCatalog([record(), record(edition="2027", suffix="next")], status)
    with pytest.raises(UnderstandingError) as error:
        service(payload, catalog=catalog).understand(QueryRequest(question=q))
    assert error.value.code == code
    assert any(item.status == "rejected" for item in error.value.decisions)


def test_explicit_edition_and_revision_disambiguate():
    q = "虚构设备设计标准2027版演示修订"
    payload = output()
    payload["standards"] = [
        dict(
            standard_name=value(q, "虚构设备设计标准"),
            edition=value(q, "2027"),
            revision=value(q, "演示修订"),
        )
    ]
    result = service(
        payload, catalog=FixtureCatalog([record(), record(edition="2027", suffix="next")])
    ).understand(QueryRequest(question=q))
    assert result.filters.document_ids == ["document-next"]


@pytest.mark.parametrize("fault", ["request_id", "scope", "identity", "fixture"])
def test_catalog_binding_and_trust(fault):
    class BadCatalog(FixtureCatalog):
        def lookup(self, request):
            result = super().lookup(request)
            if fault == "request_id":
                result.request_id = "other"
            elif fault == "scope":
                result.candidates[0].indexed_scopes = [
                    CatalogIndexScope(keyword_index="elsewhere", vector_collection="elsewhere")
                ]
            elif fault == "identity":
                result.candidates[0].document_id = None
            return result

    q = f"查询{CODE_A}"
    payload = output()
    payload["standards"] = [standard(q)]
    sut = service(payload, catalog=BadCatalog())
    if fault == "fixture":
        sut = QueryUnderstanding(
            llm=FixtureLLM(payload),
            catalog=BadCatalog(),
            config=sut.config.model_copy(update={"allow_test_catalog": False}),
        )
    with pytest.raises(UnderstandingError, match="catalog"):
        sut.understand(QueryRequest(question=q))


@pytest.mark.parametrize("fault", ["invented_code", "quote", "offset", "role", "mixed"])
def test_untrusted_source_evidence_is_rejected(fault):
    q = f"查询{CODE_A}"
    payload = output()
    candidate = standard(q)
    ev = candidate["standard_code"]["evidence"]
    if fault == "invented_code":
        candidate["standard_code"]["value"] = CODE_B
    elif fault == "quote":
        ev["quote"] = CODE_B
    elif fault == "offset":
        ev["start"] = 0
    elif fault == "role":
        ev.update(source="history_user", history_index=0)
    else:
        candidate["edition"] = value("2026", "2026", source="history_user", history_index=0)
    payload["standards"] = [candidate]
    with pytest.raises(UnderstandingError):
        service(payload).understand(
            QueryRequest(question=q, history=[dict(role="assistant", content="2026")])
        )


def test_omitted_current_standard_is_not_silently_ignored():
    with pytest.raises(UnderstandingError) as error:
        service().understand(QueryRequest(question=f"请查询{CODE_A}"))
    assert error.value.code == "invalid_evidence"


def test_history_cannot_override_current_scope():
    q = f"现在改查{CODE_A}"
    history = f"此前查{CODE_B}"
    old = dict(standard_code=value(history, CODE_B, source="history_user", history_index=0))
    payload = output()
    payload["standards"] = [old, standard(q)]
    catalog = FixtureCatalog()
    result = service(payload, catalog=catalog).understand(
        QueryRequest(question=q, history=[dict(role="user", content=history)])
    )
    assert result.filters.document_ids == ["document-a"]
    assert len(catalog.requests) == 1
    assert result.degraded
    assert any(item.status == "ignored" for item in result.decisions)


def test_history_only_scope_requires_clarification():
    h = f"此前查{CODE_A}"
    payload = output()
    payload["standards"] = [
        dict(standard_code=value(h, CODE_A, source="history_user", history_index=0))
    ]
    with pytest.raises(UnderstandingError) as error:
        service(payload).understand(
            QueryRequest(question="该规范的规定呢？", history=[dict(role="user", content=h)])
        )
    assert error.value.code == "ambiguous_scope"


def test_no_candidates_preserves_validated_original_filters():
    original = SearchFilters(
        document_ids=["document-a"],
        standard_codes=[CODE_A],
        editions=["2026"],
        clause_numbers=["1.2.3"],
        content_types=["table"],
        is_explanation=False,
        is_mandatory=None,
    )
    request = QueryRequest(question="检索要求", filters=original)
    result = service().understand(request)
    assert result.filters == original
    assert result.filters is not original
    assert result.filters.is_mandatory is None


def test_same_field_intersection_and_cross_field_and():
    q = f"查询{CODE_A}的公式"
    payload = output()
    payload.update(
        standards=[standard(q)], content_types=[dict(value="formula", evidence=evidence(q, "公式"))]
    )
    original = SearchFilters(
        document_ids=["document-a", "document-b"],
        content_types=["formula", "table"],
        is_explanation=False,
    )
    result = service(
        payload, catalog=FixtureCatalog([record(), record(CODE_B, "2025", "b")])
    ).understand(QueryRequest(question=q, filters=original))
    assert result.filters.document_ids == ["document-a"]
    assert result.filters.content_types == ["formula"]
    assert result.filters.is_explanation is False
    assert original.document_ids == ["document-a", "document-b"]


@pytest.mark.parametrize("field", ["document_ids", "content_types", "is_explanation", "editions"])
def test_conflicts_do_not_fall_back_to_empty_unrestricted_lists(field):
    q = f"查询{CODE_A}的公式和条文说明"
    payload = output()
    payload.update(
        standards=[standard(q)],
        content_types=[dict(value="formula", evidence=evidence(q, "公式"))],
        is_explanation=dict(value=True, evidence=evidence(q, "条文说明")),
    )
    filters = SearchFilters(
        **{
            field: {
                "document_ids": ["document-b"],
                "content_types": ["table"],
                "is_explanation": False,
                "editions": ["2027"],
            }[field]
        }
    )
    with pytest.raises(UnderstandingError) as error:
        service(
            payload, catalog=FixtureCatalog([record(), record(CODE_B, "2025", "b")])
        ).understand(QueryRequest(question=q, filters=filters))
    assert error.value.code == "scope_conflict"


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "extra",
        "unknown",
        "document_id",
        "bad_bool",
        "request_id",
        "model_id",
        "model_revision",
        "nan",
        "json",
    ],
)
def test_llm_output_binding_schema_and_budget(fault):
    payload = output()

    def bad_response(req):
        data = deepcopy(payload)
        if fault == "missing":
            data.pop("processing_intent")
        elif fault == "extra":
            data["reason"] = "extra"
        elif fault == "unknown":
            data["processing_intent"] = "unknown"
        elif fault == "document_id":
            data["standards"] = [dict(document_id="invented")]
        elif fault == "bad_bool":
            data["is_mandatory"] = dict(value="true", evidence=evidence("强制性条文", "强制性条文"))
        elif fault == "nan":
            data["score"] = float("nan")
        elif fault == "json":
            data = "not JSON object"
        kwargs = dict(
            request_id=req.request_id,
            model_id=req.config.model_id,
            model_revision=req.config.model_revision,
            data=data,
        )
        if fault in {"request_id", "model_id", "model_revision"}:
            kwargs[fault] = "wrong"
        return StructuredLLMResponse(**kwargs)

    llm = FixtureLLM(bad_response)
    with pytest.raises(UnderstandingError) as error:
        service(llm=llm).understand(QueryRequest(question="检索要求"))
    assert error.value.code == "invalid_output"
    assert len(llm.requests) == 2
    assert error.value.__cause__ is not None


@pytest.mark.parametrize(
    "first", [TimeoutError("timeout"), ConnectionError("connection"), output("unknown")]
)
def test_single_shared_retry_budget_and_recovery(first):
    llm = FixtureLLM(first, output())
    result = service(llm=llm).understand(QueryRequest(question="检索要求"))
    assert len(llm.requests) == len(result.attempts) == 2
    assert result.degraded
    assert result.attempts[-1].status == "success"
    assert llm.requests[0].request_id != llm.requests[1].request_id
    assert llm.requests[1].input["previous_error"]


def test_transport_and_schema_failures_cannot_stack_retry_budgets():
    llm = FixtureLLM(TimeoutError("timeout"), output("unknown"), output())
    with pytest.raises(UnderstandingError) as error:
        service(llm=llm).understand(QueryRequest(question="检索要求"))
    assert len(llm.requests) == 2
    assert error.value.code == "invalid_output"


@pytest.mark.parametrize(
    "failure",
    [TimeoutError("timeout"), ConnectionError("connection"), RuntimeError("provider failure")],
)
def test_model_failure_is_not_normal_result(failure):
    llm = FixtureLLM(failure)
    with pytest.raises(UnderstandingError) as error:
        service(llm=llm).understand(QueryRequest(question="检索要求"))
    assert error.value.code == "model_failure"
    assert error.value.__cause__ is failure
    assert len(llm.requests) == (2 if isinstance(failure, (TimeoutError, ConnectionError)) else 1)


@pytest.mark.parametrize(
    ("question", "history", "options"),
    [
        ("   ", [], {}),
        ("长" * 11, [], {"max_question_chars": 10}),
        ("提问", [dict(role="user", content="a")] * 2, {"max_history_turns": 1}),
        ("提问", [dict(role="user", content="abc")], {"max_history_chars": 2}),
    ],
)
def test_input_rejected_before_model_without_truncation(question, history, options):
    llm = FixtureLLM()
    with pytest.raises(UnderstandingError) as error:
        service(llm=llm, **options).understand(QueryRequest(question=question, history=history))
    assert error.value.code == "input_budget"
    assert llm.requests == []


def test_insufficient_context_does_not_default_to_acquisition():
    payload = output()
    payload["context_sufficient"] = False
    with pytest.raises(UnderstandingError) as error:
        service(payload).understand(QueryRequest(question="这个呢？"))
    assert error.value.code == "ambiguous_scope"


@pytest.mark.parametrize("field", ["is_mandatory", "is_explanation"])
def test_bool_filter_requires_explicit_semantics_not_just_any_quote(field):
    q = "结构应满足承载力要求，必须验算"
    payload = output()
    payload[field] = dict(value=True, evidence=evidence(q, "必须"))
    with pytest.raises(UnderstandingError) as error:
        service(payload).understand(QueryRequest(question=q))
    assert error.value.code == "invalid_evidence"


def test_scope_less_clause_is_not_claimed_verified():
    q = "查询第1.2.3条"
    payload = output()
    payload["clause_numbers"] = [value(q, "1.2.3")]
    with pytest.raises(UnderstandingError) as error:
        service(payload).understand(QueryRequest(question=q))
    assert error.value.code == "ambiguous_scope"


def test_no_sensitive_logging_and_no_mutation_across_calls(caplog):
    sut = service()
    first = sut.understand(QueryRequest(question="私密测试问题"))
    first.filters.clause_numbers.append("9.9.9")
    second = sut.understand(QueryRequest(question="私密测试问题"))
    assert second.filters.clause_numbers == []
    assert "私密测试问题" not in caplog.text


def test_caller_verified_document_disambiguates_standard_edition():
    q = f"查询{CODE_A}的要求"
    payload = output()
    payload["standards"] = [standard(q)]
    result = service(
        payload, catalog=FixtureCatalog([record(), record(edition="2027", suffix="next")])
    ).understand(QueryRequest(question=q, filters=SearchFilters(document_ids=["document-next"])))
    assert result.filters.document_ids == ["document-next"]
    assert result.filters.editions == ["2027"]


def test_rejected_partial_or_candidate_is_audited():
    q = "查询公式和表格"
    payload = output()
    payload["content_types"] = [
        dict(value="formula", evidence=evidence(q, "公式")),
        dict(value="table", evidence=evidence(q, "表格")),
    ]
    result = service(payload).understand(
        QueryRequest(question=q, filters=SearchFilters(content_types=["formula"]))
    )
    assert result.filters.content_types == ["formula"]
    assert [item.status for item in result.decisions] == ["adopted", "rejected"]
    assert result.degraded


@pytest.mark.parametrize("code", ["GB00003-2026", "DB11/T 00003-2026", "JGJ/T 00003-2026"])
def test_missed_explicit_standard_omission_guard(code):
    with pytest.raises(UnderstandingError) as error:
        service().understand(QueryRequest(question=f"查询{code}"))
    assert error.value.code == "invalid_evidence"


def test_catalog_snapshot_switch_is_rejected_and_audited():
    class SwitchingCatalog(FixtureCatalog):
        def lookup(self, request):
            match = super().lookup(request)
            if len(self.requests) > 1:
                match.snapshot_id = "snapshot-2"
            return match

    q = f"比较{CODE_A}与{CODE_B}"
    payload = output("exploratory")
    payload["standards"] = [standard(q), standard(q, CODE_B)]
    with pytest.raises(UnderstandingError) as error:
        service(
            payload, catalog=SwitchingCatalog([record(), record(CODE_B, "2025", "b")])
        ).understand(QueryRequest(question=q))
    assert error.value.code == "catalog_unavailable"
    assert len(error.value.catalog_matches) == 2
    assert all(item.status == "rejected" for item in error.value.decisions)


def test_catalog_connection_error_retains_cause():
    failure = ConnectionError("offline")

    class UnavailableCatalog:
        def lookup(self, request):
            raise failure

    q = f"查询{CODE_A}"
    payload = output()
    payload["standards"] = [standard(q)]
    with pytest.raises(UnderstandingError) as error:
        service(payload, catalog=UnavailableCatalog()).understand(QueryRequest(question=q))
    assert error.value.code == "catalog_unavailable"
    assert error.value.__cause__ is failure


def test_caller_standard_codes_and_editions_are_catalog_verified():
    catalog = FixtureCatalog([record(), record(CODE_B, "2025", "b")])
    result = service(catalog=catalog).understand(
        QueryRequest(
            question="比较这些规范",
            filters=SearchFilters(standard_codes=[CODE_A, CODE_B], editions=["2026", "2025"]),
        )
    )
    assert result.filters.document_ids == ["document-a", "document-b"]
    assert result.filters.editions == ["2026", "2025"]
    assert len(catalog.requests) == 4


@pytest.mark.parametrize("kind", ["filters", "catalog"])
def test_filter_and_catalog_work_budgets(kind):
    config = {"max_filter_values": 1} if kind == "filters" else {"max_catalog_lookups": 1}
    with pytest.raises(UnderstandingError) as error:
        service(
            catalog=FixtureCatalog([record(), record(CODE_B, "2025", "b")]), **config
        ).understand(
            QueryRequest(
                question="比较规范",
                filters=SearchFilters(document_ids=["document-a", "document-b"]),
            )
        )
    assert error.value.code == "input_budget"


@pytest.mark.parametrize("clause", ["1.2", "1.2.3-1", "free text"])
def test_invalid_clause_format_never_becomes_filter(clause):
    payload = output()
    payload["clause_numbers"] = [value(clause, clause)]
    with pytest.raises(UnderstandingError) as error:
        service(payload).understand(QueryRequest(question=clause))
    assert error.value.code == "invalid_evidence"


def test_explicit_false_flags_are_distinct_from_none():
    q = "查询正文中的非强制性条文"
    payload = output()
    payload.update(
        is_explanation=dict(value=False, evidence=evidence(q, "正文")),
        is_mandatory=dict(value=False, evidence=evidence(q, "非强制性条文")),
    )
    result = service(payload).understand(QueryRequest(question=q))
    assert result.filters.is_explanation is False
    assert result.filters.is_mandatory is False


def test_negated_label_is_not_positive_evidence():
    q = "不要强制性条文"
    payload = output()
    payload["is_mandatory"] = dict(value=True, evidence=evidence(q, "强制性条文"))
    with pytest.raises(UnderstandingError) as error:
        service(payload).understand(QueryRequest(question=q))
    assert error.value.code == "invalid_evidence"


def test_history_role_trace_and_typed_result_roundtrip():
    from engineering_rag.contracts.common import TraceContext
    from engineering_rag.modules.query.internal.models import UnderstandingResult

    request = QueryRequest(
        question="查询要求",
        history=[dict(role="user", content="此前问题")],
        trace=TraceContext(trace_id="trace-fixture"),
    )
    llm = FixtureLLM(output())
    result = service(llm=llm).understand(request)
    assert llm.requests[0].input["history"] == [dict(role="user", content="此前问题")]
    assert llm.requests[0].trace == request.trace
    assert UnderstandingResult.model_validate_json(result.model_dump_json()) == result


def test_known_usage_and_single_attempt_configuration():
    from engineering_rag.contracts.llm import LLMTokenUsage

    def response(request):
        return StructuredLLMResponse(
            request_id=request.request_id,
            model_id=request.config.model_id,
            model_revision=request.config.model_revision,
            data=output(),
            usage=LLMTokenUsage(input_tokens=4, output_tokens=6, total_tokens=10),
        )

    result = service(llm=FixtureLLM(response)).understand(QueryRequest(question="要求"))
    assert result.attempts[0].usage.total_tokens == 10
    llm = FixtureLLM(output("unknown"), output())
    with pytest.raises(UnderstandingError):
        service(llm=llm, max_attempts=1).understand(QueryRequest(question="要求"))
    assert len(llm.requests) == 1


@pytest.mark.parametrize("question", ["HRB400钢筋的强度是多少", "C30混凝土有什么要求"])
def test_engineering_material_grade_is_not_a_standard_omission(question):
    assert service().understand(QueryRequest(question=question)).filters.document_ids == []


def test_negated_content_type_is_not_a_positive_filter():
    q = "不要公式，只查要求"
    payload = output()
    payload["content_types"] = [dict(value="formula", evidence=evidence(q, "公式"))]
    with pytest.raises(UnderstandingError) as error:
        service(payload).understand(QueryRequest(question=q))
    assert error.value.code == "invalid_evidence"


@pytest.mark.parametrize("attempts", [0, 3, True, 2.0])
def test_attempt_budget_requires_strict_integer_between_one_and_two(attempts):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        service(max_attempts=attempts)
