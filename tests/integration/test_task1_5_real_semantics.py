"""Explicit assertions over saved real Task 1.5 MinerU semantic artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from engineering_rag.contracts.documents import (
    ClauseContentType,
    Document,
    PageType,
    derive_clause_plain_text,
)

pytestmark = [
    pytest.mark.real_mineru,
    pytest.mark.skipif(
        os.environ.get("ENGINEERING_RAG_RUN_REAL_MINERU") != "1",
        reason="set ENGINEERING_RAG_RUN_REAL_MINERU=1 after generating Task 1.5 artifacts",
    ),
]

ROOT = Path("data/eval/task1_5_semantics/runs/final/GB-COMBINED")


def test_real_document_roundtrip_sections_and_page_zones() -> None:
    document = _document()
    assert Document.model_validate_json(document.model_dump_json()) == document
    page_types = {page.page_number: page.page_type for page in document.pages}
    assert page_types[16] == PageType.BODY
    assert page_types[277] == PageType.EXPLANATION_COVER
    assert page_types[282] == PageType.EXPLANATION_BODY
    assert page_types[301] == PageType.EXPLANATION_BODY
    sections = {
        (section.content_group.value, section.number): section for section in document.sections
    }
    assert (
        sections[("normative", "6.2")].parent_section_id == sections[("normative", "6")].section_id
    )
    assert sections[("explanation", "1")].section_id != sections[("normative", "1")].section_id


def test_real_cross_page_clause_keeps_seven_formulas_without_duplicate_semantics() -> None:
    document = _document()
    clause = next(item for item in document.clauses.normative if item.clause_number == "6.2.1")
    assert (clause.page_start, clause.page_end) == (49, 50)
    assert [
        unit.list_item_label
        for unit in clause.clause_content.content_units
        if unit.content_type == ClauseContentType.LIST_ITEM
    ] == ["1", "2", "3", "4", "5"]
    formula_units = [
        unit
        for unit in clause.clause_content.content_units
        if unit.content_type == ClauseContentType.FORMULA
    ]
    assert [len(unit.formula_ids) for unit in formula_units] == [5, 2]
    assert len({block_id for unit in formula_units for block_id in unit.source_block_ids}) == 2
    rendered = derive_clause_plain_text(document, clause)
    assert rendered is not None
    text = rendered[0]
    assert "ε_c ≤ ε_0" in text and "ε_0 < ε_c ≤ ε_cu" in text
    assert text.count("混凝土轴心抗压强度设计值") == 1
    assert text.count("第i层纵向普通钢筋、预应力筋的应力") == 1
    assert clause.clause_content.plain_text is None
    assert clause.clause_content.review_warning is not None


def test_real_cross_page_table_and_following_clause_have_disjoint_sources() -> None:
    document = _document()
    clauses = {item.clause_number: item for item in document.clauses.normative}
    table_clause = clauses["9.1.2"]
    next_clause = clauses["9.1.3"]
    table_unit = next(
        unit
        for unit in table_clause.clause_content.content_units
        if unit.content_type == ClauseContentType.TABLE
    )
    table = next(item for item in document.tables if item.table_id == table_unit.table_id)
    assert table_unit.source_block_ids == table.source_block_ids
    assert set(table_clause.source_block_ids).isdisjoint(next_clause.source_block_ids)


def test_real_explanations_link_only_to_loaded_normative_clauses() -> None:
    document = _document()
    normative = {item.clause_number: item for item in document.clauses.normative}
    explanations = {item.clause_number: item for item in document.clauses.explanations}
    for number in ("1.0.1", "1.0.2", "1.0.3"):
        assert explanations[number].explains_clause_id == normative[number].clause_id
        assert explanations[number].clause_id != normative[number].clause_id
        assert explanations[number].is_mandatory is None
        assert explanations[number].mandatory_evidence == []


def test_real_outputs_retain_manifest_pending_links_and_overlays() -> None:
    manifest = json.loads((ROOT / "raw_inputs_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_pdf"]["sha256"] == (
        "43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682"
    )
    assert {page for item in manifest["inputs"] for page in item["physical_pages"]} == {
        16,
        49,
        50,
        126,
        127,
        277,
        282,
        301,
    }
    pending = json.loads((ROOT / "semantic_pending_links.json").read_text(encoding="utf-8"))
    assert any(item["physical_pages"] == [301] for item in pending["relations"])
    for page in (49, 50, 126, 127, 282):
        assert (ROOT / "overlays" / f"page_{page:04d}_semantic_overlay.png").is_file()


def _document() -> Document:
    return Document.model_validate_json(
        (ROOT / "document.semantic.partial.json").read_text(encoding="utf-8")
    )
