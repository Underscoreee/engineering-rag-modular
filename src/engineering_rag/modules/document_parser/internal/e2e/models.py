"""Strict private run and checkpoint models for Task 1.6."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class PrivateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RunMode(StrEnum):
    LIVE_MINERU = "live_mineru"
    REPLAY_SAVED_RAW = "replay_saved_raw"
    SYNTHETIC = "synthetic"


class RunStatus(StrEnum):
    PLANNED = "planned"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class SourceIdentity(PrivateModel):
    document_id: str = Field(min_length=1)
    file_id: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    page_count: int = Field(gt=0)
    standard_code: str = Field(min_length=1)
    edition: str | None = None
    revision: str | None = None
    bbox_unit: str = "pdf_points"
    bbox_origin: str = "top_left"
    schema_version: str = "2.4"


class BatchPlan(PrivateModel):
    batch_id: str = Field(min_length=1)
    pages: list[int] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_pages(self) -> BatchPlan:
        if self.pages != sorted(set(self.pages)) or self.pages[0] < 1:
            raise ValueError("batch pages must be unique, ascending, and 1-based")
        return self


class BatchState(PrivateModel):
    batch_id: str
    pages: list[int]
    status: RunStatus = RunStatus.PLANNED
    attempts: int = Field(default=0, ge=0)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    document_path: str | None = None
    document_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    artifact_sha256: dict[str, str] = Field(default_factory=dict)
    error: str | None = None
    elapsed_seconds: float | None = Field(default=None, ge=0)
    peak_rss_bytes: int | None = Field(default=None, ge=0)


class RunState(PrivateModel):
    run_id: str
    mode: RunMode
    status: RunStatus
    created_at: datetime
    updated_at: datetime
    source: SourceIdentity
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    model_signature: str = Field(pattern=r"^[0-9a-f]{64}$")
    batches: list[BatchState]
    full_document_status: str = "NOT_RUN_REQUIRES_EXPLICIT_APPROVAL"
