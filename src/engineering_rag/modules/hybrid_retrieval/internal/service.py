"""Sequential hybrid orchestration through injected public retrieval Protocols."""

from __future__ import annotations

from engineering_rag.contracts.protocols import (
    KeywordRetrievalService,
    VectorRetrievalService,
)
from engineering_rag.contracts.retrieval import (
    FusionStrategy,
    HybridSearchRequest,
    RetrievalResult,
    RetrievalSource,
)

from .candidate_merger import merge_candidates
from .config import HybridRetrievalConfig
from .errors import FusionParameterError
from .fusion import ScoredCandidate, min_max_weighted_fusion, reciprocal_rank_fusion


class DefaultHybridRetrievalService:
    """Call keyword then vector retrieval and deterministically fuse their candidates."""

    def __init__(
        self,
        keyword_service: KeywordRetrievalService,
        vector_service: VectorRetrievalService,
        config: HybridRetrievalConfig | None = None,
    ) -> None:
        self._keyword_service = keyword_service
        self._vector_service = vector_service
        self._config = config or HybridRetrievalConfig()

    def search(self, request: HybridSearchRequest) -> list[RetrievalResult]:
        validated = HybridSearchRequest.model_validate(request.model_dump(mode="json"))
        keyword_request = validated.keyword.model_copy(update={"top_k": validated.candidate_k})
        vector_request = validated.vector.model_copy(update={"top_k": validated.candidate_k})

        keyword_results = self._keyword_service.search(keyword_request)
        vector_results = self._vector_service.search(vector_request)
        candidates = merge_candidates(keyword_results, vector_results)
        if not candidates:
            return []

        if validated.fusion_strategy == FusionStrategy.RECIPROCAL_RANK_FUSION:
            scored = reciprocal_rank_fusion(
                candidates,
                keyword_weight=validated.keyword_weight,
                vector_weight=validated.vector_weight,
                rrf_k=self._config.rrf_k,
            )
            score_type = "rrf"
        elif validated.fusion_strategy == FusionStrategy.WEIGHTED_NORMALIZED:
            scored = min_max_weighted_fusion(
                candidates,
                keyword_weight=validated.keyword_weight,
                vector_weight=validated.vector_weight,
            )
            score_type = "min_max_weighted_sum"
        else:  # pragma: no cover - strict public enum prevents this path.
            raise FusionParameterError(f"unsupported fusion strategy {validated.fusion_strategy!r}")

        hybrid_index = (
            f"hybrid(keyword={validated.keyword.index_name};vector={validated.vector.index_name})"
        )
        return [
            _to_result(item, rank=rank, score_type=score_type, index_name=hybrid_index)
            for rank, item in enumerate(scored[: validated.top_k], start=1)
        ]


def _to_result(
    item: ScoredCandidate,
    *,
    rank: int,
    score_type: str,
    index_name: str,
) -> RetrievalResult:
    source = item.candidate.result
    return RetrievalResult.model_validate(
        source.model_copy(
            update={
                "score": item.score,
                "rank": rank,
                "retrieval_source": RetrievalSource.HYBRID,
                "score_type": score_type,
                "index_name": index_name,
            }
        ).model_dump(mode="json")
    )
