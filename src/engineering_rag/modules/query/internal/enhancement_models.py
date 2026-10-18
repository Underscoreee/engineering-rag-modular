"""Private typed optional-enhancement artifacts; no public retrieval contracts."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from engineering_rag.contracts.common import TraceContext
from engineering_rag.contracts.llm import LLMTokenUsage, StructuredLLMConfig
from engineering_rag.contracts.queries import ProcessingIntent
from engineering_rag.contracts.retrieval import SearchFilters

from .models import PrivateModel, Text

Stage = Literal["query_expansion", "query_hyde"]
FailureCode = Literal["timeout", "connection", "model_failure", "invalid_output", "unsafe_output"]
PositiveInt = Annotated[int, Field(gt=0)]


class StageStatus(StrEnum):
    COMPLETED = "completed"
    SKIPPED_BY_INTENT = "skipped_by_intent"
    SKIPPED_BY_CONFIG = "skipped_by_config"
    FAILED = "failed"


class RelatedContext(PrivateModel):
    """Reviewed retrieval relevance, NOT a synonym or an asserted engineering requirement."""

    anchor: Annotated[str, Field(min_length=1, max_length=128, pattern=r"\S")]
    phrase: Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")]
    evidence_id: Text


def default_contexts() -> list[RelatedContext]:
    return [
        RelatedContext(anchor=anchor, phrase=phrase, evidence_id="builtin-retrieval-focus-v1")
        for anchor, phrase in (
            ("设计", "设计条件与验算要求之间的关联"),
            ("规范", "规范适用范围与条文关联"),
            ("比较", "比较对象的适用条件与差异"),
        )
    ]


class EnhancementConfig(PrivateModel):
    expansion_llm: StructuredLLMConfig
    hyde_llm: StructuredLLMConfig
    enable_expansion: bool = True
    enable_hyde: bool = True
    max_question_chars: PositiveInt = 8000
    max_primary_chars: PositiveInt = 8000
    max_expansions: Annotated[int, Field(ge=1, le=8)] = 3
    max_expanded_query_chars: PositiveInt = 2048
    max_hyde_chars: PositiveInt = 4096
    max_hyde_contexts: Annotated[int, Field(ge=0, le=8)] = 3
    # One ordinary call per stage; at most ONE correction shared across both, default none.
    max_corrections: Annotated[int, Field(ge=0, le=1)] = 0
    related_contexts: list[RelatedContext] = Field(default_factory=default_contexts, max_length=32)


class EnhancementInput(PrivateModel):
    original_question: Annotated[str, Field(min_length=1, pattern=r"\S")]
    rewritten_query: Annotated[str, Field(min_length=1, pattern=r"\S")]
    keyword_synonyms: list[Text] = Field(max_length=8)
    processing_intent: ProcessingIntent
    filters: SearchFilters
    protected_values: list[str]
    trace: TraceContext | None = None


class ExpansionOutput(PrivateModel):
    expanded_queries: list[Annotated[str, Field(max_length=16000)]] = Field(max_length=16)


class HyDEOutput(PrivateModel):
    hypothetical_document: Annotated[str, Field(min_length=1, max_length=16000, pattern=r"\S")]


class ExpansionDecision(PrivateModel):
    index: int
    attempt: int
    adopted: bool
    reason: Literal[
        "accepted",
        "duplicate",
        "already_primary",
        "count_budget",
        "length_budget",
        "unsafe_candidate",
    ]
    context_id: str | None = None


class EnhancementAttempt(PrivateModel):
    request_id: str
    status: Literal["completed", "failed"]
    error_code: FailureCode | None = None
    elapsed_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    usage: LLMTokenUsage | None = None

    @model_validator(mode="after")
    def check_failure(self) -> "EnhancementAttempt":
        if (self.status == "failed") != (self.error_code is not None):
            raise ValueError("attempt error_code must correspond to failed status")
        return self


class StageReport(PrivateModel):
    stage: Stage
    error_code: FailureCode | None = None
    attempts: list[EnhancementAttempt] = Field(default_factory=list)
    decisions: list[ExpansionDecision] = Field(default_factory=list)
    model_config_id: str
    model_id: str
    model_revision: str | None
    prompt_version: str


class QueryEnhancementResult(PrivateModel):
    schema_version: Literal["1.0"] = "1.0"
    original_question: str
    rewritten_query: str
    keyword_synonyms: list[str]
    processing_intent: ProcessingIntent
    filters: SearchFilters
    expanded_queries: list[str]
    hypothetical_document: str | None
    hypothesis_is_evidence: Literal[False] = False
    expansion_status: StageStatus
    hyde_status: StageStatus
    expansion_report: StageReport
    hyde_report: StageReport
    degraded: bool
    trace: TraceContext | None = None
    policy_fingerprint: str

    @model_validator(mode="after")
    def check_stage_semantics(self) -> "QueryEnhancementResult":
        if (
            self.expansion_report.stage != "query_expansion"
            or self.hyde_report.stage != "query_hyde"
        ):
            raise ValueError("stage reports must not be exchanged")
        if self.expansion_status != StageStatus.COMPLETED and self.expanded_queries:
            raise ValueError("non-completed Expansion cannot return generated queries")
        if self.hyde_status != StageStatus.COMPLETED and self.hypothetical_document is not None:
            raise ValueError("non-completed HyDE cannot return a hypothesis")
        if self.hyde_status == StageStatus.COMPLETED and not (
            self.hypothetical_document and self.hypothetical_document.strip()
        ):
            raise ValueError("completed HyDE must contain generated text")
        for status, report in (
            (self.expansion_status, self.expansion_report),
            (self.hyde_status, self.hyde_report),
        ):
            if status == StageStatus.FAILED and (report.error_code is None or not self.degraded):
                raise ValueError(
                    "optional-stage failure requires an error and explicit degradation"
                )
            if status == StageStatus.FAILED and (
                not report.attempts
                or report.attempts[-1].status != "failed"
                or report.error_code != report.attempts[-1].error_code
            ):
                raise ValueError("failed stage requires a real failed attempt with matching error")
            if status in {StageStatus.SKIPPED_BY_CONFIG, StageStatus.SKIPPED_BY_INTENT} and (
                report.attempts or report.decisions or report.error_code is not None
            ):
                raise ValueError("skipped stage cannot contain model attempts")
            if status == StageStatus.COMPLETED and (
                report.error_code is not None
                or not report.attempts
                or report.attempts[-1].status != "completed"
            ):
                raise ValueError("completed stage requires a successful validated attempt")
            if len(report.attempts) > 1 and not self.degraded:
                raise ValueError("recovered optional stage requires a degradation diagnostic")
            if not self.degraded and any(
                item.reason in {"unsafe_candidate", "length_budget", "count_budget"}
                for item in report.decisions
            ):
                raise ValueError("substantive candidate rejection requires degradation diagnostics")
        if self.processing_intent == ProcessingIntent.ACQUISITION and (
            self.expansion_status != StageStatus.SKIPPED_BY_INTENT
            or self.hyde_status != StageStatus.SKIPPED_BY_INTENT
        ):
            raise ValueError("acquisition must skip both optional stages")
        if (
            self.processing_intent == ProcessingIntent.EXPLORATORY
            and StageStatus.SKIPPED_BY_INTENT in {self.expansion_status, self.hyde_status}
        ):
            raise ValueError("exploratory stages cannot be skipped by another intent")
        return self


class EnhancementInputError(RuntimeError):
    """Invalid upstream artifacts are NOT optional model failures and must stop execution."""

    def __init__(self, code: Literal["invalid_upstream", "input_budget"], message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
