"""Offline planning/service tests: stage doubles are NOT real model/backend evaluation."""

from dataclasses import dataclass, field
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.catalog import CatalogIndexScope
from engineering_rag.contracts.common import TraceContext
from engineering_rag.contracts.documents import StandardMetadata
from engineering_rag.contracts.queries import QueryOptions, QueryRequest, QueryResult, RetrievalPlan
from engineering_rag.contracts.retrieval import (
    FusionStrategy,
    HybridSearchRequest,
    RetrievalResult,
    RetrievalSource,
    SearchFilters,
)
from engineering_rag.modules.query.api import (
    DefaultQueryService,
    PlanningConfig,
    QueryPlanningError,
)
from engineering_rag.modules.query.internal.enhancement_models import QueryEnhancementResult
from engineering_rag.modules.query.internal.errors import UnderstandingError
from engineering_rag.modules.query.internal.models import UnderstandingResult
from engineering_rag.modules.query.internal.planning import build_keyword_text, select_vector_text
from engineering_rag.modules.query.internal.rewrite_models import RewriteError, RewriteResult

from .test_enhancement import QUESTION, FakeEnhancementLLM, enhancer, expanded, hypothesis
from .test_rewrite import RewriteLLM, reply, rewriter
from .test_understanding import CODE_A, SCOPE, output, service


def retrieval_result(
    chunk_id: str, source: RetrievalSource, score: float, rank: int = 1
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        logical_chunk_id=f"logical-{chunk_id}",
        document_id="document-a",
        content=f"虚构工程检索证据{chunk_id}",
        standard=StandardMetadata(
            standard_name="虚构设备设计标准", standard_code=CODE_A, edition="2026"
        ),
        clause_id=f"clause-{chunk_id}",
        clause_number="1.2.3",
        page_start=3,
        page_end=4,
        score=score,
        rank=rank,
        retrieval_source=source,
        score_type="rrf" if source == RetrievalSource.HYBRID else "test-score",
        index_name="fictional-index",
    )


@dataclass
class FakeUnderstanding:
    result: UnderstandingResult
    events: list[str]
    calls: int = 0
    error: Exception | None = None

    def understand(self, request: QueryRequest) -> UnderstandingResult:
        self.calls += 1
        self.events.append("understanding")
        if self.error:
            raise self.error
        return self.result


@dataclass
class FakeRewrite:
    result: RewriteResult
    events: list[str]
    calls: int = 0
    error: Exception | None = None

    def rewrite(self, request: QueryRequest, understanding: UnderstandingResult) -> RewriteResult:
        self.calls += 1
        self.events.append("rewrite")
        if self.error:
            raise self.error
        return self.result


@dataclass
class FakeEnhancement:
    result: QueryEnhancementResult
    events: list[str]
    calls: int = 0

    def enhance(
        self, request: QueryRequest, understanding: UnderstandingResult, rewrite: RewriteResult
    ) -> QueryEnhancementResult:
        self.calls += 1
        self.events.append("enhancement")
        return self.result


@dataclass
class FakeHybrid:
    results: list[RetrievalResult] = field(default_factory=list)
    requests: list[HybridSearchRequest] = field(default_factory=list)
    error: Exception | None = None

    def search(self, request: HybridSearchRequest) -> list[RetrievalResult]:
        self.requests.append(request.model_copy(deep=True))
        if self.error:
            raise self.error
        return self.results


def harness(
    intent: str = "exploratory",
    *,
    expansions: list[str] | Exception | None = None,
    hyde: str | Exception | None = None,
    filters: SearchFilters | None = None,
    **settings: object,
):
    request = QueryRequest(
        question=QUESTION,
        filters=filters or SearchFilters(),
        trace=TraceContext(trace_id="planning-trace", task_id="planning-task"),
    )
    understanding = service(output(intent)).understand(request)
    rewrite = rewriter(RewriteLLM(reply(QUESTION))).rewrite(request, understanding)
    enhancement = enhancer(
        FakeEnhancementLLM(
            expansion=expansions
            if isinstance(expansions, Exception)
            else {"expanded_queries": expansions if expansions is not None else [expanded()]},
            hyde=hyde
            if isinstance(hyde, Exception)
            else {"hypothetical_document": hyde if hyde is not None else hypothesis()},
        )
    ).enhance(request, understanding, rewrite)
    events: list[str] = []
    und, rw, en = (
        FakeUnderstanding(understanding, events),
        FakeRewrite(rewrite, events),
        FakeEnhancement(enhancement, events),
    )
    hybrid = FakeHybrid()
    query = DefaultQueryService(
        understanding=und,
        rewrite=rw,
        enhancement=en,
        hybrid_service=hybrid,
        config=PlanningConfig(scope=SCOPE, **settings),
    )
    return query, request, und, rw, en, hybrid


