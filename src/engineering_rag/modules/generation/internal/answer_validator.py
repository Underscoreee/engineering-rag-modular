"""Deterministic answer/citation checks; no semantic oracle, retrieval or model calls."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from engineering_rag.contracts.answers import (
    AnswerResult,
    GroundingStatus,
    validate_answer_citations,
)
from engineering_rag.contracts.common import SCHEMA_VERSION, ContractError

from .citation_mapper import (
    CitationMapping,
    normalize_quote_whitespace,
    quote_is_present,
    validate_registry,
)
from .context import GenerationContext
from .models import INSUFFICIENT_ANSWER, GenerationError

_SEMANTIC_LIMIT = (
    "Answer-level citations validate source identity and optional literal quotes only; "
    "individual claims, relevance and engineering/legal correctness are not verified"
)


def warning(message: str) -> ContractError:
    return ContractError(code="unsupported", message=message)


class AnswerValidator:
    def __init__(self, *, max_answer_chars: int) -> None:
        if type(max_answer_chars) is not int or max_answer_chars <= 0:
            raise ValueError("max_answer_chars must be a positive integer")
        self._max_answer_chars = max_answer_chars

    def validate(
        self,
        answer: AnswerResult | Mapping[str, object],
        *,
        context: GenerationContext,
        mapping: CitationMapping,
        limitations: Sequence[str] = (),
    ) -> AnswerResult:
        """Return a fresh checked result, or fail; never strip invalid citations."""
        if not isinstance(mapping, CitationMapping) or mapping.context is not context:
            raise GenerationError("citation_scope")
        validate_registry(context)
        try:
            payload = (
                answer.model_dump(mode="python", warnings=False)
                if isinstance(answer, AnswerResult)
                else dict(answer)
            )
            result = AnswerResult.model_validate_json(
                json.dumps(payload, ensure_ascii=False, allow_nan=False), strict=True
            )
        except (TypeError, ValueError):
            raise GenerationError("invalid_answer") from None
        if result.schema_version != SCHEMA_VERSION or not result.answer.strip():
            raise GenerationError("invalid_answer")
        if any(not isinstance(item, str) or not item.strip() for item in limitations):
            raise GenerationError("invalid_output")
        if limitations:
            self._add_warning(result, "Model reported limitations: " + "；".join(limitations))
        self._validate_citations(result, mapping, context)
        status = result.grounding_status
        if status == GroundingStatus.INSUFFICIENT_EVIDENCE:
            if result.citations or result.answer != INSUFFICIENT_ANSWER:
                raise GenerationError("grounding_conflict")
            # This fixed local fallback is not model output. Preserve Task 7.1's
            # no-evidence policy even when the configured model budget is tiny.
            return result
        if len(result.answer) > self._max_answer_chars:
            raise GenerationError("output_budget")
        if not result.citations:
            raise GenerationError("grounding_conflict")
        if status == GroundingStatus.GROUNDED:
            # A source ID alone proves nothing about a paraphrase. Only a complete
            # full-content copy can retain this status without a semantic verifier.
            # A substring can omit a leading negation or an applicability condition.
            literal_answer = any(
                normalize_quote_whitespace(result.answer)
                == normalize_quote_whitespace(context.registry[key].content)
                for key in mapping.evidence_ids
            )
            if limitations or context.omitted or not literal_answer:
                result.grounding_status = GroundingStatus.PARTIALLY_GROUNDED
                reason = (
                    "limitations or omitted evidence"
                    if limitations or context.omitted
                    else "non-extractive answer; claim support is unverified"
                )
                self._add_warning(result, "Grounding downgraded: " + reason)
        if result.grounding_status == GroundingStatus.PARTIALLY_GROUNDED and not limitations:
            self._add_warning(result, "Only partial support can be established")
        self._add_warning(result, _SEMANTIC_LIMIT)
        return result

    @staticmethod
    def _add_warning(answer: AnswerResult, message: str) -> None:
        if not any(item.message == message for item in answer.warnings):
            answer.warnings.append(warning(message))

    @staticmethod
    def _validate_citations(
        answer: AnswerResult,
        mapping: CitationMapping,
        context: GenerationContext,
    ) -> None:
        ids = mapping.evidence_ids
        if len(ids) != len(set(ids)) or len(ids) != len(mapping.citations):
            raise GenerationError("citation_mapping")
        if any(key not in context.registry for key in ids):
            raise GenerationError("unknown_evidence_id")
        if len(answer.citations) != len(mapping.citations):
            raise GenerationError("citation_mapping")
        seen_ids: set[str] = set()
        seen_chunks: set[str] = set()
        for index, (citation, expected, evidence_id) in enumerate(
            zip(answer.citations, mapping.citations, ids, strict=True), 1
        ):
            if citation.citation_id in seen_ids or citation.evidence_chunk_id in seen_chunks:
                raise GenerationError("citation_conflict")
            seen_ids.add(citation.citation_id)
            seen_chunks.add(citation.evidence_chunk_id)
            item = context.registry[evidence_id]
            if (
                citation.citation_id != f"C{index}"
                or citation != expected
                or citation.evidence_chunk_id != item.chunk_id
                or citation.document_id != item.document_id
                or citation.clause_id != item.clause_id
                or citation.page_start != item.page_start
                or citation.page_end != item.page_end
            ):
                raise GenerationError("citation_mapping")
            if citation.quoted_text is not None and not quote_is_present(
                citation.quoted_text, item.content
            ):
                raise GenerationError("quote_mismatch")
        if validate_answer_citations(answer, list(context.registry.values())):
            raise GenerationError("citation_mapping")
