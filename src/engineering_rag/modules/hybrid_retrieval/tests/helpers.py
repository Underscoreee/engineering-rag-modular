from __future__ import annotations

from dataclasses import dataclass, field

from engineering_rag.contracts.documents import StandardMetadata
from engineering_rag.contracts.retrieval import (
    KeywordSearchRequest,
    RetrievalResult,
    RetrievalSource,
    VectorSearchRequest,
)


def make_result(
    chunk_id: str,
    *,
    source: RetrievalSource,
    score: float,
    rank: int = 1,
    content: str | None = None,
    logical_chunk_id: str | None = None,
    document_id: str = "doc-1",
    page_start: int = 3,
    page_end: int = 3,
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=chunk_id,
        logical_chunk_id=logical_chunk_id or f"logical-{chunk_id}",
        document_id=document_id,
        content=content or f"content {chunk_id}",
        standard=StandardMetadata(
            standard_name="虚构工程标准",
            standard_code="GB/T 00000-2026",
            edition="演示版",
            language="zh-CN",
        ),
        clause_id=f"clause-{chunk_id}",
        clause_number="4.2.1",
        page_start=page_start,
        page_end=page_end,
        score=score,
        rank=rank,
        retrieval_source=source,
        score_type="bm25" if source == RetrievalSource.KEYWORD else "cosine_similarity",
        index_name="keyword-index" if source == RetrievalSource.KEYWORD else "vector-index",
    )


@dataclass
class FakeKeywordService:
    results: list[RetrievalResult]
    requests: list[KeywordSearchRequest] = field(default_factory=list)
    error: Exception | None = None

    def search(self, request: KeywordSearchRequest) -> list[RetrievalResult]:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return list(self.results)


@dataclass
class FakeVectorService:
    results: list[RetrievalResult]
    requests: list[VectorSearchRequest] = field(default_factory=list)
    error: Exception | None = None

    def search(self, request: VectorSearchRequest) -> list[RetrievalResult]:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return list(self.results)
