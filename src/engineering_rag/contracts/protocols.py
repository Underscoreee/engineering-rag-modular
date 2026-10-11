"""All public capability protocols for dependency injection."""

from collections.abc import Mapping
from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO, Protocol, runtime_checkable

from .answers import AnswerResult, GenerationRequest
from .chunks import ChunkBatch, ChunkingConfig
from .common import ArtifactRef, FileRef, NonEmptyStr, TraceContext
from .documents import Document, ParseRequest
from .evaluation import EvaluationReport, EvaluationRequest
from .queries import QueryRequest, QueryResult, RetrievalPlan
from .retrieval import (
    DeleteResult,
    HybridSearchRequest,
    IndexRequest,
    IndexResult,
    KeywordSearchRequest,
    RetrievalResult,
    VectorSearchRequest,
)
from .tasks import IngestionRequest, QuestionRequest, TaskRecord


@runtime_checkable
class DocumentParser(Protocol):
    def parse(self, request: ParseRequest) -> Document: ...


@runtime_checkable
class ChunkingService(Protocol):
    def chunk(self, document: Document, config: ChunkingConfig) -> ChunkBatch: ...


@runtime_checkable
class KeywordRetrievalService(Protocol):
    def index(self, batch: ChunkBatch, request: IndexRequest) -> IndexResult: ...
    def search(self, request: KeywordSearchRequest) -> list[RetrievalResult]: ...
    def delete_document(self, document_id: str, index_name: str) -> DeleteResult: ...


@runtime_checkable
class VectorRetrievalService(Protocol):
    def index(self, batch: ChunkBatch, request: IndexRequest) -> IndexResult: ...
    def search(self, request: VectorSearchRequest) -> list[RetrievalResult]: ...
    def delete_document(self, document_id: str, index_name: str) -> DeleteResult: ...


@runtime_checkable
class HybridRetrievalService(Protocol):
    def search(self, request: HybridSearchRequest) -> list[RetrievalResult]: ...


@runtime_checkable
class QueryService(Protocol):
    def plan(self, request: QueryRequest) -> RetrievalPlan: ...
    def execute(self, request: QueryRequest) -> QueryResult: ...


@runtime_checkable
class GenerationService(Protocol):
    def generate(self, request: GenerationRequest) -> AnswerResult: ...


@runtime_checkable
class FileStore(Protocol):
    def put(self, source: Path | BinaryIO, *, media_type: str) -> FileRef: ...
    def read(self, reference: FileRef | ArtifactRef) -> AbstractContextManager[BinaryIO]: ...
    def exists(self, reference: FileRef | ArtifactRef) -> bool: ...
    def delete(self, reference: FileRef | ArtifactRef) -> bool: ...


@runtime_checkable
class Orchestrator(Protocol):
    def run_ingestion(self, request: IngestionRequest) -> TaskRecord: ...
    def run_question(self, request: QuestionRequest) -> AnswerResult: ...


@runtime_checkable
class EvaluationService(Protocol):
    def evaluate(self, request: EvaluationRequest) -> EvaluationReport: ...


@runtime_checkable
class Observability(Protocol):
    def log(
        self, level: str, event: str, context: TraceContext, fields: Mapping[str, object]
    ) -> None: ...
    def record_metric(self, name: str, value: float, context: TraceContext) -> None: ...
    def measure(
        self, operation: NonEmptyStr, context: TraceContext
    ) -> AbstractContextManager[None]: ...


@runtime_checkable
class ConfigProvider(Protocol):
    def get(self, key: str) -> str | None: ...
