"""Index maintenance and online retrieval contracts."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .chunks import ChunkContentType
from .common import SCHEMA_VERSION, ContractError, ContractModel, NonEmptyStr, PositivePage
from .documents import StandardMetadata


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
    schema_version: NonEmptyStr = SCHEMA_VERSION
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

    @model_validator(mode="after")
    def validate_pages(self) -> "RetrievalResult":
        if self.page_end < self.page_start:
            raise ValueError("retrieval page_end must not precede page_start")
        return self


RetrievalMode = Literal["keyword", "vector", "hybrid"]
