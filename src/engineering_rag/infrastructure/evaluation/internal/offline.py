"""Explicit fictional demo composition, never a production backend or a gold labeler.

The fixed fixture responses/ordering do not read queries.jsonl or qrels.jsonl.
They verify interfaces and metric arithmetic, NOT engineering relevance or LLM quality.
Only public business APIs are imported at this composition boundary.
"""

from __future__ import annotations

import hashlib
import re

from engineering_rag.contracts.catalog import (
    CatalogIndexScope,
    StandardMetadataLookup,
    StandardMetadataMatch,
    StandardMetadataRecord,
)
from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.llm import (
    StructuredLLMConfig,
    StructuredLLMRequest,
    StructuredLLMResponse,
)
from engineering_rag.contracts.protocols import (
    HybridRetrievalService,
    QueryService,
    StructuredLLMClient,
)
from engineering_rag.contracts.retrieval import (
    KeywordSearchRequest,
    RetrievalResult,
    RetrievalSource,
    VectorSearchRequest,
)
from engineering_rag.modules.hybrid_retrieval.api import create_hybrid_retrieval_service
from engineering_rag.modules.query.api import (
    EnhancementConfig,
    PlanningConfig,
    QueryConfig,
    RewriteConfig,
    UnderstandingConfig,
    create_query_service,
)

from .dataset import chunk_matches_filters
from .run_models import EvaluationRuntime, RunConfig, Variant


class FixtureModel:
    """Rule-based test double; not a real intent classifier or model."""

    def generate(self, request: StructuredLLMRequest) -> StructuredLLMResponse:
        inputs = request.input
        if request.stage == "query_understanding":
            question = inputs["question"]
            match = re.search(r"DEMO \d+-\d+", question)
            standards = (
                [
                    {
                        "standard_code": {
                            "value": match.group(),
                            "evidence": {
                                "source": "question",
                                "history_index": None,
                                "start": match.start(),
                                "end": match.end(),
                                "quote": match.group(),
                            },
                        }
                    }
                ]
                if match
                else []
            )
            data = {
                "processing_intent": "exploratory"
                if question.startswith("比较")
                else "acquisition",
                "context_sufficient": True,
                "standards": standards,
                "clause_numbers": [],
                "content_types": [],
                "is_explanation": None,
                "is_mandatory": None,
            }
        elif request.stage == "query_rewrite":
            data = {"rewritten_query": inputs["question"], "keyword_synonyms": []}
        elif request.stage == "query_expansion":
            data = {
                "expanded_queries": [
                    inputs["rewritten_query"] + inputs["expansion_separator"] + item["phrase"]
                    for item in inputs["available_contexts"][:1]
                ]
            }
        elif request.stage == "query_hyde":
            data = {
                "hypothetical_document": inputs["hyde_header"]
                + inputs["rewritten_query"]
                + inputs["hyde_footer"]
            }
        else:
            raise ValueError("unknown fixture model stage")
        return StructuredLLMResponse(
            request_id=request.request_id,
            model_id=request.config.model_id,
            model_revision=request.config.model_revision,
            data=data,
        )


class FixtureCatalog:
    def __init__(self, batch: ChunkBatch, scope: CatalogIndexScope) -> None:
        self.batch, self.scope = batch, scope

    def lookup(self, request: StandardMetadataLookup) -> StandardMetadataMatch:
        standard = self.batch.chunks[0].standard
        matches = request.scope == self.scope and all(
            expected is None or expected == actual
            for expected, actual in (
                (request.document_id, self.batch.document_id),
                (request.standard_code, standard.standard_code),
                (request.standard_name, standard.standard_name),
                (request.edition, standard.edition),
                (request.revision, standard.revision),
            )
        )
        return StandardMetadataMatch(
            request_id=request.request_id,
            catalog_id="fictional-catalog",
            snapshot_id="fictional-catalog-v1",
            is_test_fixture=True,
            status="unique" if matches else "not_found",
            candidates=[
                StandardMetadataRecord(
                    record_id="fictional-record",
                    document_id=self.batch.document_id,
                    standard=standard,
                    indexed_scopes=[self.scope],
                )
            ]
            if matches
            else [],
        )


class FixtureRetrieval:
    """Fixed corpus order plus canonical filters; no BM25/embedding approximation."""

    def __init__(self, batch: ChunkBatch, source: RetrievalSource) -> None:
        self.batch, self.source = batch, source

    def search(self, request: KeywordSearchRequest | VectorSearchRequest) -> list[RetrievalResult]:
        return [
            RetrievalResult(
                chunk_id=chunk.chunk_id,
                logical_chunk_id=chunk.logical_chunk_id,
                document_id=chunk.document_id,
                content=chunk.content,
                standard=chunk.standard,
                clause_id=chunk.clause_id,
                clause_number=chunk.clause_number,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                is_explanation=chunk.is_explanation,
                is_mandatory=chunk.is_mandatory,
                content_type=chunk.content_type,
                score=1.0 / rank,
                rank=rank,
                retrieval_source=self.source,
                score_type="fictional_fixed_order",
                index_name=request.index_name,
            )
            for rank, chunk in enumerate(
                [
                    chunk
                    for chunk in self.batch.chunks
                    if chunk_matches_filters(chunk, request.filters)
                ][: request.top_k],
                1,
            )
        ]


def create_offline_runtime(batch: ChunkBatch, config: RunConfig) -> EvaluationRuntime:
    if not batch.chunks:
        raise ValueError("offline fixture corpus is empty")
    scope = CatalogIndexScope(
        keyword_index=config.keyword_index, vector_collection=config.vector_collection
    )
    model = StructuredLLMConfig(
        config_id="fixture-config",
        model_id="fixture-model",
        model_revision="fixture-v1",
        timeout_seconds=1,
        max_output_tokens=4096,
    )
    settings = QueryConfig(
        understanding=UnderstandingConfig(llm=model, scope=scope, allow_test_catalog=True),
        rewrite=RewriteConfig(llm=model),
        enhancement=EnhancementConfig(expansion_llm=model, hyde_llm=model),
        planning=PlanningConfig(
            scope=scope,
            candidate_k=config.candidate_k,
            keyword_candidate_limit=config.candidate_k,
            vector_candidate_limit=config.candidate_k,
            fusion_strategy=config.fusion_strategy,
            keyword_weight=config.keyword_weight,
            vector_weight=config.vector_weight,
            embedding_model_id=config.embedding_model_id,
        ),
    )
    catalog = FixtureCatalog(batch, scope)

    def query_factory(
        variant: Variant, llm: StructuredLLMClient, hybrid: HybridRetrievalService
    ) -> QueryService:
        selected = settings.model_copy(deep=True)
        selected.enhancement.enable_expansion = variant in {"rewrite_expansion", "full"}
        selected.enhancement.enable_hyde = variant in {"rewrite_hyde", "full"}
        return create_query_service(
            llm=llm, catalog=catalog, hybrid_service=hybrid, config=selected
        )

    return EvaluationRuntime(
        backend_kind="offline",
        llm_kind="offline",
        llm=FixtureModel(),
        query_factory=query_factory,
        hybrid_service=create_hybrid_retrieval_service(
            FixtureRetrieval(batch, RetrievalSource.KEYWORD),
            FixtureRetrieval(batch, RetrievalSource.VECTOR),
        ),
        metadata={
            "implementation": "fictional_fixed_order_no_quality_claim",
            "query_config_sha256": hashlib.sha256(settings.model_dump_json().encode()).hexdigest(),
            "catalog_snapshot_id": "fictional-catalog-v1",
        },
    )
