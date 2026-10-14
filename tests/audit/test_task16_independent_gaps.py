"""Independent Task 1.6 acceptance regressions (expected RED on supplied source).

Do not update expected outcomes just to make tests pass. Keep all code
changes inside the Parser internal evaluation/orchestration modules.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts.run_document_parser_e2e import _load_result

from engineering_rag.modules.document_parser.internal.e2e.quality import (
    evaluate_verified_records,
)

SHA = "43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682"


def _review() -> dict:
    return {
        "golden_status": "verified",
        "reviewer": "test-reviewer",
        "reviewed_at": datetime(2026, 10, 12, tzinfo=UTC).isoformat(),
        "dataset_version": "audit-fixture",
        "provenance": "test-gold",
    }


def test_false_source_and_supplied_predictions_cannot_score_as_real_accuracy():
    """P1: reject source-mismatched labels; score ONLY actual Document predictions."""
    fabricated = _review() | {
        "source_sha256": "b" * 64,
        "verified_labels": {"page_types": {"50": "body"}},
        "machine_predictions": {"page_types": {"50": "body"}},
    }
    with pytest.raises(ValueError, match="source|identity|mismatch|provenance"):
        evaluate_verified_records(
            [fabricated],
            expected_source_sha256=SHA,
            authoritative_page_types={"50": "unknown"},
        )


def test_page_type_macro_f1_all_wrong_is_zero_not_undefined():
    """P1: all-wrong but nonempty labelled data must yield macro-F1=0."""
    record = _review() | {
        "verified_labels": {"page_types": {"50": "body"}},
        "machine_predictions": {"page_types": {"50": "unknown"}},
    }
    score = evaluate_verified_records([record])["metrics"]["page_type_per_class"]
    assert score["macro_f1"] == 0.0, score


def test_replay_symlink_is_rejected_before_path_resolution(tmp_path: Path):
    """P2: _load_result must not follow a symlink contrary to its safety policy."""
    source = Path("data/eval/task1_2_mineru/runs/final/P016/single_page/normalized.json").resolve()
    alias = tmp_path / "alias.json"
    alias.symlink_to(source)
    with pytest.raises(ValueError, match="symlink|unsafe|symbolic"):
        _load_result(alias)


def test_old_run_directory_cannot_be_reused_without_resume(tmp_path: Path, monkeypatch):
    """P1: preserve completed run evidence. Opt-in: real source PDF is needed for CLI."""
    import os

    from scripts.run_document_parser_e2e import main

    del monkeypatch
    pdf = os.getenv("ENGINEERING_RAG_REVIEW_PDF")
    if not pdf or not Path(pdf).is_file():
        pytest.skip("set ENGINEERING_RAG_REVIEW_PDF to the verified GB 50010 original PDF")
    out = tmp_path / "a-provenance-run"
    common = [
        "--mode",
        "replay_saved_raw",
        "--pdf",
        pdf,
        "--pages",
        "16",
        "--output",
        str(out),
        "--test-matrix",
        "TASK_1_6_TEST_MATRIX.json",
    ]
    assert main([*common, "--run-id", "completed-run-A"]) == 0
    with pytest.raises(
        (FileExistsError, ValueError, RuntimeError),
        match="already|exist|resume|overwrite|immutable",
    ):
        main([*common, "--run-id", "unexpected-run-B"])
