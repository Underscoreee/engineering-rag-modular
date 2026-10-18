"""Run RRF and Min-Max hybrid search against already indexed example data."""

from __future__ import annotations

import json
from collections.abc import Sequence

from engineering_rag.contracts.retrieval import (
    FusionStrategy,
    HybridSearchRequest,
    KeywordSearchRequest,
    RetrievalResult,
    VectorSearchRequest,
)
from engineering_rag.modules.hybrid_retrieval.api import create_hybrid_retrieval_service
from engineering_rag.modules.keyword_retrieval.api import (
    ElasticsearchKeywordConfig,
    create_keyword_retrieval_service,
)
from engineering_rag.modules.vector_retrieval.api import (
    VectorRetrievalConfig,
    create_vector_retrieval_service,
)


def _request(
    keyword_index: str,
    vector_collection: str,
    *,
    strategy: FusionStrategy,
    keyword_weight: float = 0.5,
    vector_weight: float = 0.5,
) -> HybridSearchRequest:
    query = "设备基础周围应保留哪些检修空间？"
    return HybridSearchRequest(
        keyword=KeywordSearchRequest(query=query, top_k=10, index_name=keyword_index),
        vector=VectorSearchRequest(query=query, top_k=10, index_name=vector_collection),
        fusion_strategy=strategy,
        keyword_weight=keyword_weight,
        vector_weight=vector_weight,
        candidate_k=50,
        top_k=5,
    )


def _print_results(label: str, results: Sequence[RetrievalResult]) -> None:
    rows = [
        {
            "rank": result.rank,
            "score": result.score,
            "score_type": result.score_type,
            "chunk_id": result.chunk_id,
            "document_id": result.document_id,
            "clause_number": result.clause_number,
            "page_start": result.page_start,
            "page_end": result.page_end,
            "content": result.content,
        }
        for result in results
    ]
    print(label)
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def main() -> None:
    keyword_config = ElasticsearchKeywordConfig.from_env()
    vector_config = VectorRetrievalConfig.from_env()

    # 两个后端必须预先索引同一个 ChunkBatch；本示例只执行在线检索和融合。
    with (
        create_keyword_retrieval_service(keyword_config) as keyword_service,
        create_vector_retrieval_service(vector_config) as vector_service,
    ):
        hybrid = create_hybrid_retrieval_service(keyword_service, vector_service)
        rrf = hybrid.search(
            _request(
                keyword_config.default_index,
                vector_config.default_collection,
                strategy=FusionStrategy.RECIPROCAL_RANK_FUSION,
            )
        )
        weighted = hybrid.search(
            _request(
                keyword_config.default_index,
                vector_config.default_collection,
                strategy=FusionStrategy.WEIGHTED_NORMALIZED,
                keyword_weight=0.6,
                vector_weight=0.4,
            )
        )

    _print_results("RRF", rrf)
    _print_results("Min-Max weighted sum", weighted)


if __name__ == "__main__":
    main()
