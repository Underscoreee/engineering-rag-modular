"""Query planning and execution result contracts."""

from enum import StrEnum

from pydantic import Field, model_validator

from .common import SCHEMA_VERSION, ContractModel, NonEmptyStr, TraceContext
from .retrieval import HybridSearchRequest, RetrievalMode, RetrievalResult, SearchFilters


class ConversationRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"


class ConversationTurn(ContractModel):
    role: ConversationRole
    content: NonEmptyStr


class QueryOptions(ContractModel):
    mode: RetrievalMode = "hybrid"
    top_k: int = Field(default=10, gt=0)


class QueryRequest(ContractModel):
    question: NonEmptyStr
    history: list[ConversationTurn] = Field(default_factory=list)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    options: QueryOptions = Field(default_factory=QueryOptions)
    trace: TraceContext | None = None


class QueryIntent(StrEnum):
    FACT_LOOKUP = "fact_lookup"
    REQUIREMENT = "requirement"
    COMPARISON = "comparison"
    EXPLANATION = "explanation"
    UNKNOWN = "unknown"


class RetrievalPlan(ContractModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    original_question: NonEmptyStr
    rewritten_queries: list[NonEmptyStr] = Field(default_factory=list)
    hypothetical_document: str | None = None
    intent: QueryIntent = QueryIntent.UNKNOWN
    retrieval_mode: RetrievalMode
    hybrid_request: HybridSearchRequest | None = None

    @model_validator(mode="after")
    def validate_mode_request(self) -> "RetrievalPlan":
        if self.retrieval_mode == "hybrid" and self.hybrid_request is None:
            raise ValueError("hybrid retrieval mode requires hybrid_request")
        if self.retrieval_mode != "hybrid" and self.hybrid_request is not None:
            raise ValueError("hybrid_request is only valid for hybrid retrieval mode")
        return self


class QueryResult(ContractModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    plan: RetrievalPlan
    evidence: list[RetrievalResult] = Field(default_factory=list)
