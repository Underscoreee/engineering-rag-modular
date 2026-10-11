"""Evaluation descriptors and reproducible report contracts."""

from enum import StrEnum

from pydantic import Field

from .common import (
    SCHEMA_VERSION,
    ArtifactRef,
    ContractError,
    ContractModel,
    NonEmptyStr,
    TraceContext,
)


class EvaluationType(StrEnum):
    PARSER = "parser"
    CHUNKING = "chunking"
    RETRIEVAL = "retrieval"
    GENERATION = "generation"


class EvaluationTarget(ContractModel):
    component_id: NonEmptyStr
    component_version: NonEmptyStr
    configuration_id: NonEmptyStr | None = None


class EvaluationRequest(ContractModel):
    evaluation_type: EvaluationType
    dataset: ArtifactRef
    dataset_version: NonEmptyStr
    target: EvaluationTarget
    config: dict[str, str | int | float | bool] = Field(default_factory=dict)
    trace: TraceContext | None = None


class EvaluationMetric(ContractModel):
    name: NonEmptyStr
    value: float
    sample_count: int = Field(ge=0)


class EvaluationFailure(ContractModel):
    sample_id: NonEmptyStr
    error: ContractError


class EvaluationReport(ContractModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    evaluation_type: EvaluationType
    dataset_version: NonEmptyStr
    target: EvaluationTarget
    metrics: list[EvaluationMetric] = Field(default_factory=list)
    failures: list[EvaluationFailure] = Field(default_factory=list)
