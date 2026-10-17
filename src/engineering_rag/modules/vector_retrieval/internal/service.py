"""Public vector service composed from private Milvus functions."""

from __future__ import annotations

from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.retrieval import (
    DeleteResult,
    IndexRequest,
    IndexResult,
    RetrievalResult,
    VectorSearchRequest,
)

from .config import VectorRetrievalConfig
from .embeddings import EmbeddingProvider
from .indexer import index_batch, quote
from .milvus_client import MilvusClientProtocol, translated_milvus_error
from .searcher import search_chunks


class MilvusVectorRetrievalService:
    """Real Milvus implementation of the public ``VectorRetrievalService`` protocol."""

    def __init__(
        self,
        client: MilvusClientProtocol,
        embedding_provider: EmbeddingProvider,
        config: VectorRetrievalConfig,
        *,
        owns_client: bool = False,
    ) -> None:
        self._client = client
        self._embedding_provider = embedding_provider
        self._config = config
        self._owns_client = owns_client

    def index(self, batch: ChunkBatch, request: IndexRequest) -> IndexResult:
        return index_batch(self._client, self._embedding_provider, self._config, batch, request)

    def search(self, request: VectorSearchRequest) -> list[RetrievalResult]:
        return search_chunks(self._client, self._embedding_provider, self._config, request)

    def delete_document(self, document_id: str, index_name: str) -> DeleteResult:
        if not document_id.strip():
            raise ValueError("document_id must not be blank")
        try:
            exists = self._client.has_collection(collection_name=index_name)
        except Exception as exc:
            raise translated_milvus_error(
                exc, f"failed to inspect collection {index_name!r}"
            ) from exc
        if not exists:
            return DeleteResult(
                index_name=index_name,
                document_id=document_id,
                deleted_count=0,
                index_existed=False,
            )
        try:
            matching = self._client.query(
                collection_name=index_name,
                filter=f"document_id == {quote(document_id)}",
                output_fields=["chunk_id"],
                limit=16384,
                consistency_level="Strong",
            )
            self._client.delete(
                collection_name=index_name,
                filter=f"document_id == {quote(document_id)}",
            )
        except Exception as exc:
            raise translated_milvus_error(
                exc, f"failed to delete document {document_id!r} from {index_name!r}"
            ) from exc
        return DeleteResult(
            index_name=index_name,
            document_id=document_id,
            deleted_count=len(matching),
            index_existed=True,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> MilvusVectorRetrievalService:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
