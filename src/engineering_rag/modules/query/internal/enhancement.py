"""Query Enhancement only: no upstream reruns, query composition, embedding or retrieval."""

import hashlib
import json
import logging
from uuid import uuid4

from engineering_rag.contracts.protocols import StructuredLLMClient
from engineering_rag.contracts.queries import ProcessingIntent, QueryRequest
from engineering_rag.contracts.retrieval import SearchFilters

from .enhancement_models import (
    EnhancementConfig,
    EnhancementInput,
    EnhancementInputError,
    QueryEnhancementResult,
    Stage,
    StageStatus,
)
from .enhancement_prompts import ENHANCEMENT_POLICY_VERSION
from .enhancement_runner import StageOutcome, run_stage, stage_report
from .enhancement_validation import validate_context_policy
from .models import UnderstandingResult
from .rewrite_models import RewriteResult

LOGGER = logging.getLogger(__name__)


class QueryEnhancement:
    def __init__(self, *, llm: StructuredLLMClient, config: EnhancementConfig) -> None:
        self._llm = llm
        self._config = EnhancementConfig.model_validate_json(config.model_dump_json())
        validate_context_policy(self._config.related_contexts)
        self._fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "policy_version": ENHANCEMENT_POLICY_VERSION,
                    "config": self._config.model_dump(mode="json"),
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    def enhance(
        self,
        request: QueryRequest,
        understanding: UnderstandingResult,
        rewrite: RewriteResult,
    ) -> QueryEnhancementResult:
        inputs = self._inputs(request, understanding, rewrite)
        run_id = uuid4().hex
        outcomes: list[StageOutcome] = []
        corrections = self._config.max_corrections
        for stage, enabled in (
            ("query_expansion", self._config.enable_expansion),
            ("query_hyde", self._config.enable_hyde),
        ):
            outcome = self._stage(inputs, stage, enabled, run_id, corrections)
            corrections -= max(0, len(outcome.report.attempts) - 1)
            outcomes.append(outcome)
            self._log_stage(inputs, outcome, run_id)
        expansion, hyde = outcomes
        degraded = any(
            item.status == StageStatus.FAILED
            or len(item.report.attempts) > 1
            or any(
                decision.reason in {"unsafe_candidate", "length_budget", "count_budget"}
                for decision in item.report.decisions
            )
            for item in outcomes
        )
        LOGGER.info(
            "query_enhancement summary",
            extra={
                "stage": "query_enhancement",
                "trace_id": inputs.trace.trace_id if inputs.trace else None,
                "task_id": inputs.trace.task_id if inputs.trace else None,
                "request_id": run_id,
                "processing_intent": inputs.processing_intent.value,
                "degraded": degraded,
                "expansion_count": len(expansion.queries),
                "hyde_completed": hyde.hypothesis is not None,
            },
        )
        return QueryEnhancementResult(
            original_question=inputs.original_question,
            rewritten_query=inputs.rewritten_query,
            keyword_synonyms=list(inputs.keyword_synonyms),
            processing_intent=inputs.processing_intent,
            filters=inputs.filters.model_copy(deep=True),
            expanded_queries=expansion.queries,
            hypothetical_document=hyde.hypothesis,
            expansion_status=expansion.status,
            hyde_status=hyde.status,
            expansion_report=expansion.report,
            hyde_report=hyde.report,
            degraded=degraded,
            trace=inputs.trace,
            policy_fingerprint=self._fingerprint,
        )

    def _inputs(
        self,
        request: QueryRequest,
        understanding: UnderstandingResult,
        rewrite: RewriteResult,
    ) -> EnhancementInput:
        # Copy only required fields, not complete request/history/catalog artifacts.
        try:
            if (
                rewrite.original_question != request.question
                or rewrite.processing_intent != understanding.processing_intent
                or rewrite.filters != understanding.filters
                or rewrite.trace != request.trace
            ):
                raise ValueError("upstream request, intent, filters or trace do not match")
            if not rewrite.attempts or rewrite.attempts[-1].status != "success":
                raise ValueError("Rewrite artifact is not a successful stage result")
            for field in type(request.filters).model_fields:
                caller, verified = (
                    getattr(request.filters, field),
                    getattr(understanding.filters, field),
                )
                if isinstance(caller, list):
                    if caller and (not verified or not set(verified).issubset(caller)):
                        raise ValueError("upstream filters expanded the caller scope")
                elif caller is not None and caller != verified:
                    raise ValueError("upstream filters changed a caller boolean constraint")
            if any(
                item.start < 0
                or item.end <= item.start
                or item.end > len(request.question)
                or request.question[item.start : item.end] != item.value
                for item in rewrite.protected_spans
            ):
                raise ValueError("Rewrite protection lineage does not match the question")
            inputs = EnhancementInput(
                original_question=request.question,
                rewritten_query=rewrite.rewritten_query,
                keyword_synonyms=list(rewrite.keyword_synonyms),
                processing_intent=understanding.processing_intent,
                filters=SearchFilters.model_validate_json(understanding.filters.model_dump_json()),
                protected_values=list(
                    dict.fromkeys(item.value for item in rewrite.protected_spans)
                ),
                trace=request.trace.model_copy(deep=True) if request.trace else None,
            )
        except (ValueError, TypeError) as exc:
            raise EnhancementInputError(
                "invalid_upstream", "corresponding successful upstream artifacts required"
            ) from exc
        if (
            len(inputs.original_question) > self._config.max_question_chars
            or len(inputs.rewritten_query) > self._config.max_primary_chars
        ):
            raise EnhancementInputError(
                "input_budget", "primary query is over budget; input was not truncated"
            )
        return inputs

    def _stage(
        self,
        inputs: EnhancementInput,
        stage: Stage,
        enabled: bool,
        run_id: str,
        corrections: int,
    ) -> StageOutcome:
        if inputs.processing_intent == ProcessingIntent.ACQUISITION:
            return StageOutcome(
                status=StageStatus.SKIPPED_BY_INTENT, report=stage_report(stage, self._config)
            )
        if not enabled:
            return StageOutcome(
                status=StageStatus.SKIPPED_BY_CONFIG, report=stage_report(stage, self._config)
            )
        return run_stage(self._llm, self._config, inputs, stage, run_id, corrections)

    def _log_stage(self, inputs: EnhancementInput, outcome: StageOutcome, run_id: str) -> None:
        report = outcome.report
        LOGGER.info(
            report.stage + " result",
            extra={
                "stage": report.stage,
                "trace_id": inputs.trace.trace_id if inputs.trace else None,
                "task_id": inputs.trace.task_id if inputs.trace else None,
                "request_id": run_id,
                "processing_intent": inputs.processing_intent.value,
                "status": outcome.status.value,
                "error_code": report.error_code,
                "expansion_count": len(outcome.queries),
                "hyde_completed": outcome.hypothesis is not None,
                "attempt_count": len(report.attempts),
                "model_config_id": report.model_config_id,
                "model_id": report.model_id,
                "prompt_version": report.prompt_version,
                "policy_fingerprint": self._fingerprint,
                "elapsed_seconds": sum(item.elapsed_seconds for item in report.attempts),
                "usage": [
                    item.usage.model_dump(mode="json") if item.usage else None
                    for item in report.attempts
                ],
            },
        )
