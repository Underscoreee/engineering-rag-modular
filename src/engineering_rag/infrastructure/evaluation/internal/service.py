"""Use the existing Evaluation Protocol for snapshot-bound Query experiments."""

from __future__ import annotations

import hashlib
import json
import math
import platform
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from time import monotonic

from engineering_rag.contracts.common import ContractError, ErrorCode, TraceContext
from engineering_rag.contracts.evaluation import (
    EvaluationFailure,
    EvaluationMetric,
    EvaluationReport,
    EvaluationRequest,
    EvaluationType,
)
from engineering_rag.contracts.retrieval import RetrievalResult, SearchFilters

from .dataset import (
    AnnotatedQuery,
    LoadedDataset,
    chunk_matches_filters,
    load_dataset,
    safe_read_json,
)
from .guards import RetrievalGuard, check_variant, raw_request
from .metrics import protected_span_metrics, ranking_metrics
from .run_models import EvaluationRuntime, EvaluationSafetyError, IndexSnapshot, RunConfig, Variant
from .summary import summarize_rows
from .telemetry import ModelProbe, QueryEvents, model_usage


def chunk_inventory_digest(chunks: dict[str, object]) -> str:
    """Stable inventory digest; corpus SHA additionally binds contents and metadata."""
    return hashlib.sha256("\n".join(sorted(chunks)).encode("utf-8")).hexdigest()


