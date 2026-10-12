"""Opt-in assertions for a freshly generated Task 1.6 live MinerU run."""

import os
from pathlib import Path

import pytest

from engineering_rag.contracts.documents import Document

pytestmark = [
    pytest.mark.real_mineru,
    pytest.mark.skipif(
        os.environ.get("ENGINEERING_RAG_RUN_REAL_MINERU") != "1",
        reason="set ENGINEERING_RAG_RUN_REAL_MINERU=1 after running the Task 1.6 live pipeline",
    ),
]


def test_live_p16_artifact_has_real_source_and_valid_v24() -> None:
    root = Path(
        os.environ.get(
            "ENGINEERING_RAG_TASK16_LIVE_ROOT",
            "data/eval/task1_6_e2e/runs/live-p16-integrity-final-20261012",
        )
    )
    document = Document.model_validate_json(
        (root / "final/document.v2.4.partial.json").read_text(encoding="utf-8")
    )
    assert document.source_file.sha256 == (
        "43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682"
    )
    assert [page.page_number for page in document.pages] == [16]
    assert document.pages[0].page_type.value == "body"
    assert document.processing.partial is True
