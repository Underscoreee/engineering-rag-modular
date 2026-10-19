"""Request-local evidence registration and lossless, whole-block character budgets."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from pydantic import JsonValue, ValidationError

from engineering_rag.contracts.answers import GenerationRequest
from engineering_rag.contracts.retrieval import RetrievalResult

from .models import GenerationError, GenerationOutput, GenerationSettings
from .prompts import INSTRUCTIONS, PROMPT_VERSION


@dataclass(frozen=True)
class OmittedEvidence:
    chunk_id: str
    reason: str


@dataclass(frozen=True)
class GenerationContext:
    payload: dict[str, JsonValue]
    registry: Mapping[str, RetrievalResult]
    estimated_chars: int
    omitted: tuple[OmittedEvidence, ...]
    history_omitted: int


def application_chars(payload: dict[str, JsonValue]) -> int:
    """Serialized application input/schema length, NOT a tokenizer or model limit.

    Transport framing and provider tokenization are deliberately not guessed.
    Output tokens are separately bounded by StructuredLLMConfig.
    """
    return len(
        json.dumps(
            {"input": payload, "output_schema": GenerationOutput.model_json_schema()},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )


class ContextBuilder:
    def __init__(self, settings: GenerationSettings) -> None:
        self._settings = GenerationSettings.model_validate_json(settings.model_dump_json())

    def build(self, request: GenerationRequest) -> GenerationContext:
        try:
            request = GenerationRequest.model_validate_json(request.model_dump_json())
        except (ValidationError, ValueError, TypeError):
            raise GenerationError("invalid_request") from None
        if not request.question.strip() or any(
            not turn.content.strip() for turn in request.history
        ):
            raise GenerationError("invalid_request")
        payload: dict[str, JsonValue] = {
            "instructions": INSTRUCTIONS,
            "prompt_version": PROMPT_VERSION,
            "question": request.question,
            "history": [],
            "evidence": [],
        }
        limit = self._settings.max_context_chars
        if application_chars(payload) > limit:
            raise GenerationError("context_budget")
        registry: dict[str, RetrievalResult] = {}
        omitted: list[OmittedEvidence] = []
        # Stable rank order: scores across retrieval sources are not comparable.
        unique: dict[str, RetrievalResult] = {}
        for item in sorted(request.evidence, key=lambda item: item.rank):
            prior = unique.get(item.chunk_id)
            if prior is not None:
                if self._identity(prior) != self._identity(item):
                    raise GenerationError("evidence_conflict")
                continue
            unique[item.chunk_id] = item
        rows: list[JsonValue] = []
        for index, item in enumerate(unique.values(), 1):
            if not item.content.strip() or not item.standard.standard_name.strip():
                raise GenerationError("invalid_evidence")
            evidence_id = f"E{index}"
            # IDs/edition and null source attributes are preserved, not inferred.
            row: JsonValue = {
                "evidence_id": evidence_id,
                "chunk_id": item.chunk_id,
                "logical_chunk_id": item.logical_chunk_id,
                "document_id": item.document_id,
                "standard": item.standard.model_dump(mode="json"),
                "clause_id": item.clause_id,
                "clause_number": item.clause_number,
                "page_start": item.page_start,
                "page_end": item.page_end,
                "is_explanation": item.is_explanation,
                "is_mandatory": item.is_mandatory,
                "content_type": item.content_type.value if item.content_type else None,
                "content": item.content,
            }
            payload["evidence"] = [*rows, row]
            if application_chars(payload) > limit:
                omitted.append(OmittedEvidence(item.chunk_id, "whole_evidence_exceeds_budget"))
                payload["evidence"] = list(rows)
                continue
            rows.append(row)
            registry[evidence_id] = item
        # Evidence takes precedence over history. Keep whole recent turns, in order.
        history: list[JsonValue] = []
        history_chars = 0
        for turn in reversed(request.history):
            if (
                len(history) >= self._settings.max_history_turns
                or history_chars + len(turn.content) > self._settings.max_history_chars
            ):
                break
            candidate: JsonValue = turn.model_dump(mode="json")
            payload["history"] = [candidate, *history]
            if application_chars(payload) > limit:
                payload["history"] = list(history)
                break
            history.insert(0, candidate)
            history_chars += len(turn.content)
        return GenerationContext(
            payload=payload,
            registry=MappingProxyType(registry),
            estimated_chars=application_chars(payload),
            omitted=tuple(omitted),
            history_omitted=len(request.history) - len(history),
        )

    @staticmethod
    def _identity(item: RetrievalResult) -> dict[str, object]:
        # Rank/score/backend may differ; content and all real source identities may not.
        return item.model_dump(
            exclude={"rank", "score", "retrieval_source", "score_type", "index_name"}
        )
