"""Grounded answer and citation contracts."""

from enum import StrEnum

from pydantic import Field, model_validator

from .common import (
    SCHEMA_VERSION,
    ContractError,
    ContractModel,
    NonEmptyStr,
    PositivePage,
    TraceContext,
)
from .queries import ConversationTurn
from .retrieval import RetrievalResult


class GenerationConfig(ContractModel):
    config_id: NonEmptyStr
    max_output_tokens: int = Field(gt=0)
    temperature: float = Field(default=0, ge=0, le=2)


class GenerationRequest(ContractModel):
    question: NonEmptyStr
    evidence: list[RetrievalResult]
    history: list[ConversationTurn] = Field(default_factory=list)
    config: GenerationConfig | None = None
    trace: TraceContext | None = None


class Citation(ContractModel):
    citation_id: NonEmptyStr
    evidence_chunk_id: NonEmptyStr
    document_id: NonEmptyStr
    clause_id: NonEmptyStr | None = None
    page_start: PositivePage
    page_end: PositivePage
    quoted_text: str | None = None

    @model_validator(mode="after")
    def validate_pages(self) -> "Citation":
        if self.page_end < self.page_start:
            raise ValueError("citation page_end must not precede page_start")
        return self


class GroundingStatus(StrEnum):
    GROUNDED = "grounded"
    PARTIALLY_GROUNDED = "partially_grounded"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ModelMetadata(ContractModel):
    provider: NonEmptyStr
    model_id: NonEmptyStr
    model_version: str | None = None


class AnswerResult(ContractModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    answer: NonEmptyStr
    citations: list[Citation] = Field(default_factory=list)
    grounding_status: GroundingStatus
    model: ModelMetadata | None = None
    warnings: list[ContractError] = Field(default_factory=list)


def validate_answer_citations(
    answer: AnswerResult, evidence: list[RetrievalResult]
) -> list[ContractError]:
    """Check that citations point to the supplied evidence identity and range."""
    by_chunk = {item.chunk_id: item for item in evidence}
    errors: list[ContractError] = []
    for citation in answer.citations:
        item = by_chunk.get(citation.evidence_chunk_id)
        if item is None:
            errors.append(
                ContractError(
                    code="invalid_input",
                    message="citation references unknown evidence chunk",
                    field=citation.citation_id,
                )
            )
        elif (
            item.document_id != citation.document_id
            or item.clause_id != citation.clause_id
            or citation.page_start < item.page_start
            or citation.page_end > item.page_end
        ):
            errors.append(
                ContractError(
                    code="invalid_input",
                    message="citation identity or page range disagrees with evidence",
                    field=citation.citation_id,
                )
            )
    return errors