def _implementation_digest() -> str:
    root = Path(__file__).parents[1]
    digest = hashlib.sha256()
    for source in sorted(root.rglob("*.py")):
        digest.update(str(source.relative_to(root)).encode())
        digest.update(b"\0")
        digest.update(source.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _local_path(uri: str) -> Path:
    if "://" in uri:
        raise ValueError("evaluation dataset URI must be a local path, not a remote or file:// URI")
    return Path(uri)


def _output_directory(config: RunConfig, dataset_dir: Path, corpus: Path) -> Path:
    root = config.output_dir.absolute()
    directory = root / config.run_id
    for component in (*reversed(directory.parents), directory):
        if component.is_symlink():
            raise ValueError(f"output path contains a symbolic link: {component}")
    directory = directory.resolve()
    if directory.is_relative_to(dataset_dir.resolve()) or corpus.resolve().is_relative_to(
        directory
    ):
        raise ValueError("experiment output cannot overlap golden data or corpus")
    root.mkdir(parents=True, exist_ok=True)
    directory.mkdir(exist_ok=False)  # A completed or failed run must never be overwritten.
    return directory


def _write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        stream.write(
            json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n"
        )


class QueryPipelineEvaluator:
    """No business internals, database clients, model SDKs or corpus writes."""

    def __init__(self, *, runtime: EvaluationRuntime | None = None) -> None:
        self._runtime = runtime

    def evaluate(self, request: EvaluationRequest) -> EvaluationReport:
        request = EvaluationRequest.model_validate_json(request.model_dump_json())
        if request.evaluation_type != EvaluationType.RETRIEVAL:
            raise ValueError("this Evaluation adapter supports retrieval experiments only")
        if (
            request.dataset.artifact_type != "query_golden_dataset"
            or request.dataset.schema_version != "1.0"
        ):
            raise ValueError("evaluation artifact must be query_golden_dataset Schema 1.0")
        config = RunConfig.from_options(request.config)
        dataset_dir = _local_path(request.dataset.uri)
        dataset = load_dataset(
            dataset_dir,
            corpus_path=config.corpus_path,
            snapshot_id=config.corpus_snapshot_id,
            formal=config.require_verified,
        )
        if (
            request.dataset_version != dataset.manifest.dataset_version
            or request.dataset.artifact_version != request.dataset_version
        ):
            raise ValueError(
                "EvaluationRequest and dataset artifact versions must agree with manifest"
            )
        if request.dataset.artifact_id != dataset.manifest.dataset_id:
            raise ValueError("EvaluationRequest artifact_id must equal manifest.dataset_id")
        manifest_digest = hashlib.sha256((dataset_dir / "manifest.json").read_bytes()).hexdigest()
        if request.dataset.sha256 is not None and request.dataset.sha256 != manifest_digest:
            raise ValueError("Evaluation dataset artifact SHA-256 does not match manifest")
        blockers, snapshot = self._preflight(dataset, config, request.dataset.sha256)
        directory = _output_directory(config, dataset_dir, config.corpus_path)
        rows: list[dict[str, object]] = []
        if not blockers and config.mode != "validate_only":
            for query in dataset.queries:
                for variant in config.variants:
                    rows.append(self._run_one(query, variant, dataset, config))
        status = (
            "NOT RUN"
            if blockers
            else "VALIDATED"
            if config.mode == "validate_only" and dataset.formal_ready
            else "DRAFT_VALIDATED"
            if config.mode == "validate_only"
            else "PARTIAL"
            if any(row["status"] in {"failed", "not_run"} for row in rows)
            else "COMPLETED"
        )
        summary = summarize_rows(rows, config.variants, config.ks)
        simulated = config.mode == "offline_test"
        result_metrics: list[EvaluationMetric] = []
        if not blockers and not simulated and config.mode in {"retrieval_eval", "llm_e2e_eval"}:
            for variant, values in summary["per_variant"].items():
                for name, metric in values["retrieval_metrics"].items():
                    if metric["mean"] is not None:
                        result_metrics.append(
                            EvaluationMetric(
                                name=f"{variant}/{name}",
                                value=metric["mean"],
                                sample_count=metric["sample_count"],
                            )
                        )
        failures = [
            EvaluationFailure(
                sample_id=f"{row['variant']}:{row['query_id']}",
                error=ContractError(code=ErrorCode.CONFLICT, message=row["error"]["code"]),
            )
            for row in rows
            if row["status"] in {"failed", "not_run"}
        ]
        failures.extend(
            EvaluationFailure(
                sample_id="__run__", error=ContractError(code=ErrorCode.CONFLICT, message=reason)
            )
            for reason in blockers
        )
        report = EvaluationReport(
            evaluation_type=request.evaluation_type,
            dataset_version=request.dataset_version,
            target=request.target,
            metrics=result_metrics,
            failures=failures,
        )
        payload = {
            "schema_version": "1.0",
            "status": status,
            "mode": config.mode,
            "is_simulation": simulated,
            "blockers": blockers,
            "dataset_issues": dataset.issues,
            "formal_dataset_ready": dataset.formal_ready,
            "official_quality_metrics": None
            if simulated or blockers or config.mode == "validate_only"
            else summary,
            "offline_simulation": summary if simulated and not blockers else None,
            "metric_definitions": {
                "binary_relevance_threshold": config.relevance_threshold,
                "precision_denominator": "K_even_for_short_or_empty_results",
                "ndcg_gain": "2**relevance-1",
                "ndcg_discount": "log2(rank+1)",
                "unjudged_policy": "zero_gain_not_evidence_of_exhaustive_judgments",
                "failed_query_policy": (
                    "recorded_in_counts_and_pair_population_never_silently_dropped"
                ),
            },
        }
        _write(
            directory / "config.json",
            {
                "schema_version": "1.0",
                "created_at": datetime.now(UTC).isoformat(),
                "request": request.model_dump(mode="json"),
                "resolved": config.model_dump(mode="json"),
                "dataset": dataset.manifest.model_dump(mode="json"),
                "manifest_sha256": manifest_digest,
                "index_snapshot": snapshot.model_dump(mode="json") if snapshot else None,
                "runtime": self._runtime.metadata if self._runtime else None,
                "implementation": {
                    "evaluation_source_sha256": _implementation_digest(),
                    "python_version": platform.python_version(),
                    "pydantic_version": version("pydantic"),
                },
            },
        )
        _write(directory / "metrics.json", payload)
        _write(directory / "evaluation_report.json", report.model_dump(mode="json"))
        with (directory / "per_query_results.jsonl").open("x", encoding="utf-8") as stream:
            for row in rows:
                stream.write(
                    json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"
                )
        with (directory / "report.md").open("x", encoding="utf-8") as stream:
            stream.write(
                f"# Query Evaluation {config.run_id}\n\n状态：{status}。模式：{config.mode}。\n\n"
                f"数据集：{dataset.manifest.dataset_id} / {dataset.manifest.dataset_version}。\n\n"
                f"语料 SHA-256：{dataset.corpus_sha256}。\n\n"
                f"逐查询记录：{len(rows)}；失败：{len(failures)}。\n\n"
                + ("离线模拟只验证流程和计算，不是实际检索质量。\n\n" if simulated else "")
                + ("真实指标 NOT RUN。\n\n" if blockers else "")
                + "\n".join(f"- {reason}" for reason in blockers)
                + "\n\n具体分母、失败样本、配对比较、未知量见 metrics.json "
                + "和 per_query_results.jsonl。\n"
            )
        return report

    def _preflight(
        self,
        dataset: LoadedDataset,
        config: RunConfig,
        artifact_sha: str | None,
    ) -> tuple[list[str], IndexSnapshot | None]:
        if config.mode == "validate_only":
            return [], None
        runtime = self._runtime
        blockers = []
        if runtime is None:
            blockers.append("retrieval_runtime_not_configured")
        if not config.keyword_index or not config.vector_collection:
            blockers.append("retrieval_index_names_not_configured")
        if config.mode == "offline_test":
            if runtime is not None and runtime.backend_kind != "offline":
                blockers.append("offline_mode_requires_explicit_offline_dependencies")
            if runtime is not None and runtime.llm is not None and runtime.llm_kind != "offline":
                blockers.append("offline_mode_requires_explicit_offline_llm")
            if not dataset.manifest.is_test_fixture:
                blockers.append("offline_test_requires_explicit_fictional_fixture_dataset")
            return blockers, None
        if not dataset.formal_ready:
            blockers.append("human_verified_golden_dataset_not_ready")
        for query in dataset.queries:
            if query.expected_outcome == "retrieve" and not any(
                rel.query_id == query.query_id and rel.relevance >= config.relevance_threshold
                for rel in dataset.qrels
            ):
                blockers.append(f"no_relevant_targets_at_configured_threshold:{query.query_id}")
        if dataset.manifest.is_test_fixture:
            blockers.append("fictional_fixture_cannot_supply_official_quality_metrics")
        if artifact_sha is None:
            blockers.append("formal_dataset_manifest_requires_artifact_sha256")
        if runtime is not None and runtime.backend_kind != "real":
            blockers.append("real_mode_requires_real_backend_dependency")
        if config.mode == "llm_e2e_eval" and (
            runtime is None
            or runtime.llm_kind != "real"
            or runtime.llm is None
            or runtime.query_factory is None
        ):
            blockers.append("real_llm_query_runtime_not_configured")
        snapshot = None
        if config.snapshot_manifest is None:
            blockers.append("verified_index_snapshot_not_configured")
        else:
            snapshot = IndexSnapshot.model_validate_json(
                json.dumps(safe_read_json(config.snapshot_manifest))
            )
            expected = (
                snapshot.corpus_snapshot_id == dataset.manifest.corpus_snapshot_id
                and snapshot.corpus_sha256 == dataset.corpus_sha256
                and snapshot.chunking_version == dataset.manifest.chunking_version
                and snapshot.chunk_ids_sha256 == chunk_inventory_digest(dataset.chunks)
                and set(snapshot.document_ids) == set(dataset.document_ids)
                and snapshot.keyword_index == config.keyword_index
                and snapshot.vector_collection == config.vector_collection
                and snapshot.embedding_model_id == config.embedding_model_id
            )
            if not expected:
                blockers.append("index_snapshot_identity_mismatch")
            if runtime is None or runtime.verify_snapshot is None:
                blockers.append("live_index_inventory_verifier_not_configured")
            elif not blockers:
                try:
                    actual = runtime.verify_snapshot(snapshot.model_copy(deep=True))
                    if actual.identity() != snapshot.identity():
                        blockers.append("live_index_snapshot_does_not_match_manifest")
                except Exception:
                    blockers.append("live_index_snapshot_verification_failed")
        return blockers, snapshot

    def _run_one(
        self,
        query: AnnotatedQuery,
        variant: Variant,
        dataset: LoadedDataset,
        config: RunConfig,
    ) -> dict[str, object]:
        started = monotonic()
        runtime = self._runtime
        if runtime is None:
            raise AssertionError("preflight must reject missing runtime")
        row: dict[str, object] = {
            "query_id": query.query_id,
            "variant": variant,
            "status": "failed",
            "expected_outcome": query.expected_outcome,
            "expected_intent": query.processing_intent.value if query.processing_intent else None,
            "predicted_intent": None,
            "expected_filters": query.expected_filters.model_dump(mode="json")
            if query.expected_filters
            else None,
            "predicted_filters": None,
            "metrics": None,
            "rewrite_preservation": None,
            "expansion": {
                "valid": None,
                "accepted_count": 0,
                "protected_preservation": [],
                "human_semantic_review": None,
            },
            "hyde": {"valid": None, "protected_preservation": None, "human_factual_review": None},
            "stage_attempts": [],
            "retrieval_seconds": 0.0,
            "scope_violation": False,
            "error": None,
            "result": None,
            "annotation_status": query.annotation_status,
            "categories": list(query.categories),
        }
        guard = RetrievalGuard(
            runtime.hybrid_service,
            query.expected_filters or SearchFilters(),
            config,
            must_reject=query.expected_outcome == "reject",
        )
        probe = ModelProbe(runtime.llm) if runtime.llm else None
        trace_id = f"{config.run_id}:{query.query_id}:{variant}"
        events = QueryEvents(trace_id)
        try:
            if variant == "raw":
                if query.expected_outcome == "reject":
                    row["status"] = "skipped"
                    row["skip_reason"] = "raw_baseline_has_no_scope_understanding_stage"
                    return row
                if query.expected_filters is None:
                    raise EvaluationSafetyError(
                        "unlabeled_scope", "raw baseline requires a human-defined common scope"
                    )
                evidence = guard.search(raw_request(query.query, query.expected_filters, config))
                row["request"] = guard.requests[-1].model_dump(mode="json")
            else:
                if (
                    config.mode == "retrieval_eval"
                    or runtime.query_factory is None
                    or probe is None
                ):
                    row["status"] = "not_run"
                    row["error"] = {
                        "code": "query_runtime_not_configured",
                        "message": "this variant requires an injected Query/LLM runtime",
                    }
                    return row
                service = runtime.query_factory(variant, probe, guard)
                request = query.to_request(top_k=max(config.ks))
                request.trace = TraceContext(trace_id=trace_id, task_id=config.run_id)
                with events:
                    result = service.execute(request)  # Once; never plan() then execute().
                if len(guard.requests) != 1:
                    raise EvaluationSafetyError(
                        "missing_search", "Query did not use the injected Hybrid capability"
                    )
                row["result"] = result.model_dump(mode="json")
                row["predicted_intent"] = result.plan.processing_intent.value
                if (
                    variant == "full"
                    and result.plan.processing_intent == "exploratory"
                    and any(
                        event.get("stage") in {"query_expansion", "query_hyde"}
                        and event.get("status") == "skipped_by_config"
                        for event in events.events
                    )
                ):
                    raise EvaluationSafetyError(
                        "wrong_variant", "Full ablation disabled an enhancement stage"
                    )
                primary = result.plan.rewritten_queries[0]
                spans = [span.model_dump(mode="json") for span in query.protected_spans]
                row["rewrite_preservation"] = protected_span_metrics(query.query, primary, spans)
                expanded = result.plan.rewritten_queries[1:]
                hypothesis = result.plan.hypothetical_document
                row["expansion"] = {
                    "valid": None,  # Metadata below distinguishes completed-empty from failure.
                    "accepted_count": len(expanded),
                    "protected_preservation": [
                        protected_span_metrics(query.query, text, spans) for text in expanded
                    ],
                    "human_semantic_review": None,
                }
                row["hyde"] = {
                    "valid": None,
                    "protected_preservation": protected_span_metrics(query.query, hypothesis, spans)
                    if hypothesis
                    else None,
                    "human_factual_review": None,
                }
                check_variant(result.plan, variant, query.query)
                if result.plan.processing_intent == "acquisition" and any(
                    a["stage"] in {"query_expansion", "query_hyde"} for a in probe.attempts
                ):
                    raise EvaluationSafetyError(
                        "acquisition_enhancement", "acquisition called an optional model stage"
                    )
                evidence = result.evidence
            self._validate_evidence(evidence, dataset, query.expected_filters or SearchFilters())
            qrels = {q.chunk_id: q.relevance for q in dataset.qrels if q.query_id == query.query_id}
            row["metrics"] = ranking_metrics(
                [r.chunk_id for r in evidence], qrels, config.ks, config.relevance_threshold
            )
            row["hits"] = [item.model_dump(mode="json") for item in evidence]
            row["status"] = "success"
        except Exception as exc:
            code = getattr(exc, "code", type(exc).__name__)
            row["error"] = {
                "code": str(code),
                "message": "execution failed; no fabricated result or metrics",
                "error_type": type(exc).__name__,
                "phase": "hybrid_search" if guard.backend_calls else "query_or_scope_validation",
            }
            row["scope_violation"] = code in {"scope_mismatch", "unexpected_retrieval"}
            if (
                query.expected_outcome == "reject"
                and code == query.expected_error_code
                and guard.backend_calls == 0
            ):
                row["status"] = "expected_rejection"
                row["error"] = None
        finally:
            if guard.requests:
                row["predicted_filters"] = guard.requests[-1].keyword.filters.model_dump(
                    mode="json"
                )
                row["request"] = guard.requests[-1].model_dump(mode="json")
            row["stage_attempts"] = probe.attempts if probe else []
            row["stage_events"] = events.events
            if row["predicted_intent"] is None and probe:
                observations = [
                    item["validated_understanding_input"]
                    for item in probe.attempts
                    if item.get("validated_understanding_input") is not None
                ]
                if observations:
                    observed = observations[0]
                    row["predicted_intent"] = observed["processing_intent"]
                    row["understanding_prediction_source"] = "validated_downstream_rewrite_input"
                    if row["predicted_filters"] is None:
                        row["predicted_filters"] = observed["filters"]
            for name, stage in (("expansion", "query_expansion"), ("hyde", "query_hyde")):
                observed = [
                    event
                    for event in events.events
                    if event.get("stage") == stage and "status" in event
                ]
                status = observed[-1]["status"] if observed else "not_observed"
                row[name]["status"] = status
                row[name]["valid"] = (
                    True if status == "completed" else False if status == "failed" else None
                )
            row["model_usage"] = model_usage(probe.attempts) if probe else None
            row["retrieval_seconds"] = guard.elapsed_seconds
            row["elapsed_seconds"] = monotonic() - started
            row["backend_call_count"] = guard.backend_calls
        return row

    @staticmethod
    def _validate_evidence(
        evidence: list[RetrievalResult], dataset: LoadedDataset, filters: SearchFilters
    ) -> None:
        seen = set()
        fields = (
            "chunk_id",
            "logical_chunk_id",
            "document_id",
            "content",
            "standard",
            "clause_id",
            "clause_number",
            "page_start",
            "page_end",
        )
        for hit in evidence:
            chunk = dataset.chunks.get(hit.chunk_id)
            if chunk is None or hit.chunk_id in seen:
                raise EvaluationSafetyError(
                    "index_inventory_mismatch", "unknown or repeated returned Chunk identity"
                )
            seen.add(hit.chunk_id)
            if any(getattr(hit, name) != getattr(chunk, name) for name in fields):
                raise EvaluationSafetyError(
                    "source_mismatch", "returned Chunk content/source differs from corpus snapshot"
                )
            if not math.isfinite(hit.score) or hit.retrieval_source != "hybrid":
                raise EvaluationSafetyError("invalid_score", "invalid Hybrid score or source")
            if not chunk_matches_filters(chunk, filters):
                raise EvaluationSafetyError(
                    "scope_mismatch", "backend returned an out-of-scope Chunk"
                )
