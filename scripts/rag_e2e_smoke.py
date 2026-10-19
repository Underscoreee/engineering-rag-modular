"""Task 7.3 real composition test. Explicit isolated targets only; never deletes.

Run with ``python -m scripts.rag_e2e_smoke --help`` from an editable installation.
This is a test composition root, not a new business API or a gold-quality evaluator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic
from typing import Protocol
from uuid import uuid4

from scripts._query_smoke_backends import inspect_backends
from scripts._query_smoke_runtime import (
    SmokeError,
    TraceEvents,
    environment,
    load_env_file,
    read_corpus,
    safe_error_code,
    validate_hits,
    write_json,
)
from scripts._rag_validation import ObservedLLM, SmokeCase, run_case, structural_metrics

from engineering_rag.contracts.catalog import CatalogIndexScope
from engineering_rag.contracts.chunks import ChunkBatch
from engineering_rag.contracts.common import TraceContext
from engineering_rag.contracts.queries import QueryOptions, QueryRequest
from engineering_rag.contracts.retrieval import (
    IndexRequest,
    KeywordSearchRequest,
    RetrievalResult,
    SearchFilters,
    VectorSearchRequest,
)
from engineering_rag.infrastructure.llm.api import LLMSettings, OpenAICompatibleLLMClient
from engineering_rag.modules.generation.api import GenerationSettings, create_generation_service
from engineering_rag.modules.hybrid_retrieval.api import create_hybrid_retrieval_service
from engineering_rag.modules.keyword_retrieval.api import (
    ElasticsearchKeywordConfig,
    create_elasticsearch_client,
    create_keyword_retrieval_service,
)
from engineering_rag.modules.query.api import (
    EnhancementConfig,
    PlanningConfig,
    QueryConfig,
    RewriteConfig,
    UnderstandingConfig,
    create_query_service,
)
from engineering_rag.modules.vector_retrieval.api import (
    SentenceTransformerEmbeddingProvider,
    VectorRetrievalConfig,
    create_milvus_client,
    create_vector_retrieval_service,
)


class SearchBackend(Protocol):
    def search(
        self, request: KeywordSearchRequest | VectorSearchRequest
    ) -> list[RetrievalResult]: ...


class RecordedSearch:
    """Observe actual delegated searches; never synthesize hits or alter filters."""

    def __init__(self, backend: SearchBackend, batch: ChunkBatch) -> None:
        self.backend, self.batch = backend, batch
        self.calls: list[dict[str, object]] = []

    def search(self, request: KeywordSearchRequest | VectorSearchRequest) -> list[RetrievalResult]:
        row: dict[str, object] = {
            "index_name": request.index_name,
            "top_k": request.top_k,
            "filters": request.filters.model_dump(mode="json"),
            "status": "FAIL",
        }
        self.calls.append(row)
        started = monotonic()
        try:
            hits = self.backend.search(request)
            validate_hits(hits, self.batch, request.filters)
            row.update(status="PASS", chunk_ids=[item.chunk_id for item in hits])
            return hits
        except Exception as error:
            row["error_code"] = safe_error_code(error)
            raise
        finally:
            row["elapsed_seconds"] = monotonic() - started


def validate_isolated_targets(keyword: str, vector: str) -> None:
    """Only operator-selected test targets; no wildcard, alias, or default target."""
    if not all(re.fullmatch(r"test_task73_[a-z0-9_]{8,64}", name) for name in (keyword, vector)):
        raise SmokeError("invalid_isolated_target")


def candidate_cases(batch: ChunkBatch) -> list[SmokeCase]:
    """Unverified workflow probes, NOT qrels or reference answers.

    Caller filters are explicit test inputs. No normative conclusions or mandatory
    labels are inferred. Source inventory proves only the two empty scopes.
    """
    document = batch.document_id
    code = batch.chunks[0].standard.standard_code
    specs = [
        (
            "exact",
            "exact_clause",
            "第4.2.6条的要求是什么？",
            {"clause_numbers": ["4.2.6"], "is_explanation": False},
        ),
        (
            "standard",
            "standard_scope",
            f"{code}中普通钢筋疲劳应力幅限值如何规定？",
            {"standard_codes": [code]},
        ),
        (
            "clause",
            "clause_number",
            "第6.2.1条包含哪些计算规定？",
            {"clause_numbers": ["6.2.1"], "is_explanation": False},
        ),
        (
            "formula",
            "formula_conditions",
            "第6.2.1条的公式、适用条件和符号解释是什么？",
            {"clause_numbers": ["6.2.1"], "content_types": ["formula"], "is_explanation": False},
        ),
        (
            "table",
            "table_notes",
            "第4.2.6条的表格数据和表注有哪些？",
            {"clause_numbers": ["4.2.6"], "content_types": ["table"], "is_explanation": False},
        ),
        (
            "explanation",
            "normative_vs_explanation",
            "第4.2.6条的条文说明解释了什么？",
            {"clause_numbers": ["4.2.6"], "is_explanation": True},
        ),
        (
            "mandatory",
            "mandatory_metadata",
            "哪些条文被来源数据明确标记为强制性条文？",
            {"is_mandatory": True},
        ),
        (
            "missing",
            "insufficient_evidence",
            "第99.9.9条的条文要求是什么？",
            {"clause_numbers": ["99.9.9"]},
        ),
    ]
    cases = []
    for name, category, question, values in specs:
        filters = SearchFilters(document_ids=[document], **values)
        expected_empty = (
            name == "mandatory" and not any(item.is_mandatory is True for item in batch.chunks)
        ) or (
            name == "missing" and not any(item.clause_number == "99.9.9" for item in batch.chunks)
        )
        cases.append(
            SmokeCase(
                name,
                category,
                QueryRequest(
                    question=question,
                    filters=filters,
                    options=QueryOptions(top_k=3),
                    trace=TraceContext(trace_id=f"task73-{name}-{uuid4().hex}"),
                ),
                expected_empty,
            )
        )
    return cases


def execute(args: argparse.Namespace, report: dict[str, object], secrets: list[str]) -> None:
    batch, digest = read_corpus(args.corpus)
    report.update(
        corpus_sha256=digest, chunk_count=len(batch.chunks), document_id=batch.document_id
    )
    settings = LLMSettings.from_env()
    keyword_config = ElasticsearchKeywordConfig.from_env()
    vector_config = VectorRetrievalConfig.from_env()
    os.environ["HF_HUB_OFFLINE"] = os.environ["TRANSFORMERS_OFFLINE"] = "1"
    provider = SentenceTransformerEmbeddingProvider(vector_config)
    with ExitStack() as resources:
        es = create_elasticsearch_client(keyword_config)
        mv = create_milvus_client(vector_config)
        resources.callback(es.close)
        resources.callback(mv.close)
        # Check BOTH targets before any write. Reuse mode never calls index();
        # exact dual inventories below are still mandatory, not a name-only trust.
        keyword_exists = bool(es.indices.exists(index=args.keyword_index))
        vector_exists = bool(mv.has_collection(collection_name=args.vector_collection))
        if args.create_isolated and (keyword_exists or vector_exists):
            raise SmokeError("isolated_target_already_exists")
        if args.reuse_isolated and not (keyword_exists and vector_exists):
            raise SmokeError("isolated_target_missing")
        report["stage"] = "inventory" if args.reuse_isolated else "indexing"
        report["targets_confirmed_absent"] = not (keyword_exists or vector_exists)
        report["read_only_reuse"] = args.reuse_isolated
        write_json(args.output_dir / "scope.json", report, secrets)
        keyword = create_keyword_retrieval_service(keyword_config, client=es)
        vector = create_vector_retrieval_service(
            vector_config, client=mv, embedding_provider=provider
        )
        for name, service, target in (
            ("keyword", keyword, args.keyword_index),
            ("vector", vector, args.vector_collection),
        ):
            if args.reuse_isolated:
                continue
            started = monotonic()
            print(f"indexing: {name}", flush=True)
            result = service.index(
                batch,
                IndexRequest(index_name=target, operation_id=uuid4().hex, replace_document=False),
            )
            write_json(
                args.output_dir / f"{name}-index.json",
                {
                    "result": result.model_dump(mode="json"),
                    "elapsed_seconds": monotonic() - started,
                },
                secrets,
            )
            if result.indexed != len(batch.chunks) or result.failures:
                raise SmokeError("isolated_index_incomplete")
        snapshot = inspect_backends(
            batch,
            keyword_client=es,
            vector_client=mv,
            keyword_config=keyword_config,
            vector_config=vector_config,
            provider=provider,
            keyword_index=args.keyword_index,
            vector_collection=args.vector_collection,
            corpus_sha256=digest,
        )
        report["inventory"] = snapshot.diagnostics
        llm = OpenAICompatibleLLMClient(settings)
        observed = ObservedLLM(llm)
        kr, vr = RecordedSearch(keyword, batch), RecordedSearch(vector, batch)
        scope = CatalogIndexScope(
            keyword_index=args.keyword_index, vector_collection=args.vector_collection
        )
        config = QueryConfig(
            understanding=UnderstandingConfig(
                llm=settings.structured_config("task73-understanding"),
                scope=scope,
                max_attempts=settings.max_attempts,
            ),
            rewrite=RewriteConfig(
                llm=settings.structured_config("task73-rewrite"), max_attempts=settings.max_attempts
            ),
            enhancement=EnhancementConfig(
                expansion_llm=settings.structured_config("task73-expansion"),
                hyde_llm=settings.structured_config("task73-hyde"),
            ),
            planning=PlanningConfig(
                scope=scope,
                candidate_k=10,
                keyword_candidate_limit=keyword_config.max_top_k,
                vector_candidate_limit=min(vector_config.max_top_k, vector_config.search_ef),
                embedding_model_id=provider.model_id,
            ),
        )
        query = create_query_service(
            llm=observed,
            catalog=snapshot.catalog,
            hybrid_service=create_hybrid_retrieval_service(kr, vr),
            config=config,
        )
        generation = create_generation_service(
            llm=observed,
            settings=GenerationSettings(
                llm=settings.structured_config("task73-generation"),
                provider=settings.provider,
                max_attempts=settings.max_attempts,
            ),
        )
        report.update(
            stage="end_to_end",
            model_id=settings.model_id,
            provider=settings.provider,
            llm_max_output_tokens=settings.max_output_tokens,
            llm_timeout_seconds=settings.timeout_seconds,
            query_config_sha256=hashlib.sha256(repr(config).encode()).hexdigest(),
        )
        rows = []
        for case in candidate_cases(batch):
            print(f"running: {case.case_id}", flush=True)
            ko, vo, lo = len(kr.calls), len(vr.calls), len(llm.calls)
            with TraceEvents(case.request.trace.trace_id) as events:
                row, answer = run_case(
                    case, query=query, generation=generation, observed_llm=observed, batch=batch
                )
            row.update(
                keyword_calls=kr.calls[ko:],
                vector_calls=vr.calls[vo:],
                llm_calls=llm.calls[lo:],
                events=events.events,
            )
            if row["status"] == "PASS" and (
                not row["keyword_calls"]
                or not row["vector_calls"]
                or any(call["status"] != "PASS" for call in [*kr.calls[ko:], *vr.calls[vo:]])
            ):
                row.update(
                    status="FAIL",
                    failure_stage="retrieval_assertion",
                    error_code="backend_not_successfully_executed",
                )
            write_json(args.output_dir / f"{case.case_id}.diagnostics.json", row, secrets)
            if answer is not None:
                write_json(
                    args.output_dir / f"{case.case_id}.answer.json",
                    answer.model_dump(mode="json"),
                    secrets,
                )
            rows.append(row)
            print(f"{case.case_id}: {row['status']}", flush=True)
        report.update(
            cases=rows,
            structural_metrics=structural_metrics(rows),
            stage="complete",
            status="PASS" if all(row["status"] == "PASS" for row in rows) else "FAIL",
        )
        if hashlib.sha256(args.corpus.read_bytes()).hexdigest() != digest:
            raise SmokeError("source_corpus_changed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--keyword-index", required=True)
    parser.add_argument("--vector-collection", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--create-isolated",
        action="store_true",
        help="explicitly authorize NEW targets and paid LLM calls",
    )
    mode.add_argument(
        "--reuse-isolated",
        action="store_true",
        help="read-only reuse after exact corpus/model inventory checks; real paid API calls",
    )
    args = parser.parse_args(argv)
    started = monotonic()
    report: dict[str, object] = {
        "status": "FAIL",
        "stage": "preflight",
        "created_at": datetime.now(UTC).isoformat(),
        "keyword_index": args.keyword_index,
        "vector_collection": args.vector_collection,
        "human_gold_status": "NOT AVAILABLE",
        "official_metrics": None,
        "cleanup": "NONE: test targets retained; existing knowledge bases untouched",
    }
    secrets: list[str] = []
    owns_output = False
    try:
        validate_isolated_targets(args.keyword_index, args.vector_collection)
        if not (args.create_isolated or args.reuse_isolated):
            raise SmokeError("explicit_isolated_mode_required")
        if any(path.is_symlink() for path in (args.output_dir, *args.output_dir.parents)):
            raise SmokeError("unsafe_output_directory")
        args.output_dir.mkdir(parents=True, exist_ok=False)
        owns_output = True
        values = load_env_file(args.env_file, os.environ)
        secrets = [
            value
            for key, value in values.items()
            if key.endswith(("_API_KEY", "_TOKEN", "_PASSWORD"))
        ]
        with environment(values):
            execute(args, report, secrets)
    except Exception as error:
        report["error_code"] = safe_error_code(error)
        report["status"] = "FAIL"
    report["elapsed_seconds"] = monotonic() - started
    if owns_output and not (args.output_dir / "report.json").exists():
        try:
            write_json(args.output_dir / "report.json", report, secrets)
        except Exception as error:
            report.update(status="FAIL", error_code=safe_error_code(error))
    print(
        json.dumps(
            {
                name: report.get(name)
                for name in ("status", "stage", "error_code", "elapsed_seconds")
            }
        )
    )
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
