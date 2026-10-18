"""Deployment-owned planning settings and local stage injection boundaries."""

from typing import Annotated, Literal, Protocol

from pydantic import Field, model_validator

from engineering_rag.contracts.catalog import CatalogIndexScope
from engineering_rag.contracts.queries import QueryRequest
from engineering_rag.contracts.retrieval import FusionStrategy

from .config import UnderstandingConfig
from .enhancement_models import EnhancementConfig, QueryEnhancementResult
from .models import PrivateModel, UnderstandingResult
from .rewrite_models import RewriteConfig, RewriteResult

PositiveInt = Annotated[int, Field(gt=0)]
Weight = Annotated[float, Field(ge=0, allow_inf_nan=False)]


class PlanningConfig(PrivateModel):
    scope: CatalogIndexScope
    candidate_k: PositiveInt = 50
    # Deployment budgets, NOT backend discovery. Defaults fit current backend defaults
    # (keyword max_top_k=100; vector max_top_k=100 and HNSW search_ef=64).
    keyword_candidate_limit: PositiveInt = 100
    vector_candidate_limit: PositiveInt = 64
    fusion_strategy: FusionStrategy = FusionStrategy.RECIPROCAL_RANK_FUSION
    keyword_weight: Weight = 0.5
    vector_weight: Weight = 0.5
    embedding_model_id: Annotated[str, Field(min_length=1, pattern=r"\S")] | None = None
    max_keyword_chars: PositiveInt = 8192
    max_vector_chars: PositiveInt = 8192
    max_keyword_synonyms: Annotated[int, Field(ge=0, le=8)] = 4
    max_synonym_chars: PositiveInt = 64

    @model_validator(mode="after")
    def check_deployment(self) -> "PlanningConfig":
        if not self.scope.keyword_index.strip() or not self.scope.vector_collection.strip():
            raise ValueError("both deployment index names must be nonblank")
        if self.candidate_k > min(self.keyword_candidate_limit, self.vector_candidate_limit):
            raise ValueError("candidate_k exceeds declared backend budgets")
        if self.fusion_strategy == FusionStrategy.RECIPROCAL_RANK_FUSION:
            if self.keyword_weight != 0.5 or self.vector_weight != 0.5:
                raise ValueError("RRF only accepts public weights 0.5/0.5")
        elif abs(self.keyword_weight + self.vector_weight - 1.0) > 1e-9:
            raise ValueError("weighted_normalized weights must sum to 1")
        return self


class QueryConfig(PrivateModel):
    """Factory configuration, reusing rather than duplicating existing stage settings."""

    understanding: UnderstandingConfig
    rewrite: RewriteConfig
    enhancement: EnhancementConfig
    planning: PlanningConfig

    @model_validator(mode="after")
    def check_scope(self) -> "QueryConfig":
        if self.understanding.scope != self.planning.scope:
            raise ValueError("Understanding catalog scope must equal retrieval deployment scope")
        return self


class UnderstandingStage(Protocol):
    def understand(self, request: QueryRequest) -> UnderstandingResult: ...


class RewriteStage(Protocol):
    def rewrite(
        self, request: QueryRequest, understanding: UnderstandingResult
    ) -> RewriteResult: ...


class EnhancementStage(Protocol):
    def enhance(
        self,
        request: QueryRequest,
        understanding: UnderstandingResult,
        rewrite: RewriteResult,
    ) -> QueryEnhancementResult: ...


class QueryPlanningError(RuntimeError):
    """Local orchestration failures; upstream/backend exceptions retain their own types."""

    def __init__(
        self,
        code: Literal[
            "unsupported_mode", "invalid_parameters", "invalid_upstream", "invalid_result"
        ],
        message: str,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
