"""使用虚构 Chunk V1 示例执行真实 Milvus 向量索引和检索。"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.retrieval import IndexRequest, VectorSearchRequest
from engineering_rag.modules.vector_retrieval.api import create_vector_retrieval_service


def main() -> None:
    batch_path = Path(__file__).with_name("chunk_batch.example.json")
    batch = ChunkBatch.model_validate_json(batch_path.read_text(encoding="utf-8"))
    collection_name = "engineering_rag_vector_example"

    # 工厂从环境读取 Milvus/模型配置；模型在首次 index 时惰性加载。
    with create_vector_retrieval_service() as service:
        indexed = service.index(
            batch,
            IndexRequest(
                index_name=collection_name,
                operation_id=f"vector-example-{uuid4().hex}",
                replace_document=True,
            ),
        )
        if indexed.failures:
            raise RuntimeError(indexed.model_dump_json(indent=2))
        results = service.search(
            VectorSearchRequest(
                query="设备检修空间",
                top_k=5,
                index_name=collection_name,
            )
        )

    # 公共结果只打印契约实际提供的身份、相似度、排名和页码引用。
    print(
        json.dumps(
            [
                {
                    "chunk_id": result.chunk_id,
                    "score": result.score,
                    "rank": result.rank,
                    "document_id": result.document_id,
                    "clause_number": result.clause_number,
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
