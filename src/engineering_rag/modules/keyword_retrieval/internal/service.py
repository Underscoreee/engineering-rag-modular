"""Public-service implementation composed from private Elasticsearch functions."""

from __future__ import annotations

from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.retrieval import (
    DeleteResult,
    IndexRequest,
    IndexResult,
    KeywordSearchRequest,
    RetrievalResult,
)

from .client import (
    ElasticsearchClient,
    exception_status,
    refresh_as_bool,
    translated_backend_error,
)
from .config import ElasticsearchKeywordConfig
from .errors import KeywordResponseError
from .indexer import index_batch, validate_delete_by_query_response
from .searcher import search_chunks


class ElasticsearchKeywordRetrievalService:
    """Real Elasticsearch implementation of ``KeywordRetrievalService``."""

    def __init__(
        self,
        client: ElasticsearchClient,
        config: ElasticsearchKeywordConfig,
        *,
        owns_client: bool = False,
    ) -> None:
        self._client = client
        self._config = config
        self._owns_client = owns_client

    def index(self, batch: ChunkBatch, request: IndexRequest) -> IndexResult:
        return index_batch(self._client, self._config, batch, request)

    def search(self, request: KeywordSearchRequest) -> list[RetrievalResult]:
        return search_chunks(self._client, self._config, request)

    def delete_document(self, document_id: str, index_name: str) -> DeleteResult:
        if not document_id.strip():
            raise ValueError("document_id must not be blank")
        try:
            exists = bool(self._client.indices.exists(index=index_name))
        except Exception as exc:
            raise translated_backend_error(exc, f"failed to inspect index {index_name!r}") from exc
        if not exists:
            return DeleteResult(
                index_name=index_name,
                document_id=document_id,
                deleted_count=0,
                index_existed=False,
            )
        try:
            response = self._client.delete_by_query(
                index=index_name,
                query={"term": {"document_id": document_id}},
                refresh=refresh_as_bool(self._config.refresh),
                conflicts="abort",
            )
        except Exception as exc:
            if exception_status(exc) == 404:
                return DeleteResult(
                    index_name=index_name,
                    document_id=document_id,
                    deleted_count=0,
                    index_existed=False,
                )
            raise translated_backend_error(
                exc,
                f"failed to delete document {document_id!r} from {index_name!r}",
            ) from exc
        body = validate_delete_by_query_response(response, operation="delete_by_query")
        deleted = body.get("deleted")
        if not isinstance(deleted, int) or isinstance(deleted, bool) or deleted < 0:
            raise KeywordResponseError("delete_by_query response has invalid deleted count")
        return DeleteResult(
            index_name=index_name,
            document_id=document_id,
            deleted_count=deleted,
            index_existed=True,
        )

    def close(self) -> None:
        """Close only clients created by the module factory."""

        if self._owns_client:
            self._client.close()

    def __enter__(self) -> ElasticsearchKeywordRetrievalService:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()
