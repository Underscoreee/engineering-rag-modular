"""Explicit, offline V1-to-V2 query DTO migrations without intent inference."""

from collections.abc import Mapping
from typing import Literal

from pydantic import Field, TypeAdapter, model_validator

from .common import ContractModel, NonEmptyStr
from .queries import ProcessingIntent, QueryIntent, QueryResult, RetrievalPlan
from .retrieval import HybridSearchRequest, RetrievalMode, RetrievalResult


class _LegacyRetrievalPlan(ContractModel):
    """Strict reader for the V1 shape; never guesses the new processing intent."""

    schema_version: Literal["1.0"] = "1.0"
    original_question: NonEmptyStr
    rewritten_queries: list[NonEmptyStr] = Field(default_factory=list)
    hypothetical_document: str | None = None
    intent: QueryIntent = QueryIntent.UNKNOWN
    retrieval_mode: RetrievalMode
    hybrid_request: HybridSearchRequest | None = None

    @model_validator(mode="after")
    def validate_mode_request(self) -> "_LegacyRetrievalPlan":
        if (self.retrieval_mode == "hybrid") != (self.hybrid_request is not None):
            raise ValueError("legacy retrieval mode and hybrid_request disagree")
        return self


class _LegacyQueryResult(ContractModel):
    schema_version: Literal["1.0"] = "1.0"
    plan: _LegacyRetrievalPlan
    evidence: list[RetrievalResult] = Field(default_factory=list)


def migrate_retrieval_plan_v1(
    payload: Mapping[str, object], *, processing_intent: ProcessingIntent
) -> RetrievalPlan:
    """Validate V1 data and require a caller-provided processing decision."""

    legacy = _LegacyRetrievalPlan.model_validate(dict(payload))
    intent = TypeAdapter(ProcessingIntent).validate_python(processing_intent)
    return RetrievalPlan.model_validate(
        {
            **legacy.model_dump(mode="json", exclude={"schema_version"}),
            "schema_version": "2.0",
            "processing_intent": intent,
        }
    )


def migrate_query_result_v1(
    payload: Mapping[str, object], *, processing_intent: ProcessingIntent
) -> QueryResult:
    """Migrate the enclosing result and plan together, preserving evidence."""

    legacy = _LegacyQueryResult.model_validate(dict(payload))
    plan = migrate_retrieval_plan_v1(
        legacy.plan.model_dump(mode="json"), processing_intent=processing_intent
    )
    return QueryResult(plan=plan, evidence=legacy.evidence)
