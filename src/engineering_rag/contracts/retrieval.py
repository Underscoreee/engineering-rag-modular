"""Index maintenance and online retrieval contracts."""

from collections.abc import Mapping
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, StrictBool, field_validator, model_validator

from .chunks import ChunkContentType
from .common import SCHEMA_VERSION, ContractError, ContractModel, NonEmptyStr, PositivePage
from .documents import StandardMetadata

RETRIEVAL_RESULT_SCHEMA_VERSION = "2.0"
_SOURCE_METADATA_FIELDS = frozenset({"is_explanation", "is_mandatory", "content_type"})


class SearchFilters(ContractModel):
    document_ids: list[NonEmptyStr] = Field(default_factory=list)
    standard_codes: list[NonEmptyStr] = Field(default_factory=list)
    editions: list[NonEmptyStr] = Field(default_factory=list)
    clause_numbers: list[NonEmptyStr] = Field(default_factory=list)
    content_types: list[ChunkContentType] = Field(default_factory=list)
    is_explanation: bool | None = None
    is_mandatory: bool | None = None


class IndexRequest(ContractModel):
    index_name: NonEmptyStr
    operation_id: NonEmptyStr
    replace_document: bool = True


class IndexFailure(ContractModel):
    chunk_id: NonEmptyStr
    error: ContractError


class IndexResult(ContractModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    index_name: NonEmptyStr
    operation_id: NonEmptyStr
    attempted: Annotated[int, Field(ge=0)]
    indexed: Annotated[int, Field(ge=0)]
    failures: list[IndexFailure] = Field(default_factory=list)
    index_version: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_counts(self) -> "IndexResult":
        if self.indexed + len(self.failures) != self.attempted:
            raise ValueError("indexed plus failures must equal attempted")
        return self


class DeleteResult(ContractModel):
    schema_version: NonEmptyStr = SCHEMA_VERSION
    index_name: NonEmptyStr
    document_id: NonEmptyStr
    deleted_count: Annotated[int, Field(ge=0)]
    index_existed: bool


class KeywordSearchRequest(ContractModel):
    query: NonEmptyStr
    top_k: Annotated[int, Field(gt=0)] = 10
    filters: SearchFilters = Field(default_factory=SearchFilters)
    field_weights: dict[NonEmptyStr, Annotated[float, Field(ge=0)]] = Field(default_factory=dict)
    index_name: NonEmptyStr


class VectorSearchRequest(ContractModel):
    query: NonEmptyStr
    top_k: Annotated[int, Field(gt=0)] = 10
    filters: SearchFilters = Field(default_factory=SearchFilters)
    embedding_model_id: NonEmptyStr | None = None
    index_name: NonEmptyStr


class FusionStrategy(StrEnum):
    RECIPROCAL_RANK_FUSION = "rrf"
    WEIGHTED_NORMALIZED = "weighted_normalized"


class HybridSearchRequest(ContractModel):
    keyword: KeywordSearchRequest
    vector: VectorSearchRequest
    fusion_strategy: FusionStrategy
    keyword_weight: Annotated[float, Field(ge=0)] = 0.5
    vector_weight: Annotated[float, Field(ge=0)] = 0.5
    candidate_k: Annotated[int, Field(gt=0)] = 50
    top_k: Annotated[int, Field(gt=0)] = 10

    @model_validator(mode="after")
    def validate_fusion(self) -> "HybridSearchRequest":
        if self.top_k > self.candidate_k:
            raise ValueError("top_k must not exceed candidate_k")
        if self.fusion_strategy == FusionStrategy.WEIGHTED_NORMALIZED:
            if abs(self.keyword_weight + self.vector_weight - 1.0) > 1e-9:
                raise ValueError("weighted fusion weights must sum to 1")
        elif self.keyword_weight != 0.5 or self.vector_weight != 0.5:
            raise ValueError("RRF does not accept numeric score weights")
        return self


class RetrievalSource(StrEnum):
    KEYWORD = "keyword"
    VECTOR = "vector"
    HYBRID = "hybrid"


class RetrievalResult(ContractModel):
    schema_version: Literal["2.0"] = RETRIEVAL_RESULT_SCHEMA_VERSION
    chunk_id: NonEmptyStr
    logical_chunk_id: NonEmptyStr
    document_id: NonEmptyStr
    content: NonEmptyStr
    standard: StandardMetadata
    clause_id: NonEmptyStr | None = None
    clause_number: str | None = None
    page_start: PositivePage
    page_end: PositivePage
    score: float
    rank: Annotated[int, Field(gt=0)]
    retrieval_source: RetrievalSource
    score_type: NonEmptyStr
    index_name: NonEmptyStr
    is_explanation: StrictBool | None = None
    is_mandatory: StrictBool | None = None
    content_type: ChunkContentType | None = None

    @field_validator("content_type", mode="before")
    @classmethod
    def validate_content_type_input(cls, value: object) -> object:
        if value is not None and not isinstance(value, str):
            raise ValueError("content_type must be a ChunkContentType string or null")
        return value

    @model_validator(mode="before")
    @classmethod
    def read_legacy_evidence(cls, value: object) -> object:
        """Documented V1 read bridge; never infer unknown source attributes.

        Persisted V1 records remain read-only. New instances and all serialized
        results use V2, including evidence nested inside other public models.
        """
        if isinstance(value, Mapping) and value.get("schema_version") == "1.0":
            if _SOURCE_METADATA_FIELDS.intersection(value):
                raise ValueError("V1 retrieval records cannot contain V2 source metadata fields")
            return {**value, "schema_version": RETRIEVAL_RESULT_SCHEMA_VERSION}
        return value

    @model_validator(mode="after")
    def validate_pages(self) -> "RetrievalResult":
        if self.page_end < self.page_start:
            raise ValueError("retrieval page_end must not precede page_start")
        return self


RetrievalMode = Literal["keyword", "vector", "hybrid"]


def migrate_retrieval_result_v1(payload: Mapping[str, object]) -> RetrievalResult:
    """Explicit in-memory migration for archived V1 JSON; never overwrite a file.

    The same reader bridge is used for nested evidence. An old consumer still
    requires an upgrade: no lossy V1 writer or second production DTO is provided.
    """
    if payload.get("schema_version") != "1.0":
        raise ValueError("migration requires an explicit RetrievalResult schema_version='1.0'")
    return RetrievalResult.model_validate(dict(payload))
