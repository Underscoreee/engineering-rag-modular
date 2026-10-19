"""Read-only comparison guards: no widening scopes or changing retrieval algorithms."""

from __future__ import annotations

from time import monotonic

from engineering_rag.contracts.protocols import HybridRetrievalService
from engineering_rag.contracts.queries import RetrievalPlan
from engineering_rag.contracts.retrieval import HybridSearchRequest, RetrievalResult, SearchFilters

from .run_models import EvaluationSafetyError, RunConfig, Variant


def equal_filters(first: SearchFilters, second: SearchFilters) -> bool:
    return all(
        set(left) == set(right) if isinstance(left, list) else left == right
        for field in SearchFilters.model_fields
        for left, right in [(getattr(first, field), getattr(second, field))]
    )


def raw_request(question: str, filters: SearchFilters, config: RunConfig) -> HybridSearchRequest:
    if not config.keyword_index or not config.vector_collection:
        raise EvaluationSafetyError("not_configured", "both backend index names must be configured")
    return HybridSearchRequest.model_validate(
        {
            "keyword": {
                "query": question,
                "index_name": config.keyword_index,
                "filters": filters.model_dump(mode="json"),
                "top_k": config.candidate_k,
            },
            "vector": {
                "query": question,
                "index_name": config.vector_collection,
                "filters": filters.model_dump(mode="json"),
                "top_k": config.candidate_k,
                "embedding_model_id": config.embedding_model_id,
            },
            "candidate_k": config.candidate_k,
            "top_k": max(config.ks),
            "fusion_strategy": config.fusion_strategy,
            "keyword_weight": config.keyword_weight,
            "vector_weight": config.vector_weight,
        }
    )


class RetrievalGuard:
    def __init__(
        self,
        backend: HybridRetrievalService,
        expected_filters: SearchFilters,
        config: RunConfig,
        *,
        must_reject: bool = False,
    ) -> None:
        self.backend, self.expected_filters, self.config = backend, expected_filters, config
        self.must_reject = must_reject
        self.requests: list[HybridSearchRequest] = []
        self.elapsed_seconds = 0.0
        self.backend_calls = 0

    def search(self, request: HybridSearchRequest) -> list[RetrievalResult]:
        validated = HybridSearchRequest.model_validate_json(request.model_dump_json())
        self.requests.append(validated.model_copy(deep=True))
        if len(self.requests) != 1:
            raise EvaluationSafetyError(
                "repeated_search", "only one Hybrid call is allowed per variant/query"
            )
        if self.must_reject:
            raise EvaluationSafetyError(
                "unexpected_retrieval", "expected rejection reached retrieval"
            )
        if not equal_filters(validated.keyword.filters, self.expected_filters) or not equal_filters(
            validated.vector.filters, self.expected_filters
        ):
            raise EvaluationSafetyError(
                "scope_mismatch", "predicted filters differ from the common human scope"
            )
        reference = raw_request("parameter comparison", self.expected_filters, self.config)
        first, second = validated.model_dump(mode="json"), reference.model_dump(mode="json")
        for branch in ("keyword", "vector"):
            first[branch].pop("query")
            second[branch].pop("query")
        if first != second:
            raise EvaluationSafetyError(
                "retrieval_parameter_mismatch", "ablation changed retrieval budgets or routing"
            )
        started = monotonic()
        self.backend_calls += 1
        try:
            return self.backend.search(validated.model_copy(deep=True))
        finally:
            self.elapsed_seconds += monotonic() - started


def check_variant(plan: RetrievalPlan, variant: Variant, question: str) -> None:
    """No silent fallback may masquerade as a successful enhancement-only ablation."""
    request = plan.hybrid_request
    if request is None or not plan.rewritten_queries:
        raise EvaluationSafetyError(
            "invalid_plan", "actual Query plan lacks a primary query/request"
        )
    primary, expanded = plan.rewritten_queries[0], plan.rewritten_queries[1:]
    hypothesis = plan.hypothetical_document
    if plan.original_question != question:
        raise EvaluationSafetyError("invalid_plan", "plan belongs to another original question")
    if hypothesis and hypothesis == request.keyword.query:
        raise EvaluationSafetyError("hyde_keyword_leak", "HyDE entered the keyword query")
    if plan.processing_intent == "acquisition":
        if expanded or hypothesis or request.vector.query != primary:
            raise EvaluationSafetyError(
                "acquisition_enhancement", "acquisition did not skip enhancement"
            )
        return
    if variant == "rewrite" and (expanded or hypothesis or request.vector.query != primary):
        raise EvaluationSafetyError("wrong_variant", "Rewrite-only variant used enhancement")
    if variant == "rewrite_expansion" and (
        hypothesis or not expanded or request.vector.query not in expanded
    ):
        raise EvaluationSafetyError(
            "expansion_unavailable", "Expansion ablation was not actually used"
        )
    if variant == "rewrite_hyde" and (
        expanded or not hypothesis or request.vector.query != hypothesis
    ):
        raise EvaluationSafetyError("hyde_unavailable", "HyDE ablation was not actually used")
