"""Private, strict Understanding DTOs; not public Query contracts."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engineering_rag.contracts.catalog import CatalogIndexScope, StandardMetadataMatch
from engineering_rag.contracts.chunks import ChunkContentType
from engineering_rag.contracts.llm import LLMTokenUsage
from engineering_rag.contracts.queries import ProcessingIntent, QueryIntent
from engineering_rag.contracts.retrieval import SearchFilters

Text = Annotated[str, Field(min_length=1, max_length=4096, pattern=r"\S")]
Position = Annotated[int, Field(ge=0)]


class PrivateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, validate_assignment=True)


class SourceEvidence(PrivateModel):
    """Python character offsets, end-exclusive; history indexes refer to original turns."""

    source: Literal["question", "history_user"]
    history_index: Position | None = None
    start: Position
    end: Position
    quote: Text

    @model_validator(mode="after")
    def check_span(self) -> "SourceEvidence":
        if self.end <= self.start:
            raise ValueError("evidence must have a positive span")
        if (self.source == "question") != (self.history_index is None):
            raise ValueError("only history evidence requires history_index")
        return self


class TextCandidate(PrivateModel):
    value: Text
    evidence: SourceEvidence


class StandardCandidate(PrivateModel):
    standard_code: TextCandidate | None = None
    standard_name: TextCandidate | None = None
    edition: TextCandidate | None = None
    revision: TextCandidate | None = None

    def selectors(self) -> dict[str, TextCandidate]:
        return {
            name: item
            for name in type(self).model_fields
            if (item := getattr(self, name)) is not None
        }

    @model_validator(mode="after")
    def check_identity(self) -> "StandardCandidate":
        if self.standard_code is None and self.standard_name is None:
            raise ValueError("standard candidate requires a code or name, never an LLM document ID")
        sources = {
            (item.evidence.source, item.evidence.history_index)
            for item in self.selectors().values()
        }
        if len(sources) != 1:
            raise ValueError("do not combine current and historical standard selectors")
        return self


class ContentTypeCandidate(PrivateModel):
    value: ChunkContentType
    evidence: SourceEvidence


class BooleanCandidate(PrivateModel):
    value: bool
    evidence: SourceEvidence


class UnderstandingOutput(PrivateModel):
    """Authoritative schema sent to the injected structured LLM."""

    processing_intent: ProcessingIntent
    context_sufficient: bool
    standards: list[StandardCandidate] = Field(max_length=16)
    clause_numbers: list[TextCandidate] = Field(max_length=32)
    content_types: list[ContentTypeCandidate] = Field(max_length=8)
    is_explanation: BooleanCandidate | None
    is_mandatory: BooleanCandidate | None


class CandidateDecision(PrivateModel):
    key: str
    candidate: StandardCandidate | TextCandidate | ContentTypeCandidate | BooleanCandidate
    status: Literal["adopted", "rejected", "ignored"]
    reason: str
    document_ids: list[str] = Field(default_factory=list)


class ModelAttempt(PrivateModel):
    request_id: str
    status: Literal["success", "invalid_output", "model_failure"]
    elapsed_seconds: float
    usage: LLMTokenUsage | None = None


class UnderstandingResult(PrivateModel):
    processing_intent: ProcessingIntent
    semantic_intent: QueryIntent = QueryIntent.UNKNOWN
    filters: SearchFilters
    scope: CatalogIndexScope
    catalog_matches: list[StandardMetadataMatch]
    decisions: list[CandidateDecision]
    attempts: list[ModelAttempt]
    diagnostics: list[str]
    degraded: bool
    clause_existence_verified: Literal[False] = False
    prompt_version: str
    model_config_id: str
    model_id: str
    model_revision: str | None
