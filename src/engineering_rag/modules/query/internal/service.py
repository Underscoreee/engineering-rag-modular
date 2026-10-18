"""Query orchestration; external retrieval is injected exclusively via the public Protocol."""

import logging
import math
from collections.abc import Callable
from time import monotonic
from typing import TypeVar
from uuid import uuid4

from engineering_rag.contracts.protocols import HybridRetrievalService
from engineering_rag.contracts.queries import QueryRequest, QueryResult, RetrievalPlan
from engineering_rag.contracts.retrieval import RetrievalSource

from .enhancement_models import QueryEnhancementResult
from .models import UnderstandingResult
from .planning import build_plan
from .planning_models import (
    EnhancementStage,
    PlanningConfig,
    QueryPlanningError,
    RewriteStage,
    UnderstandingStage,
)
from .rewrite_models import RewriteResult

LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


class DefaultQueryService:
    def __init__(
        self,
        *,
        understanding: UnderstandingStage,
        rewrite: RewriteStage,
        enhancement: EnhancementStage,
        hybrid_service: HybridRetrievalService,
        config: PlanningConfig,
    ) -> None:
        self._understanding = understanding
        self._rewrite = rewrite
        self._enhancement = enhancement
        self._hybrid_service = hybrid_service
        self._config = PlanningConfig.model_validate_json(config.model_dump_json())

    def plan(self, request: QueryRequest) -> RetrievalPlan:
        started = monotonic()
        request = QueryRequest.model_validate_json(request.model_dump_json())
        if request.options.mode != "hybrid":
            raise QueryPlanningError("unsupported_mode", "this implementation only supports hybrid")
        if request.options.top_k > self._config.candidate_k:
            raise QueryPlanningError("invalid_parameters", "top_k exceeds configured candidate_k")
        run_id = uuid4().hex
        understanding = self._timed(
            request,
            run_id,
            "query_understanding",
            lambda: UnderstandingResult.model_validate_json(
                self._understanding.understand(request.model_copy(deep=True)).model_dump_json()
            ),
        )
        if understanding.scope != self._config.scope:
            raise QueryPlanningError("invalid_upstream", "Understanding used another index scope")
        rewrite = self._timed(
            request,
            run_id,
            "query_rewrite",
            lambda: RewriteResult.model_validate_json(
                self._rewrite.rewrite(
                    request.model_copy(deep=True), understanding.model_copy(deep=True)
                ).model_dump_json()
            ),
        )
        enhancement = self._timed(
            request,
            run_id,
            "query_enhancement",
            lambda: QueryEnhancementResult.model_validate_json(
                self._enhancement.enhance(
                    request.model_copy(deep=True),
                    understanding.model_copy(deep=True),
                    rewrite.model_copy(deep=True),
                ).model_dump_json()
            ),
        )
        plan, strategy = build_plan(request, understanding, rewrite, enhancement, self._config)
        LOGGER.info(
            "query plan completed",
            extra={
                **self._context(request, run_id),
                "stage": "query_planning",
                "processing_intent": understanding.processing_intent.value,
                "expansion_status": enhancement.expansion_status.value,
                "hyde_status": enhancement.hyde_status.value,
                "degraded": enhancement.degraded,
                "vector_strategy": strategy,
                "candidate_k": self._config.candidate_k,
                "top_k": request.options.top_k,
                "elapsed_seconds": monotonic() - started,
            },
        )
        return plan

    def execute(self, request: QueryRequest) -> QueryResult:
        started = monotonic()
        run_id = uuid4().hex
        snapshot = QueryRequest.model_validate_json(request.model_dump_json())
        plan = self.plan(snapshot)
        hybrid_request = plan.hybrid_request
        if hybrid_request is None:
            raise QueryPlanningError("invalid_upstream", "hybrid plan has no retrieval request")
        submitted = hybrid_request.model_copy(deep=True)
        evidence = self._timed(
            snapshot,
            run_id,
            "hybrid_search",
            lambda: self._hybrid_service.search(submitted),
        )
        if submitted != hybrid_request:
            raise QueryPlanningError("invalid_result", "injected Hybrid mutated its request")
        # Revalidate nested models (including objects modified after construction), without
        # changing scores, ranking, source identity, content or any provenance fields.
        try:
            result = QueryResult.model_validate(
                QueryResult(plan=plan, evidence=evidence).model_dump(mode="python")
            )
        except (ValueError, TypeError) as exc:
            raise QueryPlanningError("invalid_result", "invalid Hybrid result contract") from exc
        if any(
            not math.isfinite(item.score) or item.retrieval_source != RetrievalSource.HYBRID
            for item in result.evidence
        ):
            raise QueryPlanningError("invalid_result", "invalid Hybrid score or retrieval source")
        LOGGER.info(
            "query execution completed",
            extra={
                **self._context(snapshot, run_id),
                "stage": "query_execution",
                "result_count": len(result.evidence),
                "elapsed_seconds": monotonic() - started,
            },
        )
        return result

    @staticmethod
    def _context(request: QueryRequest, run_id: str | None) -> dict[str, str | None]:
        return {
            "request_id": run_id,
            "trace_id": request.trace.trace_id if request.trace else None,
            "task_id": request.trace.task_id if request.trace else None,
        }

    def _timed(
        self, request: QueryRequest, run_id: str, stage: str, operation: Callable[[], T]
    ) -> T:
        started = monotonic()
        status = "failed"
        try:
            result = operation()
            status = "completed"
            return result
        finally:
            LOGGER.info(
                "query stage completed",
                extra={
                    **self._context(request, run_id),
                    "stage": stage,
                    "status": status,
                    "elapsed_seconds": monotonic() - started,
                },
            )
