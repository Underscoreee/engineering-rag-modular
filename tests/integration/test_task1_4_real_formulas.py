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


def test_real_page_50_context_and_dedup_repair() -> None:
    root = ROOT / "GB-E621"
    document = Document.model_validate_json(
        (root / "document.fixed.partial.json").read_text(encoding="utf-8")
    )
    equations = {item.equation_number: item for item in _equations(document)}
    assert "ε_c ≤ ε_0" in (equations["6.2.1-1"].text or "")
    assert "ε_0 < ε_c ≤ ε_cu" in (equations["6.2.1-2"].text or "")
    assert all(equations[number].text is None for number in ("6.2.1-3", "6.2.1-4", "6.2.1-5"))
    assert (
        len([block for block in document.pages[0].blocks if block.block_type == BlockType.FORMULA])
        == 7
    )
    context = json.loads((root / "formula_context_sidecar.json").read_text(encoding="utf-8"))
    assert context["conditions"][0]["raw_text"].find(r"\ll") >= 0
    coverage = json.loads((root / "formula_dedup_coverage.json").read_text(encoding="utf-8"))
    assert sum(item["duplicate_disposition"] == "consumed" for item in coverage["records"]) == 7
    assert [
        item["source_index"]
        for item in coverage["records"]
        if item["duplicate_disposition"] == "dedup_unresolved"
    ] == [20]
    assert (root / "overlays/page-0050-formulas-fixed.png").is_file()


def test_real_page_50_semantic_groups_are_complete_and_unique() -> None:
    root = ROOT / "GB-E621"
    document = Document.model_validate_json(
        (root / "document.grouped.partial.json").read_text(encoding="utf-8")
    )
    blocks = document.pages[0].blocks
    formulas = [block for block in blocks if block.block_type == BlockType.FORMULA]
    assert len(blocks) == 7 and len(formulas) == 2
    assert [
        [equation.equation_number for equation in block.ocr.formula_group.equations]
        for block in formulas
        if block.ocr is not None and block.ocr.formula_group is not None
    ] == [
        [f"6.2.1-{index}" for index in range(1, 6)],
        ["6.2.1-6", "6.2.1-7"],
    ]
    assert [
        len(block.ocr.formula_group.symbol_explanations.items)
        for block in formulas
        if block.ocr is not None
        and block.ocr.formula_group is not None
        and block.ocr.formula_group.symbol_explanations is not None
    ] == [6, 2]
    body_texts = [
        block.ocr.text
        for block in blocks
        if block.block_type == BlockType.BODY and block.ocr is not None
    ]
    assert body_texts == [
        "2不考虑混凝土的抗拉强度。",
        "3 混凝土受压的应力与应变关系按下列规定取用:",
        "4 纵向受拉钢筋的极限拉应变取为0.01。",
        "5 纵向钢筋的应力取钢筋应变与其弹性模量的乘积，但其值应符合下列要求:",
        "35",
    ]
    sidecar = json.loads((root / "formula_semantic_group_sidecar.json").read_text(encoding="utf-8"))
    assert len(sidecar["groups"]) == 2
    assert sidecar["groups"][0]["conditions"][0]["raw_text"].find(r"\ll") >= 0
    consumption = json.loads(
        (root / "formula_source_consumption_report.json").read_text(encoding="utf-8")
    )
    assert consumption["summary"] == {
        "condition_sources_consumed": 2,
        "symbol_sources_consumed": 8,
        "unresolved_sources_retained": 0,
        "cross_page_incomplete_sources": 1,
    }
    assert (root / "overlays/page-0050-formulas-grouped.png").is_file()


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