@pytest.mark.parametrize("intent", ["acquisition", "exploratory"])
def test_plan_order_roundtrip_and_no_retrieval(intent):
    query, request, und, rw, en, hybrid = harness(intent)
    before = request.model_dump_json()
    plan = query.plan(request)
    assert und.events == ["understanding", "rewrite", "enhancement"]
    assert und.calls == rw.calls == en.calls == 1
    assert not hybrid.requests
    assert plan.processing_intent == intent
    assert plan.intent == "unknown"
    assert plan.original_question == QUESTION
    assert plan.rewritten_queries[0] == QUESTION
    assert plan.hybrid_request.keyword.query == QUESTION
    assert plan.hybrid_request.vector.query == (
        QUESTION if intent == "acquisition" else hypothesis()
    )
    assert request.model_dump_json() == before
    assert RetrievalPlan.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize(
    ("expansions", "hyde", "expected"),
    [
        ([expanded(), expanded(index=1)], hypothesis(), hypothesis()),
        ([expanded(), expanded(index=1)], TimeoutError(), expanded()),
        (TimeoutError(), TimeoutError(), QUESTION),
        ([], TimeoutError(), QUESTION),
        (TimeoutError(), hypothesis(), hypothesis()),
    ],
)
def test_vector_priority_without_fanout_or_keyword_contamination(expansions, hyde, expected):
    query, request, _, rw, en, hybrid = harness(expansions=expansions, hyde=hyde)
    plan = query.plan(request)
    assert plan.hybrid_request.vector.query == expected
    assert plan.hybrid_request.keyword.query == rw.result.rewritten_query == QUESTION
    assert rw.result.rewritten_query == en.result.rewritten_query
    assert not hybrid.requests
    assert plan.hypothetical_document == en.result.hypothetical_document


def test_vector_budget_selects_first_fitting_whole_expansion_then_primary():
    query, request, _, _, en, _ = harness(
        expansions=[expanded(), expanded(index=1)], max_vector_chars=len(expanded(index=1))
    )
    plan = query.plan(request)
    assert len(expanded()) > len(expanded(index=1))
    assert plan.hybrid_request.vector.query == expanded(index=1)
    text, strategy = select_vector_text(
        en.result, PlanningConfig(scope=SCOPE, max_vector_chars=len(QUESTION))
    )
    assert (text, strategy) == (QUESTION, "rewritten_query")


def test_keyword_builder_deduplicates_and_bounds_only_verified_synonyms():
    _, _, _, rw, _, _ = harness()
    rewrite = rw.result.model_copy(
        update={"keyword_synonyms": ["", "规范", "审核词甲", "审核词甲", "审核词乙"]}
    )
    assert (
        build_keyword_text(rewrite, PlanningConfig(scope=SCOPE))
        == QUESTION + "\n审核词甲\n审核词乙"
    )
    assert (
        build_keyword_text(rewrite, PlanningConfig(scope=SCOPE, max_keyword_synonyms=1))
        == QUESTION + "\n审核词甲"
    )
    assert (
        build_keyword_text(rewrite, PlanningConfig(scope=SCOPE, max_keyword_chars=len(QUESTION)))
        == QUESTION
    )
    assert build_keyword_text(rewrite, PlanningConfig(scope=SCOPE, max_synonym_chars=1)) == QUESTION


@pytest.mark.parametrize("field", ["max_keyword_chars", "max_vector_chars"])
def test_never_truncate_primary_for_a_text_budget(field):
    query, request, *_ = harness(**{field: len(QUESTION) - 1})
    with pytest.raises(QueryPlanningError, match="invalid_parameters"):
        query.plan(request)


