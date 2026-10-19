"""Test execution provenance, ablation safety and artifacts without real backends."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import pytest

from engineering_rag.contracts.common import ArtifactRef
from engineering_rag.contracts.evaluation import EvaluationRequest, EvaluationTarget
from engineering_rag.contracts.llm import (
    StructuredLLMConfig,
    StructuredLLMRequest,
    StructuredLLMResponse,
)
from engineering_rag.contracts.retrieval import KeywordSearchRequest, RetrievalSource
from engineering_rag.infrastructure.evaluation.api import (
    EvaluationRuntime,
    IndexSnapshot,
    create_evaluation_service,
)
from engineering_rag.infrastructure.evaluation.internal.dataset import (
    DatasetValidationError,
    safe_read_json,
)
from engineering_rag.infrastructure.evaluation.internal.offline import (
    FixtureRetrieval,
    create_offline_runtime,
)
from engineering_rag.infrastructure.evaluation.internal.run_models import RunConfig
from engineering_rag.infrastructure.evaluation.internal.service import chunk_inventory_digest
from engineering_rag.infrastructure.evaluation.internal.telemetry import ModelProbe, QueryEvents

from .test_dataset import Fixture
from .test_dataset import dataset as dataset


def prepare(dataset: Fixture) -> None:
    rows = [
        json.loads(line) for line in (dataset.directory / "queries.jsonl").read_text().splitlines()
    ]
    for row in rows:
        row["caller_filters"] = row["expected_filters"] or {}
    dataset.rows("queries.jsonl", rows)


def request(dataset: Fixture, mode: str = "offline_test", **options) -> EvaluationRequest:
    return EvaluationRequest(
        evaluation_type="retrieval",
        dataset=ArtifactRef(
            artifact_id="fictional-dataset",
            artifact_type="query_golden_dataset",
            uri=str(dataset.directory),
            media_type="application/json",
            artifact_version="demo-1",
            sha256=hashlib.sha256((dataset.directory / "manifest.json").read_bytes()).hexdigest(),
        ),
        dataset_version="demo-1",
        target=EvaluationTarget(component_id="query_pipeline", component_version="query-2.0"),
        config={
            "corpus_path": str(dataset.corpus),
            "corpus_snapshot_id": "snapshot-fictional-1",
            "output_dir": str(dataset.directory.parent / "runs"),
            "run_id": "test-run",
            "keyword_index": "fixture_keyword",
            "vector_collection": "fixture_vector",
            "mode": mode,
            "ks": "1,3",
            "variants": "raw,rewrite,rewrite_expansion,rewrite_hyde,full",
            **options,
        },
    )


def runtime(dataset: Fixture, req: EvaluationRequest) -> EvaluationRuntime:
    return create_offline_runtime(dataset.load().batch, RunConfig.from_options(req.config))


def test_offline_fixture_preserves_declared_chunk_source_metadata(dataset: Fixture) -> None:
    batch = dataset.load().batch
    backend = FixtureRetrieval(batch, RetrievalSource.KEYWORD)
    hits = backend.search(
        KeywordSearchRequest(query="虚构工程问题", index_name="fixture", top_k=len(batch.chunks))
    )
    assert len(hits) == len(batch.chunks)
    for rank, (hit, chunk) in enumerate(zip(hits, batch.chunks, strict=True), 1):
        assert hit.is_explanation is chunk.is_explanation
        assert hit.is_mandatory is chunk.is_mandatory
        assert hit.content_type == chunk.content_type
        assert hit.chunk_id == chunk.chunk_id
        assert hit.rank == rank and hit.score == 1.0 / rank


def results(req: EvaluationRequest) -> tuple[dict[str, object], list[dict[str, object]]]:
    root = Path(req.config["output_dir"]) / req.config["run_id"]
    return json.loads((root / "metrics.json").read_text()), [
        json.loads(line) for line in (root / "per_query_results.jsonl").read_text().splitlines()
    ]


def test_actual_query_and_hybrid_offline_ablations_keep_gold_and_metadata_readonly(dataset):
    prepare(dataset)
    req = request(dataset)
    before = {path: path.read_bytes() for path in [dataset.corpus, *dataset.directory.iterdir()]}
    report = create_evaluation_service(runtime=runtime(dataset, req)).evaluate(req)
    payload, rows = results(req)
    assert payload["status"] == "COMPLETED"
    assert payload["is_simulation"] and payload["official_quality_metrics"] is None
    assert report.metrics == []  # Never promote fixture scores to official public metrics.
    assert len(rows) == 5 and all(row["status"] == "success" for row in rows)
    assert all(row["backend_call_count"] == 1 for row in rows)
    assert [a["stage"] for a in rows[-1]["stage_attempts"]] == [
        "query_understanding",
        "query_rewrite",
    ]
    assert rows[-1]["expansion"]["status"] == rows[-1]["hyde"]["status"] == "skipped_by_intent"
    assert all(row["hits"][0]["chunk_id"] == "chunk-fictional-1" for row in rows)
    assert {path: path.read_bytes() for path in before} == before


def test_exploratory_variants_use_real_public_query_mapping_with_single_execution(dataset):
    row = json.loads((dataset.directory / "queries.jsonl").read_text())
    row.update(query="比较设备设计要求？", processing_intent="exploratory", protected_spans=[])
    row["caller_filters"] = row["expected_filters"]
    dataset.rows("queries.jsonl", [row])
    req = request(dataset)
    create_evaluation_service(runtime=runtime(dataset, req)).evaluate(req)
    payload, rows = results(req)
    variants = {row["variant"]: row for row in rows}
    assert payload["status"] == "COMPLETED"
    assert len(variants["rewrite"]["stage_attempts"]) == 2
    assert len(variants["rewrite_expansion"]["stage_attempts"]) == 3
    assert len(variants["rewrite_hyde"]["stage_attempts"]) == 3
    assert len(variants["full"]["stage_attempts"]) == 4
    assert (
        variants["full"]["result"]["plan"]["hypothetical_document"]
        == variants["full"]["request"]["vector"]["query"]
    )
    assert all("假设性检索材料" not in item["request"]["keyword"]["query"] for item in rows)
    assert (
        len({json.dumps(item["request"]["keyword"]["filters"], sort_keys=True) for item in rows})
        == 1
    )
    assert all(row["backend_call_count"] == 1 for row in rows)


@pytest.mark.parametrize("failed_stage", ["query_expansion", "query_hyde"])
def test_failed_enhancement_ablation_is_failed_not_silent_success_but_full_can_fallback(
    dataset, failed_stage
):
    row = json.loads((dataset.directory / "queries.jsonl").read_text())
    row.update(query="比较设备设计要求？", processing_intent="exploratory", protected_spans=[])
    row["caller_filters"] = row["expected_filters"]
    dataset.rows("queries.jsonl", [row])
    variant = "rewrite_expansion" if failed_stage == "query_expansion" else "rewrite_hyde"
    req = request(dataset, variants=f"raw,{variant},full")
    injected = runtime(dataset, req)
    original = injected.llm.generate

    def generate(model_request):
        if model_request.stage == failed_stage:
            raise TimeoutError("fixture model unavailable")
        return original(model_request)

    with patch.object(injected.llm, "generate", side_effect=generate):
        create_evaluation_service(runtime=injected).evaluate(req)
    payload, rows = results(req)
    assert payload["status"] == "PARTIAL"
    assert rows[1]["status"] == "failed" and rows[1]["metrics"] is None
    assert rows[2]["status"] == "success"
    assert (
        rows[1]["expansion" if failed_stage == "query_expansion" else "hyde"]["status"] == "failed"
    )
    paired = payload["offline_simulation"]["paired_vs_raw"][variant]["recall@1"]
    assert paired["excluded_count"] == 1


def test_legal_empty_expansion_is_distinguished_from_generation_failure(dataset):
    row = json.loads((dataset.directory / "queries.jsonl").read_text())
    row.update(query="比较参数？", processing_intent="exploratory", protected_spans=[])
    row["caller_filters"] = row["expected_filters"]
    dataset.rows("queries.jsonl", [row])
    req = request(dataset, variants="full")
    create_evaluation_service(runtime=runtime(dataset, req)).evaluate(req)
    _, rows = results(req)
    assert rows[0]["expansion"]["accepted_count"] == 1  # default 比较 reviewed focus exists
    # A separate injectable empty response is tested without changing the policy.
    req2 = request(dataset, run_id="empty-expansion", variants="full")
    injected = runtime(dataset, req2)
    original = injected.llm.generate

    def generate(model_request):
        response = original(model_request)
        if model_request.stage == "query_expansion":
            response.data = {"expanded_queries": []}
        return response

    with patch.object(injected.llm, "generate", side_effect=generate):
        create_evaluation_service(runtime=injected).evaluate(req2)
    _, rows = results(req2)
    assert rows[0]["expansion"]["valid"] is True
    assert rows[0]["expansion"]["status"] == "completed"
    assert rows[0]["expansion"]["accepted_count"] == 0


def test_scope_mismatch_is_stopped_before_any_backend_call(dataset):
    req = request(dataset, variants="full")  # Original fixture has no caller_filters.
    create_evaluation_service(runtime=runtime(dataset, req)).evaluate(req)
    payload, rows = results(req)
    assert payload["status"] == "PARTIAL"
    assert rows[0]["error"]["code"] == "scope_mismatch"
    assert rows[0]["scope_violation"] is True and rows[0]["backend_call_count"] == 0
    assert rows[0]["metrics"] is None


def test_real_modes_are_not_run_when_only_fake_dependencies_or_labels_exist(dataset):
    prepare(dataset)
    req = request(dataset, mode="llm_e2e_eval")
    report = create_evaluation_service(runtime=runtime(dataset, req)).evaluate(req)
    payload, rows = results(req)
    assert payload["status"] == "NOT RUN" and rows == []
    assert report.metrics == [] and payload["official_quality_metrics"] is None
    assert "fictional_fixture_cannot_supply_official_quality_metrics" in payload["blockers"]
    assert "real_llm_query_runtime_not_configured" in payload["blockers"]
    assert "verified_index_snapshot_not_configured" in payload["blockers"]


def test_validate_only_never_calls_any_dependency(dataset):
    prepare(dataset)
    req = request(dataset, mode="validate_only")
    injected = runtime(dataset, req)
    with patch.object(injected.llm, "generate", side_effect=AssertionError("must not call")):
        create_evaluation_service(runtime=injected).evaluate(req)
    payload, rows = results(req)
    assert payload["status"] == "VALIDATED" and not rows
    assert payload["official_quality_metrics"] is None


def test_unknown_qrel_prevents_entire_run_instead_of_becoming_retrieval_miss(dataset):
    dataset.rows(
        "qrels.jsonl",
        [
            dict(
                query_id="query-fictional-1",
                chunk_id="missing",
                relevance=3,
                annotation_status="draft",
            )
        ],
    )
    req = request(dataset)
    with pytest.raises(DatasetValidationError, match="absent"):
        create_evaluation_service().evaluate(req)
    assert not (Path(req.config["output_dir"]) / req.config["run_id"]).exists()


def test_no_run_overwrite_and_no_golden_output_overlap(dataset):
    prepare(dataset)
    req = request(dataset, mode="validate_only")
    service = create_evaluation_service()
    service.evaluate(req)
    root = Path(req.config["output_dir"]) / req.config["run_id"]
    original = (root / "metrics.json").read_bytes()
    with pytest.raises(FileExistsError):
        service.evaluate(req)
    assert (root / "metrics.json").read_bytes() == original
    req.config["output_dir"] = str(dataset.directory / "nested")
    with pytest.raises(ValueError, match="overlap"):
        service.evaluate(req)


def test_output_symlink_and_dotdot_cannot_write_into_golden(dataset):
    req = request(dataset, mode="validate_only")
    alias = dataset.directory.parent / "linked-output"
    alias.symlink_to(dataset.directory, target_is_directory=True)
    req.config["output_dir"] = str(alias)
    with pytest.raises(ValueError, match="symbolic"):
        create_evaluation_service().evaluate(req)
    (dataset.directory.parent / "unused").mkdir()
    req.config["output_dir"] = str(dataset.directory.parent / "unused" / ".." / "gold")
    with pytest.raises(ValueError, match="overlap"):
        create_evaluation_service().evaluate(req)


@pytest.mark.parametrize(
    "field,value",
    [
        ("ks", "0"),
        ("ks", "1,1"),
        ("candidate_k", 0),
        ("vector_weight", -1.0),
        ("mode", "imaginary"),
    ],
)
def test_invalid_request_config_rejected(dataset, field, value):
    req = request(dataset, **{field: value})
    with pytest.raises(ValueError):
        create_evaluation_service().evaluate(req)


def test_backend_failure_is_not_normal_empty_result(dataset):
    prepare(dataset)
    req = request(dataset, variants="raw")
    injected = runtime(dataset, req)
    with patch.object(
        injected.hybrid_service, "search", side_effect=ConnectionError("fixture-down")
    ):
        create_evaluation_service(runtime=injected).evaluate(req)
    _, rows = results(req)
    assert rows[0]["status"] == "failed" and rows[0]["metrics"] is None
    assert rows[0]["error"]["code"] == "ConnectionError"


def test_complete_snapshot_identity_and_live_verifier_are_required(dataset):
    prepare(dataset)
    dataset.manifest["is_test_fixture"] = False  # Synthetic unit fixture, not real human gold.
    dataset.refresh()
    req = request(
        dataset, mode="retrieval_eval", variants="raw", embedding_model_id="deployed-model"
    )
    loaded = dataset.load()
    snapshot = IndexSnapshot.model_validate_json(
        json.dumps(
            {
                "snapshot_id": "test-index-1",
                "corpus_snapshot_id": loaded.manifest.corpus_snapshot_id,
                "corpus_sha256": loaded.corpus_sha256,
                "chunking_version": loaded.manifest.chunking_version,
                "keyword_index": "fixture_keyword",
                "vector_collection": "fixture_vector",
                "keyword_index_version": "immutable-es-test-id",
                "vector_collection_version": "immutable-vector-test-id",
                "chunk_ids_sha256": chunk_inventory_digest(loaded.chunks),
                "document_ids": loaded.document_ids,
                "embedding_model_id": "deployed-model",
                "encoding_policy_id": "fixture-policy",
                "verified_at": "2026-10-18T00:00:00Z",
                "verification_evidence": "unit-fixture-NOT-real-backend",
            }
        )
    )
    snapshot_path = dataset.directory.parent / "index.json"
    snapshot_path.write_text(snapshot.model_dump_json())
    req.config["snapshot_manifest"] = str(snapshot_path)
    base = runtime(dataset, req)
    declared = replace(base, backend_kind="real", verify_snapshot=None)
    create_evaluation_service(runtime=declared).evaluate(req)
    payload, _ = results(req)
    assert payload["status"] == "NOT RUN"
    assert "live_index_inventory_verifier_not_configured" in payload["blockers"]
    # Only schema/preflight logic is simulated here, not claimed as real integration.
    req.config["run_id"] = "bad-live-proof"
    altered = snapshot.model_copy(update={"corpus_sha256": "a" * 64})
    create_evaluation_service(
        runtime=replace(declared, verify_snapshot=lambda _: altered)
    ).evaluate(req)
    payload, rows = results(req)
    assert payload["status"] == "NOT RUN" and not rows
    assert "live_index_snapshot_does_not_match_manifest" in payload["blockers"]


def test_stage_capture_restores_logging_and_filters_unrelated_traces():
    logger = logging.getLogger("engineering_rag.modules.query")
    level, handlers = logger.level, list(logger.handlers)
    with pytest.raises(RuntimeError), QueryEvents("this-trace") as capture:
        logger.info(
            "metadata",
            extra={"trace_id": "other", "stage": "query_hyde", "status": "completed"},
        )
        logger.info(
            "metadata",
            extra={"trace_id": "this-trace", "stage": "query_hyde", "status": "failed"},
        )
        raise RuntimeError("fixture-error")
    assert logger.level == level and logger.handlers == handlers
    assert capture.events == [dict(stage="query_hyde", status="failed")]


def test_safe_reader_rejects_unknown_snapshot_links(dataset):
    target = dataset.directory.parent / "link.json"
    target.symlink_to(dataset.directory / "manifest.json")
    with pytest.raises(DatasetValidationError, match="symbolic"):
        safe_read_json(target)


def test_offline_mode_never_calls_a_declared_real_model(dataset):
    prepare(dataset)
    req = request(dataset, variants="full")
    injected = replace(runtime(dataset, req), llm_kind="real")
    with patch.object(
        injected.llm, "generate", side_effect=AssertionError("must not call real model")
    ):
        create_evaluation_service(runtime=injected).evaluate(req)
    payload, rows = results(req)
    assert payload["status"] == "NOT RUN" and not rows
    assert "offline_mode_requires_explicit_offline_llm" in payload["blockers"]


def test_post_understanding_prediction_survives_rewrite_failure(dataset):
    prepare(dataset)
    req = request(dataset, variants="full")
    injected = runtime(dataset, req)
    original = injected.llm.generate

    def generate(model_request):
        if model_request.stage == "query_rewrite":
            raise TimeoutError("fixture rewrite failure")
        return original(model_request)

    with patch.object(injected.llm, "generate", side_effect=generate):
        create_evaluation_service(runtime=injected).evaluate(req)
    _, rows = results(req)
    assert rows[0]["status"] == "failed" and rows[0]["metrics"] is None
    assert rows[0]["predicted_intent"] == "acquisition"
    assert rows[0]["predicted_filters"]["document_ids"] == ["document-fictional"]
    assert rows[0]["understanding_prediction_source"] == "validated_downstream_rewrite_input"


def test_returned_content_must_match_the_bound_chunk_snapshot(dataset):
    prepare(dataset)
    req = request(dataset, variants="raw")
    injected = runtime(dataset, req)
    original = injected.hybrid_service.search

    def changed(search_request):
        hits = original(search_request)
        hits[0] = hits[0].model_copy(update={"content": "wrong or generated evidence"})
        return hits

    with patch.object(injected.hybrid_service, "search", side_effect=changed):
        create_evaluation_service(runtime=injected).evaluate(req)
    _, rows = results(req)
    assert rows[0]["error"]["code"] == "source_mismatch" and rows[0]["metrics"] is None


def test_provider_cannot_mutate_observed_prior_stage_predictions():
    class MutatingProvider:
        def generate(self, request):
            request.input["validated_filters"]["document_ids"].clear()
            return StructuredLLMResponse(
                request_id=request.request_id, model_id=request.config.model_id, data={}
            )

    model_request = StructuredLLMRequest(
        request_id="probe-test",
        stage="query_rewrite",
        output_schema={},
        input={
            "processing_intent": "acquisition",
            "validated_filters": {"document_ids": ["original-doc"]},
        },
        config=StructuredLLMConfig(
            config_id="fixture", model_id="fixture", timeout_seconds=1, max_output_tokens=100
        ),
    )
    probe = ModelProbe(MutatingProvider())
    probe.generate(model_request)
    assert model_request.input["validated_filters"]["document_ids"] == ["original-doc"]
    assert probe.attempts[0]["validated_understanding_input"]["filters"]["document_ids"] == [
        "original-doc"
    ]
