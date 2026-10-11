"""Chunk contracts; no chunking algorithm is implemented here."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from .common import SCHEMA_VERSION, ArtifactRef, ContractModel, NonEmptyStr, PositivePage, SourceRef
from .documents import StandardMetadata


class ChunkContentType(StrEnum):
    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"
    FORMULA = "formula"
    MIXED = "mixed"


class ChunkingConfig(ContractModel):
    strategy_id: NonEmptyStr
    max_tokens: Annotated[int, Field(gt=0)]
    overlap_tokens: Annotated[int, Field(ge=0)] = 0
    options: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_overlap(self) -> "ChunkingConfig":
        if self.overlap_tokens >= self.max_tokens:
            raise ValueError("overlap_tokens must be less than max_tokens")
        return self


class Chunk(ContractModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    chunk_id: NonEmptyStr
    logical_chunk_id: NonEmptyStr
    document_id: NonEmptyStr
    content: NonEmptyStr
    context_header: str | None = None
    embedding_text: str | None = None
    content_type: ChunkContentType
    page_start: PositivePage
    page_end: PositivePage
    source_refs: list[SourceRef] = Field(min_length=1)
    standard: StandardMetadata
    section_id: NonEmptyStr | None = None
    clause_id: NonEmptyStr | None = None
    clause_number: str | None = None
    is_explanation: bool = False
    is_mandatory: bool | None = None
    parent_chunk_id: NonEmptyStr | None = None
    related_asset_ids: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_identity_and_pages(self) -> "Chunk":
        if self.chunk_id == self.logical_chunk_id:
            raise ValueError("chunk_id and logical_chunk_id represent distinct identities")
        if self.page_end < self.page_start:
            raise ValueError("chunk page_end must not precede page_start")
        if any(ref.document_id != self.document_id for ref in self.source_refs):
            raise ValueError("all chunk sources must belong to document_id")
        return self


class ChunkBatch(ContractModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    document_id: NonEmptyStr
    chunks: list[Chunk] = Field(default_factory=list)
    chunking_version: NonEmptyStr
    strategy_id: NonEmptyStr
    source_document_artifact: ArtifactRef | None = None

    @model_validator(mode="after")
    def validate_chunk_documents(self) -> "ChunkBatch":
        if any(chunk.document_id != self.document_id for chunk in self.chunks):
            raise ValueError("all chunks must belong to batch document_id")
        if len({chunk.chunk_id for chunk in self.chunks}) != len(self.chunks):
            raise ValueError("chunk_id must be unique within a batch")
        return self
