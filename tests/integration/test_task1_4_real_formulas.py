"""Explicit replay assertions for the three real Task 1.4 formula pages."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from engineering_rag.contracts.documents import (
    BlockType,
    Document,
    FormulaNumberStatus,
    RecognitionStatus,
)

pytestmark = [
    pytest.mark.real_mineru,
    pytest.mark.skipif(
        os.environ.get("ENGINEERING_RAG_RUN_REAL_MINERU") != "1",
        reason="set ENGINEERING_RAG_RUN_REAL_MINERU=1 after generating Task 1.4 artifacts",
    ),
]

ROOT = Path("data/eval/task1_4_formulas/runs/final")


@pytest.mark.parametrize(
    ("case_id", "numbers"),
    [
        ("GB-E332", ["3.3.2-1", "3.3.2-2"]),
        ("GB-E621", [f"6.2.1-{index}" for index in range(1, 8)]),
    ],
)
def test_real_numbered_formulas_are_individually_traceable(
    case_id: str, numbers: list[str]
) -> None:
    document = _document(case_id)
    equations = _equations(document)
    assert [item.equation_number for item in equations] == numbers
    assert all(item.equation_number_status == FormulaNumberStatus.PRINTED for item in equations)
    assert all(item.recognition_status == RecognitionStatus.UNVERIFIED for item in equations)
    assert len({item.formula_id for item in equations}) == len(equations)
    assert Document.model_validate_json(document.model_dump_json()) == document


def test_real_page_301_number_remains_unknown() -> None:
    document = _document("GB-EEXPL")
    equation = _equations(document)[0]
    assert equation.equation_number is None
    assert equation.equation_number_status == FormulaNumberStatus.UNKNOWN
    assert equation.recognition_status == RecognitionStatus.UNVERIFIED


def test_real_artifacts_retain_provenance_sidecars_and_overlays() -> None:
    for case_id, page in (("GB-E332", 24), ("GB-E621", 50), ("GB-EEXPL", 301)):
        root = ROOT / case_id
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        assert manifest["source_pdf_sha256"] == (
            "43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682"
        )
        assert manifest["middle_schema"] == "docvortex.middle"
        assert manifest["middle_schema_version"] == "2.0"
        assert manifest["page_mapping"][0]["original_physical_page"] == page
        assert (root / "raw/middle_json.json").is_file()
        assert list((root / "formula_sidecars").glob("*.json"))
        assert (root / "overlays" / f"page-{page:04d}-formulas.png").is_file()


def _document(case_id: str) -> Document:
    return Document.model_validate_json(
        (ROOT / case_id / "document.partial.json").read_text(encoding="utf-8")
    )


def _equations(document: Document):  # type: ignore[no-untyped-def]
    return [
        equation
        for page in document.pages
        for block in page.blocks
        if block.block_type == BlockType.FORMULA
        if block.ocr is not None and block.ocr.formula_group is not None
        for equation in block.ocr.formula_group.equations
    ]
