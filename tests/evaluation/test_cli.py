"""Invoke the documented CLI in a subprocess; all artifacts stay in pytest temp dirs."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from engineering_rag.contracts.evaluation import EvaluationReport


def repository_root() -> Path:
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "AGENTS.md").is_file() and (candidate / "pyproject.toml").is_file():
            return candidate
    raise AssertionError("cannot locate repository markers from test file")


ROOT = repository_root()
FIXTURE = ROOT / "examples" / "query_evaluation" / "v1"
SCRIPT = ROOT / "scripts" / "evaluate_query_pipeline.py"
MANIFEST = json.loads((FIXTURE / "manifest.json").read_text(encoding="utf-8"))


def command(output: Path, run_id: str = "example", mode: str = "validate_only") -> list[str]:
    return [
        sys.executable,
        str(SCRIPT),
        "--dataset",
        str(FIXTURE),
        "--dataset-version",
        MANIFEST["dataset_version"],
        "--corpus",
        str(FIXTURE / "corpus.chunk_batch.v1.json"),
        "--corpus-snapshot-id",
        MANIFEST["corpus_snapshot_id"],
        "--output-dir",
        str(output),
        "--run-id",
        run_id,
        "--mode",
        mode,
        "--keyword-index",
        "fixture_keyword",
        "--vector-collection",
        "fixture_vector",
    ]


def invoke(args: list[str], *, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=30, check=False)


def read_metrics(output: Path, run_id: str = "example") -> dict[str, object]:
    return json.loads((output / run_id / "metrics.json").read_text(encoding="utf-8"))


def fingerprints(directory: Path) -> dict[str, str]:
    return {
        str(path.relative_to(directory)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in directory.rglob("*")
        if path.is_file()
    }


def test_cli_validate_only_produces_no_official_scores(tmp_path: Path) -> None:
    before = fingerprints(FIXTURE)
    result = invoke(command(tmp_path))
    assert result.returncode == 0, result.stderr
    metrics = read_metrics(tmp_path)
    assert metrics["status"] == "DRAFT_VALIDATED"
    assert metrics["official_quality_metrics"] is None
    assert metrics["offline_simulation"] is None
    assert (tmp_path / "example" / "per_query_results.jsonl").read_text() == ""
    report = EvaluationReport.model_validate_json(
        (tmp_path / "example" / "evaluation_report.json").read_text(encoding="utf-8")
    )
    assert report.metrics == []
    assert fingerprints(FIXTURE) == before


def test_cli_offline_all_variants_are_simulation_not_official_scores(tmp_path: Path) -> None:
    before = fingerprints(FIXTURE)
    result = invoke(command(tmp_path, mode="offline_test"))
    assert result.returncode == 0, result.stderr + result.stdout
    assert "OFFLINE SIMULATION" in result.stdout
    assert "real retrieval quality NOT RUN" in result.stdout
    metrics = read_metrics(tmp_path)
    assert metrics["status"] == "COMPLETED"
    assert metrics["is_simulation"] is True
    assert metrics["official_quality_metrics"] is None
    assert set(metrics["offline_simulation"]["per_variant"]) == {
        "raw",
        "rewrite",
        "rewrite_expansion",
        "rewrite_hyde",
        "full",
    }
    rows = [
        json.loads(line)
        for line in (tmp_path / "example" / "per_query_results.jsonl").read_text().splitlines()
    ]
    assert len(rows) == MANIFEST["query_count"] * 5 == 40
    for row in rows:
        if row["expected_outcome"] == "retrieve":
            assert row["status"] == "success"
        elif row["variant"] == "raw":
            assert row["status"] == "skipped"
            assert row["skip_reason"] == "raw_baseline_has_no_scope_understanding_stage"
        else:
            assert row["status"] == "expected_rejection"
    report = EvaluationReport.model_validate_json(
        (tmp_path / "example" / "evaluation_report.json").read_text(encoding="utf-8")
    )
    assert report.metrics == []
    assert fingerprints(FIXTURE) == before


@pytest.mark.parametrize("mode", ["retrieval_eval", "llm_e2e_eval"])
def test_cli_real_modes_without_runtime_are_not_run(tmp_path: Path, mode: str) -> None:
    result = invoke(command(tmp_path, mode=mode))
    assert result.returncode == 2
    metrics = read_metrics(tmp_path)
    assert metrics["status"] == "NOT RUN"
    assert metrics["is_simulation"] is False
    assert metrics["official_quality_metrics"] is None
    assert metrics["offline_simulation"] is None
    assert "retrieval_runtime_not_configured" in metrics["blockers"]
    assert "human_verified_golden_dataset_not_ready" in metrics["blockers"]
    assert (tmp_path / "example" / "per_query_results.jsonl").read_text() == ""


def test_cli_wrong_dataset_version_fails_without_creating_run(tmp_path: Path) -> None:
    args = command(tmp_path)
    args[args.index("--dataset-version") + 1] = "nonexistent-version"
    result = invoke(args)
    assert result.returncode != 0
    assert "versions must agree" in result.stderr
    assert not (tmp_path / "example").exists()


def test_cli_cannot_overwrite_existing_run(tmp_path: Path) -> None:
    args = command(tmp_path)
    assert invoke(args).returncode == 0
    before = fingerprints(tmp_path / "example")
    second = invoke(args)
    assert second.returncode != 0
    assert "exist" in second.stderr.lower()
    assert fingerprints(tmp_path / "example") == before


def test_cli_absolute_paths_work_outside_repository(tmp_path: Path) -> None:
    outside = tmp_path / "unrelated-working-directory"
    outside.mkdir()
    output = tmp_path / "artifacts"
    result = invoke(command(output, mode="offline_test"), cwd=outside)
    assert result.returncode == 0, result.stderr
    assert read_metrics(output)["status"] == "COMPLETED"


def test_cli_validate_only_does_not_import_runtime_factory(tmp_path: Path) -> None:
    result = invoke(command(tmp_path) + ["--runtime-factory", "does_not_exist:factory"])
    assert result.returncode == 0, result.stderr
    assert read_metrics(tmp_path)["status"] == "DRAFT_VALIDATED"
