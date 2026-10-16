"""Stable Chunk V1 contracts produced from Document V2.4."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .common import ArtifactRef, ContractModel, NonEmptyStr, PositivePage, SourceRef
from .documents import StandardMetadata

CHUNK_SCHEMA_VERSION = "1.0"


class ChunkContentType(StrEnum):
    CLAUSE = "clause"
    PARAGRAPH = "paragraph"
    TEXT = "text"
    TABLE = "table"
    FIGURE = "figure"
    FORMULA = "formula"
    MIXED = "mixed"


class ChunkingConfig(ContractModel):
    strategy_id: NonEmptyStr
    max_tokens: Annotated[int, Field(gt=0)] = 800
    overlap_tokens: Annotated[int, Field(ge=0)] = 0
    options: dict[str, str | int | float | bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_overlap(self) -> "ChunkingConfig":
        if self.overlap_tokens != 0:
            raise ValueError("Chunk V1 requires overlap_tokens=0")
        if self.overlap_tokens >= self.max_tokens:
            raise ValueError("overlap_tokens must be less than max_tokens")
        return self


class Chunk(ContractModel):
    schema_version: Literal["1.0"] = CHUNK_SCHEMA_VERSION
    chunk_id: NonEmptyStr
    logical_chunk_id: NonEmptyStr
    document_id: NonEmptyStr
    content: NonEmptyStr
    context_header: NonEmptyStr | None = None
    embedding_text: NonEmptyStr
    token_count: Annotated[int, Field(gt=0)]
    content_type: ChunkContentType
    page_start: PositivePage
    page_end: PositivePage
    source_refs: list[SourceRef] = Field(min_length=1)
    source_block_ids: list[NonEmptyStr] = Field(min_length=1)
    standard: StandardMetadata
    section_path: list[NonEmptyStr] = Field(default_factory=list)
    section_id: NonEmptyStr | None = None
    clause_id: NonEmptyStr | None = None
    clause_number: NonEmptyStr | None = None
    is_explanation: bool = False
    is_mandatory: bool | None = None
    parent_chunk_id: NonEmptyStr | None = None
    table_id: NonEmptyStr | None = None
    figure_id: NonEmptyStr | None = None
    formula_ids: list[NonEmptyStr] = Field(default_factory=list)
    related_asset_ids: list[NonEmptyStr] = Field(default_factory=list)
    chunking_version: NonEmptyStr
    exceeds_max_tokens: bool = False

    @model_validator(mode="after")
    def validate_identity_and_pages(self) -> "Chunk":
        if self.chunk_id == self.logical_chunk_id:
            raise ValueError("chunk_id and logical_chunk_id represent distinct identities")
        if self.page_end < self.page_start:
            raise ValueError("chunk page_end must not precede page_start")
        if any(ref.document_id != self.document_id for ref in self.source_refs):
            raise ValueError("all chunk sources must belong to document_id")
        if any(ref.block_id is None for ref in self.source_refs):
            raise ValueError("all chunk sources must identify a block")
        referenced_blocks = [ref.block_id for ref in self.source_refs if ref.block_id is not None]
        if referenced_blocks != self.source_block_ids:
            raise ValueError("source_block_ids must match ordered source_refs block identities")
        if len(set(self.source_block_ids)) != len(self.source_block_ids):
            raise ValueError("source_block_ids must be unique")
        source_pages = [ref.page_number for ref in self.source_refs]
        if (self.page_start, self.page_end) != (min(source_pages), max(source_pages)):
            raise ValueError("chunk page range must match source_refs")
        expected_embedding = (
            f"{self.context_header}\n\n{self.content}" if self.context_header else self.content
        )
        if self.embedding_text != expected_embedding:
            raise ValueError("embedding_text must be context_header + blank line + content")
        if self.content_type == ChunkContentType.TABLE:
            if self.table_id is None:
                raise ValueError("table chunk requires table_id")
        elif self.table_id is not None:
            raise ValueError("table_id belongs only to table chunks")
        if self.content_type == ChunkContentType.FORMULA:
            if not self.formula_ids:
                raise ValueError("formula chunk requires formula_ids")
        elif self.formula_ids:
            raise ValueError("formula_ids belong only to formula chunks")
        if len(set(self.formula_ids)) != len(self.formula_ids):
            raise ValueError("formula_ids must be unique")
        if len(set(self.related_asset_ids)) != len(self.related_asset_ids):
            raise ValueError("related_asset_ids must be unique")
        if self.content_type == ChunkContentType.FIGURE:
            if self.figure_id is None:
                raise ValueError("figure chunk requires figure_id")
        elif self.figure_id is not None:
            raise ValueError("figure_id belongs only to figure chunks")
        return self


class ChunkBatch(ContractModel):
    schema_version: Literal["1.0"] = CHUNK_SCHEMA_VERSION
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
        if any(chunk.chunking_version != self.chunking_version for chunk in self.chunks):
            raise ValueError("chunk chunking_version must match its batch")
        chunk_ids = {chunk.chunk_id for chunk in self.chunks}
        if any(
            chunk.parent_chunk_id is not None and chunk.parent_chunk_id not in chunk_ids
            for chunk in self.chunks
        ):
            raise ValueError("parent_chunk_id must reference a chunk in the same batch")
        return self
