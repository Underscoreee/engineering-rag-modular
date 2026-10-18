"""Pure, deterministic projection of validated stage artifacts to the existing plan."""

from typing import Literal

from engineering_rag.contracts.queries import ProcessingIntent, QueryRequest, RetrievalPlan
from engineering_rag.contracts.retrieval import (
    HybridSearchRequest,
    KeywordSearchRequest,
    VectorSearchRequest,
)

from .enhancement_models import QueryEnhancementResult, StageStatus
from .models import UnderstandingResult
from .planning_models import PlanningConfig, QueryPlanningError
from .rewrite_models import RewriteResult
from .rewrite_protection import validate_understanding_scope

VectorStrategy = Literal["hyde", "first_expansion", "rewritten_query"]


def build_keyword_text(rewrite: RewriteResult, config: PlanningConfig) -> str:
    """Keep the main query verbatim; append only whole reviewed terms within budgets."""
    primary = rewrite.rewritten_query
    if not primary.strip() or len(primary) > config.max_keyword_chars:
        raise QueryPlanningError("invalid_parameters", "main keyword query exceeds text budget")
    parts = [primary]
    seen: set[str] = set()
    for candidate in rewrite.keyword_synonyms:
        term = candidate.strip()
        if not term or term in seen or term in primary:
            continue
        seen.add(term)
        if len(parts) - 1 >= config.max_keyword_synonyms:
            break
        if len(term) > config.max_synonym_chars:
            continue
        if len("\n".join([*parts, term])) <= config.max_keyword_chars:
            parts.append(term)
    return "\n".join(parts)


def select_vector_text(
    enhancement: QueryEnhancementResult, config: PlanningConfig
) -> tuple[str, VectorStrategy]:
    """One vector request: validated HyDE, first fitting expansion, then intact primary."""
    primary = enhancement.rewritten_query
    if not primary.strip() or len(primary) > config.max_vector_chars:
        raise QueryPlanningError("invalid_parameters", "main vector query exceeds text budget")
    if enhancement.processing_intent == ProcessingIntent.EXPLORATORY:
        hypothesis = enhancement.hypothetical_document
        if (
            enhancement.hyde_status == StageStatus.COMPLETED
            and hypothesis
            and len(hypothesis) <= config.max_vector_chars
        ):
            return hypothesis, "hyde"
        if enhancement.expansion_status == StageStatus.COMPLETED:
            for expanded in dict.fromkeys(enhancement.expanded_queries):
                if (
                    expanded.strip()
                    and expanded != primary
                    and len(expanded) <= config.max_vector_chars
                ):
                    return expanded, "first_expansion"
    return primary, "rewritten_query"


def build_plan(
    request: QueryRequest,
    understanding: UnderstandingResult,
    rewrite: RewriteResult,
    enhancement: QueryEnhancementResult,
    config: PlanningConfig,
) -> tuple[RetrievalPlan, VectorStrategy]:
    """Check artifact correspondence, without re-running candidate extraction or generation."""
    try:
        validate_understanding_scope(request, understanding)
        if understanding.scope != config.scope:
            raise ValueError("catalog and retrieval index pairs differ")
        if not rewrite.attempts or rewrite.attempts[-1].status != "success":
            raise ValueError("successful Rewrite result required")
        for result in (rewrite, enhancement):
            if (
                result.original_question != request.question
                or result.processing_intent != understanding.processing_intent
                or result.filters != understanding.filters
                or result.trace != request.trace
            ):
                raise ValueError("upstream request, intent, filters or trace differ")
        if (
            enhancement.rewritten_query != rewrite.rewritten_query
            or enhancement.keyword_synonyms != rewrite.keyword_synonyms
        ):
            raise ValueError("Enhancement changed the authoritative Rewrite result")
    except ValueError as exc:
        raise QueryPlanningError("invalid_upstream", "stage artifacts do not correspond") from exc

    keyword = build_keyword_text(rewrite, config)
    vector, strategy = select_vector_text(enhancement, config)
    filters = understanding.filters
    hybrid = HybridSearchRequest(
        keyword=KeywordSearchRequest(
            query=keyword,
            filters=filters.model_copy(deep=True),
            top_k=config.candidate_k,
            index_name=config.scope.keyword_index,
        ),
        vector=VectorSearchRequest(
            query=vector,
            filters=filters.model_copy(deep=True),
            top_k=config.candidate_k,
            index_name=config.scope.vector_collection,
            embedding_model_id=config.embedding_model_id,
        ),
        fusion_strategy=config.fusion_strategy,
        keyword_weight=config.keyword_weight,
        vector_weight=config.vector_weight,
        candidate_k=config.candidate_k,
        top_k=request.options.top_k,
    )
    return RetrievalPlan(
        original_question=request.question,
        rewritten_queries=list(
            dict.fromkeys([rewrite.rewritten_query, *enhancement.expanded_queries])
        ),
        hypothetical_document=enhancement.hypothetical_document,
        intent=understanding.semantic_intent,
        processing_intent=understanding.processing_intent,
        retrieval_mode="hybrid",
        hybrid_request=hybrid,
    ), strategy
