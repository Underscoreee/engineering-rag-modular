"""Observe public model calls without treating response candidates as validated facts."""

from __future__ import annotations

import logging
from copy import deepcopy
from threading import RLock
from time import monotonic

from engineering_rag.contracts.llm import StructuredLLMRequest, StructuredLLMResponse
from engineering_rag.contracts.protocols import StructuredLLMClient

_CAPTURE_LOCK = RLock()


class QueryEvents(logging.Handler):
    """Temporarily collect existing trace-scoped metadata, not private stage objects.

    No business import is needed. Logging event availability is explicitly
    optional; absent events are not fabricated. The evaluator runs sequentially,
    restores logger settings, and serializes its own capture scopes.
    """

    def __init__(self, trace_id: str) -> None:
        super().__init__(logging.INFO)
        self.trace_id = trace_id
        self.events: list[dict[str, object]] = []
        self.logger = logging.getLogger("engineering_rag.modules.query")

    def __enter__(self) -> QueryEvents:
        _CAPTURE_LOCK.acquire()
        self.previous_level = self.logger.level
        self.logger.setLevel(logging.INFO)
        self.logger.addHandler(self)
        return self

    def __exit__(self, *args: object) -> None:
        self.logger.removeHandler(self)
        self.logger.setLevel(self.previous_level)
        _CAPTURE_LOCK.release()
        self.close()

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "trace_id", None) != self.trace_id:
            return
        fields = (
            "stage",
            "status",
            "error_code",
            "elapsed_seconds",
            "prompt_version",
            "policy_fingerprint",
            "model_config_id",
            "model_id",
            "expansion_count",
            "hyde_completed",
            "vector_strategy",
            "processing_intent",
            "candidate_k",
            "top_k",
        )
        self.events.append({key: getattr(record, key) for key in fields if hasattr(record, key)})


class ModelProbe:
    def __init__(self, client: StructuredLLMClient) -> None:
        self.client = client
        self.attempts: list[dict[str, object]] = []

    def generate(self, request: StructuredLLMRequest) -> StructuredLLMResponse:
        started = monotonic()
        observation: dict[str, object] = {
            "request_id": request.request_id,
            "stage": request.stage,
            "config": request.config.model_dump(mode="json"),
            "status": "transport_failure",
            "usage": None,
            "candidate_summary": None,
            "prompt_version": request.input.get("prompt_version"),
            # Downstream input is emitted AFTER Understanding validation. Unlike
            # response.data, it can identify an observed successful prior stage.
            "validated_understanding_input": deepcopy(
                {
                    "processing_intent": request.input.get("processing_intent"),
                    "filters": request.input.get("validated_filters"),
                }
            )
            if request.stage == "query_rewrite"
            else None,
        }
        try:
            response = self.client.generate(request.model_copy(deep=True))
            # Bind the public transport envelope, NOT the private task output schema.
            if (
                response.request_id != request.request_id
                or response.model_id != request.config.model_id
                or (
                    request.config.model_revision is not None
                    and response.model_revision != request.config.model_revision
                )
            ):
                raise ValueError("model response does not match requested identity")
            observation["status"] = "transport_success_not_business_validation"
            observation["usage"] = (
                response.usage.model_dump(mode="json") if response.usage else None
            )
            data = response.data
            if request.stage == "query_expansion":
                candidates = data.get("expanded_queries")
                observation["candidate_summary"] = {
                    "count": len(candidates) if isinstance(candidates, list) else None,
                    "empty_count": sum(
                        isinstance(item, str) and not item.strip() for item in candidates
                    )
                    if isinstance(candidates, list)
                    else None,
                    "char_lengths": [
                        len(item) if isinstance(item, str) else None for item in candidates
                    ]
                    if isinstance(candidates, list)
                    else None,
                }
            elif request.stage == "query_hyde":
                text = data.get("hypothetical_document")
                observation["candidate_summary"] = {
                    "empty": not isinstance(text, str) or not text.strip(),
                    "char_length": len(text) if isinstance(text, str) else None,
                }
            return response
        finally:
            observation["elapsed_seconds"] = monotonic() - started
            self.attempts.append(observation)


def model_usage(attempts: list[dict[str, object]]) -> dict[str, object]:
    """Unknown failed-call usage stays null, never an invented zero cost."""
    totals: dict[str, int | None] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        values = [
            item["usage"].get(key) if isinstance(item["usage"], dict) else None for item in attempts
        ]
        totals[key] = sum(values) if all(type(value) is int for value in values) else None
    return {
        "attempt_count": len(attempts),
        **totals,
        "cost": None,
        "cost_reason": "no_verified_provider_pricing_and_billing_information",
        "timing_definition": "model_call_wall_time_only_not_complete_business_stage",
    }
