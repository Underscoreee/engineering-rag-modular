"""Shared primitive contracts and public error vocabulary."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = "1.0"
NonEmptyStr = Annotated[str, Field(min_length=1)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
PositivePage = Annotated[int, Field(ge=1)]


class ContractModel(BaseModel):
    """Strict base for all cross-module models."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    NOT_FOUND = "not_found"
    UNSUPPORTED = "unsupported"
    CONFLICT = "conflict"
    INTERNAL = "internal"


class ContractError(ContractModel):
    code: ErrorCode
    message: NonEmptyStr
    field: str | None = None
    retryable: bool = False


class FileRef(ContractModel):
    file_id: NonEmptyStr
    uri: NonEmptyStr
    mime_type: NonEmptyStr
    sha256: Sha256 | None = None
    size_bytes: Annotated[int, Field(ge=0)] | None = None


class ArtifactRef(ContractModel):
    artifact_id: NonEmptyStr
    artifact_type: NonEmptyStr
    uri: NonEmptyStr
    media_type: NonEmptyStr
    schema_version: NonEmptyStr = SCHEMA_VERSION
    artifact_version: NonEmptyStr


class BoundingBox(ContractModel):
    x_min: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    y_min: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    x_max: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    y_max: Annotated[float, Field(ge=0, allow_inf_nan=False)]

    @model_validator(mode="after")
    def validate_order(self) -> "BoundingBox":
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("bbox max coordinates must be greater than min coordinates")
        return self


class SourceRef(ContractModel):
    document_id: NonEmptyStr
    page_number: PositivePage
    block_id: NonEmptyStr | None = None
    bbox: BoundingBox | None = None


class SourceSpan(ContractModel):
    start: SourceRef
    end: SourceRef

    @model_validator(mode="after")
    def validate_span(self) -> "SourceSpan":
        if self.start.document_id != self.end.document_id:
            raise ValueError("source span endpoints must belong to one document")
        if self.end.page_number < self.start.page_number:
            raise ValueError("source span end page must not precede start page")
        return self


class TraceContext(ContractModel):
    trace_id: NonEmptyStr
    task_id: NonEmptyStr | None = None