def test_all_filters_copied_to_both_routes_with_none_and_false_preserved():
    filters = SearchFilters(
        document_ids=["document-a"],
        standard_codes=[CODE_A],
        editions=["2026"],
        clause_numbers=["1.2.3", "1.2.4"],
        content_types=["formula", "table"],
        is_explanation=False,
        is_mandatory=None,
    )
    query, request, und, *_ = harness(filters=filters)
    plan = query.plan(request)
    keyword, vector = plan.hybrid_request.keyword, plan.hybrid_request.vector
    assert keyword.filters == vector.filters == und.result.filters == request.filters
    assert keyword.filters is not vector.filters
    assert keyword.filters is not request.filters
    keyword.filters.document_ids.append("only-modify-returned-copy")
    assert vector.filters.document_ids == request.filters.document_ids == ["document-a"]


@pytest.mark.parametrize("top_k", [1, 10, 50])
def test_candidate_final_k_indexes_model_and_weighted_parameters(top_k):
    query, request, *_ = harness(
        fusion_strategy=FusionStrategy.WEIGHTED_NORMALIZED,
        keyword_weight=0.7,
        vector_weight=0.3,
        embedding_model_id="deployed-model",
    )
    request.options.top_k = top_k
    plan = query.plan(request)
    hybrid = plan.hybrid_request
    assert hybrid.top_k == top_k
    assert hybrid.candidate_k == hybrid.keyword.top_k == hybrid.vector.top_k == 50
    assert hybrid.keyword.index_name == SCOPE.keyword_index
    assert hybrid.vector.index_name == SCOPE.vector_collection
    assert hybrid.vector.embedding_model_id == "deployed-model"
    assert hybrid.fusion_strategy == "weighted_normalized"
    assert (hybrid.keyword_weight, hybrid.vector_weight) == (0.7, 0.3)
    assert hybrid.keyword.field_weights == {}


@pytest.mark.parametrize("mode", ["keyword", "vector"])
def test_unsupported_mode_fails_before_upstream_calls(mode):
    query, request, und, rw, en, hybrid = harness()
    request.options = QueryOptions(mode=mode)
    with pytest.raises(QueryPlanningError, match="unsupported_mode"):
        query.execute(request)
    assert not und.events and not hybrid.requests
    assert und.calls == rw.calls == en.calls == 0


def test_final_k_over_candidate_budget_fails_before_model_calls():
    query, request, und, *_ = harness()
    request.options.top_k = 51
    with pytest.raises(QueryPlanningError, match="invalid_parameters"):
        query.plan(request)
    assert und.calls == 0


@pytest.mark.parametrize(
    "settings",
    [
        {"candidate_k": 0},
        {"candidate_k": 65},
        {"keyword_candidate_limit": 49},
        {"candidate_k": True},
        {"max_keyword_chars": 0},
        {"keyword_weight": 0.9},
        {"keyword_weight": float("nan")},
        {"vector_weight": float("inf")},
        {"fusion_strategy": "imaginary"},
        {"fusion_strategy": FusionStrategy.WEIGHTED_NORMALIZED, "vector_weight": 0.2},
    ],
)
def test_invalid_deployment_config_rejected(settings):
    with pytest.raises(ValidationError):
        PlanningConfig(scope=SCOPE, **settings)


@pytest.mark.parametrize("target", ["understanding", "rewrite", "enhancement"])
def test_inconsistent_scope_or_stage_correspondence_is_not_optional_degradation(target):
    query, request, und, rw, en, hybrid = harness()
    if target == "understanding":
        und.result.scope = CatalogIndexScope(keyword_index="elsewhere", vector_collection="other")
    elif target == "rewrite":
        rw.result.filters.is_explanation = True
    else:
        en.result.keyword_synonyms = ["untrusted replacement"]
    with pytest.raises(QueryPlanningError, match="invalid_upstream"):
        query.execute(request)
    assert not hybrid.requests


def test_caller_scope_cannot_be_cleared_to_mean_unrestricted():
    query, request, und, rw, en, hybrid = harness(
        filters=SearchFilters(document_ids=["document-a"])
    )
    for artifact in (und.result, rw.result, en.result):
        artifact.filters.document_ids.clear()
    with pytest.raises(QueryPlanningError, match="invalid_upstream"):
        query.execute(request)
    assert not hybrid.requests


