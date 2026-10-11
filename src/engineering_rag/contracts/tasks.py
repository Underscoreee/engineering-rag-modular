"""Orchestration request and task lifecycle contracts."""

from datetime import datetime
from enum import StrEnum

from pydantic import Field, model_validator

from .answers import GenerationConfig
from .chunks import ChunkingConfig
from .common import (
    SCHEMA_VERSION,
    ArtifactRef,
    ContractError,
    ContractModel,
    NonEmptyStr,
    TraceContext,
)
from .documents import ParseRequest
from .queries import QueryRequest
from .retrieval import IndexRequest


class TaskType(StrEnum):
    INGESTION = "ingestion"
    QUESTION = "question"
    EVALUATION = "evaluation"


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskRecord(ContractModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    task_id: NonEmptyStr
    task_type: TaskType
    status: TaskStatus
    current_stage: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    errors: list[ContractError] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> "TaskRecord":
        terminal = {TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}
        if self.status in terminal and self.finished_at is None:
            raise ValueError("terminal tasks require finished_at")
        if self.status == TaskStatus.FAILED and not self.errors:
            raise ValueError("failed tasks require at least one error")
        if self.started_at and self.started_at < self.created_at:
            raise ValueError("started_at must not precede created_at")
        if self.finished_at and self.started_at and self.finished_at < self.started_at:
            raise ValueError("finished_at must not precede started_at")
        return self


class IngestionRequest(ContractModel):
    parse: ParseRequest
    chunking: ChunkingConfig
    keyword_index: IndexRequest
    vector_index: IndexRequest
    trace: TraceContext | None = None


class QuestionRequest(ContractModel):
    query: QueryRequest
    generation: GenerationConfig | None = None
    trace: TraceContext | None = None
