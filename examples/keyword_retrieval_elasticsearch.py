"""Index and search the fictitious Chunk V1 example with Elasticsearch 8.x."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.retrieval import IndexRequest, KeywordSearchRequest
from engineering_rag.modules.keyword_retrieval.api import (
    ElasticsearchKeywordConfig,
    create_keyword_retrieval_service,
)


def main() -> None:
    batch_path = Path(__file__).with_name("chunk_batch.example.json")
    batch = ChunkBatch.model_validate_json(batch_path.read_text(encoding="utf-8"))
    config = ElasticsearchKeywordConfig.from_env()

    with create_keyword_retrieval_service(config) as service:
        indexed = service.index(
            batch,
            IndexRequest(
                index_name=config.default_index,
                operation_id=f"example-{uuid4().hex}",
                replace_document=True,
            ),
        )
        if indexed.failures:
            raise RuntimeError(indexed.model_dump_json(indent=2))

        results = service.search(
            KeywordSearchRequest(
                query="检修空间",
                top_k=5,
                index_name=config.default_index,
            )
        )
        print(
            json.dumps(
                [
                    {
                        "chunk_id": result.chunk_id,
                        "score": result.score,
                        "rank": result.rank,
                        "document_id": result.document_id,
                        "page_start": result.page_start,
                        "page_end": result.page_end,
                    }
                    for result in results
                ],
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    main()