def test_execute_plans_once_retrieves_once_and_preserves_actual_evidence():
    query, request, und, rw, en, hybrid = harness()
    hybrid.results = [
        retrieval_result("second", RetrievalSource.HYBRID, 0.8, 1),
        retrieval_result("first", RetrievalSource.HYBRID, 0.7, 2),
    ]
    before = request.model_dump_json()
    with patch.object(query, "plan", wraps=query.plan) as planned:
        result = query.execute(request)
    assert planned.call_count == len(hybrid.requests) == 1
    assert und.calls == rw.calls == en.calls == 1
    assert result.plan.hybrid_request == hybrid.requests[0]
    assert result.evidence == hybrid.results
    assert request.model_dump_json() == before
    assert QueryResult.model_validate_json(result.model_dump_json()) == result
    assert all(item.content != result.plan.hypothetical_document for item in result.evidence)


def test_empty_search_and_degraded_enhancement_are_not_backend_failure():
    query, request, *_, hybrid = harness(expansions=TimeoutError(), hyde=ConnectionError())
    result = query.execute(request)
    assert result.evidence == []
    assert len(hybrid.requests) == 1
    assert result.plan.hybrid_request.vector.query == QUESTION


@pytest.mark.parametrize("stage", ["understanding", "rewrite", "scope", "hybrid"])
def test_required_errors_propagate_without_fake_empty_success(stage):
    query, request, und, rw, en, hybrid = harness()
    if stage in {"understanding", "scope"}:
        error = UnderstandingError(
            "model_failure" if stage == "understanding" else "unmatched_scope", "fixture failure"
        )
        und.error = error
    elif stage == "rewrite":
        error = RewriteError("unsafe_rewrite", "fixture failure")
        rw.error = error
    else:
        error = ConnectionError("fixture backend down")
        hybrid.error = error
    with pytest.raises(type(error)) as caught:
        query.execute(request)
    assert caught.value is error
    assert len(hybrid.requests) == (1 if stage == "hybrid" else 0)
    assert und.calls == 1
    assert rw.calls == (0 if stage in {"understanding", "scope"} else 1)
    assert en.calls == (1 if stage == "hybrid" else 0)


def test_logs_expose_strategy_counts_trace_and_latency_without_query_text(caplog):
    query, request, *_ = harness()
    with caplog.at_level("INFO"):
        query.execute(request)
    plan_log = next(item for item in caplog.records if item.message == "query plan completed")
    assert plan_log.vector_strategy == "hyde"
    assert plan_log.trace_id == "planning-trace" and plan_log.task_id == "planning-task"
    assert plan_log.candidate_k == 50 and plan_log.top_k == 10
    assert plan_log.expansion_status == plan_log.hyde_status == "completed"
    stages = [item for item in caplog.records if item.message == "query stage completed"]
    assert len(stages) == 4
    assert all(item.elapsed_seconds >= 0 for item in stages)
    assert QUESTION not in str([item.__dict__ for item in caplog.records])


def test_fixed_stage_outputs_produce_repeatable_plans_without_shared_return_state():
    query, request, *_ = harness()
    first, second = query.plan(request), query.plan(request)
    assert first.model_dump_json() == second.model_dump_json()
    first.hybrid_request.keyword.filters.document_ids.append("local-change")
    assert second.hybrid_request.keyword.filters.document_ids == []


@pytest.mark.parametrize("score", [float("nan"), float("inf")])
def test_invalid_hybrid_results_are_not_returned_as_evidence(score):
    query, request, *_, hybrid = harness()
    hybrid.results = [retrieval_result("invalid", RetrievalSource.HYBRID, score)]
    with pytest.raises(QueryPlanningError, match="invalid_result"):
        query.execute(request)


def test_mutating_injected_hybrid_cannot_change_returned_plan_silently():
    query, request, *_ = harness()

    def mutate(submitted):
        submitted.vector.query = "another query"
        return []

    with (
        patch.object(query._hybrid_service, "search", side_effect=mutate),
        pytest.raises(QueryPlanningError, match="invalid_result"),
    ):
        query.execute(request)
