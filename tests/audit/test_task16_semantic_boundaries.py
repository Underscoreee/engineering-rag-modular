"""Saved-real-artifact regressions for Task 1.6 semantic ownership boundaries."""

from pathlib import Path

from engineering_rag.contracts.documents import Document
from engineering_rag.modules.document_parser.internal.e2e import merge_documents
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUParseResult
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24
from engineering_rag.modules.document_parser.internal.semantic import assemble_semantics

RUN = Path("data/eval/task1_6_e2e/runs/gb50010-full-v2")


def test_saved_real_formula_note_is_retained_once_and_linked_to_equation() -> None:
    adaptation = _adapt("batch-005")
    note = "注:公式(3.3.2-1)中的\\gamma _ { 0 } s为内力设计值"
    page_text = [
        block.ocr.text or ""
        for page in adaptation.document.pages
        if page.page_number == 25
        for block in page.blocks
        if block.ocr is not None
    ]
    assert sum(note in text for text in page_text) == 1
    sidecar = next(item for item in adaptation.formula_sidecars if item.printed_notes)
    evidence = sidecar.printed_notes[0]
    assert evidence.projection_disposition == "retained_as_body"
    assert evidence.target_formula_ids
    assert evidence.projection_block_id in {
        block.block_id
        for page in adaptation.document.pages
        if page.page_number == 25
        for block in page.blocks
    }
    semantic = assemble_semantics(adaptation.document)
    clause = next(
        item for item in semantic.document.clauses.normative if item.clause_number == "3.3.2"
    )
    assert clause.page_start == 24 and clause.page_end == 25
    assert clause.clause_content.plain_text is not None
    assert clause.clause_content.plain_text.count(note) == 1
    assert evidence.projection_block_id in clause.source_block_ids


def test_saved_real_table_note_run_stops_before_clause_5_2_5() -> None:
    adaptation = _adapt("batch-009")
    table = next(item for item in adaptation.document.tables if item.title and "翼缘" in item.title)
    assert [note.number for note in table.notes or []] == [1, 2, 3, 4]
    assert all("5.2.5" not in note.content for note in table.notes or [])
    assert any(
        block.ocr is not None and (block.ocr.text or "").startswith("5.2.5 ")
        for page in adaptation.document.pages
        if page.page_number == 45
        for block in page.blocks
    )


def test_saved_real_formula_leadin_is_body_and_clause_plain_text_is_lossless() -> None:
    adaptations = [_adapt(f"batch-{index:03d}") for index in range(5, 10)]
    semantic = assemble_semantics(merge_documents([item.document for item in adaptations]))
    clause = next(
        item for item in semantic.document.clauses.normative if item.clause_number == "4.2.6"
    )
    leadin = "预应力筋疲劳应力比值\\rho _ { \\mathrm { p } } ^ { \\mathrm { f } }应按下列公式计算:"
    assert clause.clause_content.plain_text is not None
    assert clause.clause_content.plain_text.count(leadin) == 1
    assert "最大应力预应力筋" not in clause.clause_content.plain_text
    assert "4.2.6-1" in clause.clause_content.plain_text
    assert "4.2.6-2" in clause.clause_content.plain_text
    first_formula = next(
        block.ocr.formula_group
        for page in semantic.document.pages
        if page.page_number == 41
        for block in page.blocks
        if block.ocr is not None
        and block.ocr.formula_group is not None
        and block.ocr.formula_group.equations[0].equation_number == "4.2.6-1"
    )
    assert first_formula.symbol_explanations is not None
    assert leadin not in first_formula.symbol_explanations.items[0].description


def test_saved_real_replay_is_deterministic_and_v24_round_trips() -> None:
    adaptations = [_adapt("batch-005"), _adapt("batch-008"), _adapt("batch-009")]
    merged = merge_documents([item.document for item in adaptations])
    first = assemble_semantics(merged).document
    second = assemble_semantics(merged).document
    assert first == second
    assert Document.model_validate_json(first.model_dump_json()) == first


def _adapt(batch: str):  # type: ignore[no-untyped-def]
    baseline = Document.model_validate_json(
        (RUN / "final/document.v2.4.partial.json").read_text(encoding="utf-8")
    )
    result = MinerUParseResult.model_validate_json(
        (RUN / f"batches/{batch}/normalized-01.json").read_text(encoding="utf-8")
    )
    return adapt_to_v24(
        result,
        source_file=baseline.source_file,
        standard=baseline.standard,
        page_count=baseline.page_count,
    )
