"""Independent, injected Rewrite stage. Failure never masquerades as original-query success."""

import hashlib
import json
import logging
from time import monotonic
from uuid import uuid4

from pydantic import ValidationError

from engineering_rag.contracts.llm import StructuredLLMRequest
from engineering_rag.contracts.protocols import StructuredLLMClient
from engineering_rag.contracts.queries import QueryRequest

from .models import UnderstandingResult
from .rewrite_models import (
    RewriteAttempt,
    RewriteConfig,
    RewriteError,
    RewriteFailureCode,
    RewriteOutput,
    RewriteResult,
)
from .rewrite_prompt import REWRITE_INSTRUCTIONS, REWRITE_PROMPT_VERSION
from .rewrite_protection import (
    PROTECTION_RULE_VERSION,
    extract_protected_spans,
    scope_literals,
    validate_rewrite,
    validate_understanding_scope,
)
from .rewrite_synonyms import review_synonyms

LOGGER = logging.getLogger(__name__)


class QueryRewrite:
    def __init__(self, *, llm: StructuredLLMClient, config: RewriteConfig) -> None:
        self._llm = llm
        self._config = RewriteConfig.model_validate_json(config.model_dump_json())
        policy = {
            field: getattr(self._config, field)
            for field in (
                "language_rules",
                "equivalent_terms",
                "max_keyword_synonyms",
                "max_synonym_chars",
            )
        }
        self._policy_fingerprint = hashlib.sha256(
            json.dumps(
                {
                    "protection_version": PROTECTION_RULE_VERSION,
                    **{
                        key: [item.model_dump(mode="json") for item in value]
                        if isinstance(value, list)
                        else value
                        for key, value in policy.items()
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    def rewrite(self, request: QueryRequest, understanding: UnderstandingResult) -> RewriteResult:
        """Consume the corresponding successful Understanding; never invoke it again."""
        run_id = uuid4().hex
        attempts: list[RewriteAttempt] = []
        try:
            try:
                request = QueryRequest.model_validate_json(request.model_dump_json())
                understanding = UnderstandingResult.model_validate_json(
                    understanding.model_dump_json()
                )
            except ValueError as exc:
                raise RewriteError("scope_conflict", "invalid request/Understanding input") from exc
            self._check_budget(request)
            try:
                validate_understanding_scope(request, understanding)
            except ValueError as exc:
                raise RewriteError(
                    "scope_conflict", "request and Understanding scope conflict"
                ) from exc
            return self._run(request, understanding, run_id, attempts)
        except RewriteError as exc:
            exc.attempts = tuple(item.model_copy(deep=True) for item in attempts)
            LOGGER.info(
                "query_rewrite failed",
                extra={
                    "stage": "query_rewrite",
                    "request_id": run_id,
                    "trace_id": request.trace.trace_id if request.trace else None,
                    "task_id": request.trace.task_id if request.trace else None,
                    "model_config_id": self._config.llm.config_id,
                    "status": exc.code,
                    "attempt_count": len(attempts),
                    "prompt_version": REWRITE_PROMPT_VERSION,
                },
            )
            raise

    def _check_budget(self, request: QueryRequest) -> None:
        config = self._config
        if (
            not request.question.strip()
            or len(request.question) > config.max_question_chars
            or len(request.history) > config.max_history_turns
            or sum(len(item.content) for item in request.history) > config.max_history_chars
            or any(not item.content.strip() for item in request.history)
        ):
            raise RewriteError("input_budget", "question/history is blank or exceeds its budget")

    def _run(
        self,
        request: QueryRequest,
        understanding: UnderstandingResult,
        run_id: str,
        attempts: list[RewriteAttempt],
    ) -> RewriteResult:
        config = self._config
        literals = scope_literals(understanding, request.question)
        protected = extract_protected_spans(request.question, literals)
        previous_error: RewriteFailureCode | None = None
        for index in range(config.max_attempts):
            llm_request = self._build_request(
                request,
                understanding,
                f"{run_id}-rewrite-{index}",
                list(dict.fromkeys(item.value for item in protected)),
                previous_error,
            )
            started = monotonic()
            usage = None
            try:
                response = self._llm.generate(llm_request.model_copy(deep=True))
                parsed = response.validate_output(llm_request, RewriteOutput)
                usage = response.usage
                if len(parsed.rewritten_query) > config.max_rewritten_chars:
                    raise ValueError("rewritten query exceeds configured character budget")
            except (ValidationError, ValueError) as exc:
                code: RewriteFailureCode = "invalid_output"
                failure: Exception = exc
                retry = True
            except Exception as exc:
                code, failure = "model_failure", exc
                retry = isinstance(exc, (TimeoutError, ConnectionError))
            else:
                try:
                    edits = validate_rewrite(
                        request.question, parsed.rewritten_query, config, literals
                    )
                except ValueError as exc:
                    code, failure, retry = "unsafe_rewrite", exc, True
                else:
                    synonyms, decisions = review_synonyms(
                        parsed.keyword_synonyms,
                        request.question,
                        parsed.rewritten_query,
                        config,
                    )
                    attempts.append(
                        RewriteAttempt(
                            request_id=llm_request.request_id,
                            status="success",
                            elapsed_seconds=monotonic() - started,
                            usage=usage,
                        )
                    )
                    self._log_attempt(request, attempts[-1], len(attempts))
                    return RewriteResult(
                        original_question=request.question,
                        rewritten_query=parsed.rewritten_query,
                        keyword_synonyms=synonyms,
                        processing_intent=understanding.processing_intent,
                        filters=understanding.filters.model_copy(deep=True),
                        protected_spans=protected,
                        applied_rules=edits,
                        synonym_decisions=decisions,
                        attempts=attempts,
                        trace=request.trace,
                        prompt_version=REWRITE_PROMPT_VERSION,
                        policy_fingerprint=self._policy_fingerprint,
                        model_config_id=config.llm.config_id,
                        model_id=config.llm.model_id,
                        model_revision=config.llm.model_revision,
                    )
            attempts.append(
                RewriteAttempt(
                    request_id=llm_request.request_id,
                    status=code,
                    elapsed_seconds=monotonic() - started,
                    usage=usage,
                )
            )
            self._log_attempt(request, attempts[-1], len(attempts))
            if not retry or index + 1 == config.max_attempts:
                raise RewriteError(
                    code, "Rewrite attempt failed; no fallback query returned"
                ) from failure
            previous_error = code
        raise AssertionError("positive Rewrite attempt budget was not enforced")

    def _build_request(
        self,
        request: QueryRequest,
        understanding: UnderstandingResult,
        request_id: str,
        protected_values: list[str],
        previous_error: RewriteFailureCode | None,
    ) -> StructuredLLMRequest:
        config = self._config
        return StructuredLLMRequest(
            request_id=request_id,
            stage="query_rewrite",
            input={
                "instructions": REWRITE_INSTRUCTIONS,
                "prompt_version": REWRITE_PROMPT_VERSION,
                "question": request.question,
                "history": [item.model_dump(mode="json") for item in request.history],
                "processing_intent": understanding.processing_intent.value,
                "validated_filters": understanding.filters.model_dump(mode="json"),
                "protected_values": protected_values,
                "allowed_language_rules": [
                    item.model_dump(mode="json") for item in config.language_rules
                ],
                "reviewed_equivalent_terms": [
                    item.model_dump(mode="json")
                    for item in config.equivalent_terms
                    if item.term in request.question
                ],
                "previous_error": previous_error,
            },
            output_schema=RewriteOutput.model_json_schema(),
            config=config.llm.model_copy(deep=True),
            trace=request.trace,
        )

    def _log_attempt(self, request: QueryRequest, attempt: RewriteAttempt, count: int) -> None:
        LOGGER.info(
            "query_rewrite attempt",
            extra={
                "stage": "query_rewrite",
                "request_id": attempt.request_id,
                "trace_id": request.trace.trace_id if request.trace else None,
                "task_id": request.trace.task_id if request.trace else None,
                "model_config_id": self._config.llm.config_id,
                "model_id": self._config.llm.model_id,
                "prompt_version": REWRITE_PROMPT_VERSION,
                "policy_fingerprint": self._policy_fingerprint,
                "status": attempt.status,
                "attempt_count": count,
                "elapsed_seconds": attempt.elapsed_seconds,
                "usage": attempt.usage.model_dump(mode="json") if attempt.usage else None,
            },
        )
