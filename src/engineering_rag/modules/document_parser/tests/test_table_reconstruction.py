"""Pure Task 1.3 table topology, continuation, security, and V2.4 tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import (
    LogicalTableStatus,
    RawGridExtractionStatus,
    RecognitionStatus,
    StandardMetadata,
)
from engineering_rag.modules.document_parser.internal.mineru.models import (
    MinerUElement,
    MinerUPage,
    MinerUParseResult,
)
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24
from engineering_rag.modules.document_parser.internal.tables.assembler import (
    assemble_mineru_tables,
)
from engineering_rag.modules.document_parser.internal.tables.continuation_matcher import (
    decide_continuation,
)
from engineering_rag.modules.document_parser.internal.tables.header_normalizer import (
    build_columns,
    build_data_rows,
    build_header_paths,
    infer_header_row_count,
)
from engineering_rag.modules.document_parser.internal.tables.models import (
    TableFragmentCandidate,
)
from engineering_rag.modules.document_parser.internal.tables.notes import parse_table_notes
from engineering_rag.modules.document_parser.internal.tables.raw_html_parser import (
    TableHtmlError,
    parse_html_table,
)

CASES = json.loads(
    (Path(__file__).resolve().parents[5] / "TASK_1_3_TEST_CASES.json").read_text(encoding="utf-8")
)
SYNTHETIC = {item["case_id"]: item for item in CASES["synthetic_cases"]}


def test_simple_html_builds_complete_grid_columns_and_string_data() -> None:
    grid = parse_html_table(SYNTHETIC["S01"]["html"])
    header_rows, _ = infer_header_row_count(grid)
    columns = build_columns(grid, build_header_paths(grid, header_rows))
    rows = build_data_rows(
        grid, columns, header_rows=header_rows, page_number=1, block_id="block-1"
    )
    assert (grid.row_count, grid.column_count, grid.complete) == (2, 2, True)
    assert rows[0].root["column_2"] == "C30"
    assert all(value is None or isinstance(value, (str, int)) for value in rows[0].root.values())


def test_multilevel_headers_preserve_paths_and_spans() -> None:
    grid = parse_html_table(SYNTHETIC["S02"]["html"])
    header_rows, basis = infer_header_row_count(grid)
    paths = build_header_paths(grid, header_rows)
    assert basis == "explicit_th_or_thead"
    assert header_rows == 2
    assert paths == SYNTHETIC["S02"]["expect"]["header_paths"]
    assert any(cell.row_span == 2 for cell in grid.cells)
    assert any(cell.col_span == 2 for cell in grid.cells)


def test_three_level_header_and_vertical_header_path_are_preserved() -> None:
    grid = parse_html_table(
        '<table><thead><tr><th rowspan="3">类别</th><th colspan="2">限值</th></tr>'
        '<tr><th colspan="2">设计</th></tr><tr><th>下限</th><th>上限</th></tr></thead>'
        "<tbody><tr><td>A</td><td>1</td><td>2</td></tr></tbody></table>"
    )
    header_rows, _ = infer_header_row_count(grid)
    paths = build_header_paths(grid, header_rows)
    columns = build_columns(grid, paths)
    assert header_rows == 3
    assert paths == [["类别"], ["限值", "设计", "下限"], ["限值", "设计", "上限"]]
    assert columns[0].role.value == "row_header"


def test_rowspan_data_is_not_duplicated_in_flat_rows() -> None:
    grid = parse_html_table(SYNTHETIC["S03"]["html"])
    header_rows, _ = infer_header_row_count(grid)
    columns = build_columns(grid, build_header_paths(grid, header_rows))
    rows = build_data_rows(
        grid, columns, header_rows=header_rows, page_number=1, block_id="block-1"
    )
    assert rows[0].root["column_1"] == "长期"
    assert rows[1].root["column_1"] is None
    merged = next(cell for cell in grid.cells if cell.text == "长期")
    assert merged.row_span == 2


def test_engineering_values_remain_exact_strings() -> None:
    grid = parse_html_table(SYNTHETIC["S04"]["html"])
    header_rows, _ = infer_header_row_count(grid)
    columns = build_columns(grid, build_header_paths(grid, header_rows))
    rows = build_data_rows(grid, columns, header_rows=header_rows, page_number=28, block_id="p028")
    values = [value for row in rows for value in row.root.values() if isinstance(value, str)]
    for expected in SYNTHETIC["S04"]["expect"]["business_strings"]:
        assert expected in values


def test_numbered_and_unnumbered_notes_have_distinct_outcomes() -> None:
    numbered, raw, diagnostics = parse_table_notes(SYNTHETIC["S05"]["observed_note_texts"])
    assert [note.model_dump() for note in numbered or []] == SYNTHETIC["S05"]["expect"]["notes"]
    assert raw == [] and diagnostics == []
    notes, raw, diagnostics = parse_table_notes(SYNTHETIC["S06"]["observed_note_texts"])
    assert notes is None
    assert raw == SYNTHETIC["S06"]["observed_note_texts"]
    assert diagnostics


def test_explicit_compatible_continuation_merges_without_duplicate_data_header() -> None:
    result = _result_from_fragments(SYNTHETIC["S07"]["fragments"])
    adaptation = _adapt(result)
    assert len(adaptation.document.tables) == 1
    table = adaptation.document.tables[0]
    assert len(table.fragments) == 2
    assert len(table.data or []) == 2
    assert table.raw_grid is not None and table.raw_grid.row_count == 4
    assert sum(cell.is_header for cell in table.raw_grid.cells) == 4
    assert [block.table_id for page in adaptation.document.pages for block in page.blocks] == [
        table.table_id,
        table.table_id,
    ]


@pytest.mark.parametrize(
    ("case_id", "reason"),
    [("S08", "different_table_number"), ("S09", "incompatible_columns")],
)
def test_conflicting_continuations_do_not_merge(case_id: str, reason: str) -> None:
    fragments = SYNTHETIC[case_id]["fragments"]
    result = _result_from_fragments(fragments)
    assembly = assemble_mineru_tables(result)
    assert len(assembly.tables) == 2
    decisions = [
        decision for sidecar in assembly.sidecars for decision in sidecar.continuation_decisions
    ]
    assert any(decision.reason == reason for decision in decisions)


def test_adjacency_without_continuation_evidence_does_not_merge() -> None:
    result = _result_from_fragments(SYNTHETIC["S10"]["fragments"])
    assembly = assemble_mineru_tables(result)
    assert len(assembly.tables) == 2


def test_grid_without_header_evidence_remains_structure_only() -> None:
    result = _single_table_result("<table><tr><td>A</td><td>1</td></tr></table>", caption=None)
    table = _adapt(result).document.tables[0]
    assert table.extraction_status == LogicalTableStatus.STRUCTURE_ONLY
    assert table.data is None


def test_holey_grid_is_partial_without_phantom_cell() -> None:
    grid = parse_html_table(SYNTHETIC["S12"]["html"])
    assert grid.complete is False
    assert len(grid.cells) == 3
    result = _single_table_result(SYNTHETIC["S12"]["html"], caption="表 1.1 演示")
    table = _adapt(result).document.tables[0]
    assert table.raw_grid is not None
    assert table.raw_grid.extraction_status == RawGridExtractionStatus.PARTIAL


def test_unsafe_elements_are_ignored_without_network_or_script_execution() -> None:
    grid = parse_html_table(SYNTHETIC["S13"]["html"])
    assert grid.cells[0].text == ""
    assert "ignored unsafe script element" in grid.diagnostics
    assert "ignored external resource attribute" in grid.diagnostics


@pytest.mark.parametrize("case_id", ["S14", "S15"])
def test_multiple_or_pathological_tables_are_rejected(case_id: str) -> None:
    with pytest.raises(TableHtmlError):
        parse_html_table(SYNTHETIC[case_id]["html"])


def test_pathological_html_nesting_is_rejected() -> None:
    html = "<table><tr><td>" + "<div>" * 65 + "X" + "</div>" * 65 + "</td></tr></table>"
    with pytest.raises(TableHtmlError, match="nesting exceeds"):
        parse_html_table(html)


def test_missing_bbox_or_html_never_invents_grid_or_block() -> None:
    result = _single_table_result("", caption="表 1.2", bbox=None)
    assembly = assemble_mineru_tables(result)
    assert assembly.tables == []
    assert assembly.placements == {}
    assert assembly.omitted[0]["reason"] == "missing_bbox"


def test_stable_ids_machine_status_and_v24_roundtrip() -> None:
    result = _result_from_fragments(SYNTHETIC["S07"]["fragments"])
    first = _adapt(result).document
    second = _adapt(result).document
    assert first.tables[0].table_id == second.tables[0].table_id
    assert first.tables[0].extraction_status == LogicalTableStatus.UNVERIFIED
    assert all(
        cell.recognition_status == RecognitionStatus.UNVERIFIED
        for cell in first.tables[0].raw_grid.cells  # type: ignore[union-attr]
    )
    assert first.sections == []
    assert first.clauses.normative == [] and first.clauses.explanations == []
    assert first.processing.partial is True
    assert type(first.tables[0].data[0].root["source_page"]) is int  # type: ignore[index]
    assert first.model_validate_json(first.model_dump_json()) == first


def test_continuation_decision_uses_original_page_numbers() -> None:
    left = _candidate(28, "表 3.5.2", SYNTHETIC["S07"]["fragments"][0]["html"])
    right = _candidate(30, "续表 3.5.2", SYNTHETIC["S07"]["fragments"][1]["html"])
    decision = decide_continuation(left, right)
    assert decision.should_merge is False
    assert decision.reason == "non_adjacent_source_pages"


def _candidate(page: int, caption: str, html: str) -> TableFragmentCandidate:
    result = _single_table_result(html, caption=caption, page=page)
    assembly = assemble_mineru_tables(result)
    return assembly.sidecars[0].fragments[0]


def _adapt(result: MinerUParseResult):  # type: ignore[no-untyped-def]
    return adapt_to_v24(
        result,
        source_file=FileRef(
            file_id="synthetic-file",
            uri="memory://synthetic.pdf",
            mime_type="application/pdf",
            sha256=result.source_sha256,
        ),
        standard=StandardMetadata(
            standard_name="虚构表格测试标准",
            standard_code="DEMO-TABLE-2026",
            edition="演示版",
        ),
        page_count=500,
    )


def _result_from_fragments(fragments: list[dict[str, object]]) -> MinerUParseResult:
    pages = []
    for index, fragment in enumerate(fragments):
        page = int(fragment["physical_page"])
        pages.append(
            MinerUPage(
                page_number=page,
                page_idx=page - 1,
                width_points=400,
                height_points=600,
                elements=[
                    _element(
                        page,
                        index,
                        str(fragment["html"]),
                        fragment.get("caption"),
                    )
                ],
            )
        )
    return _result(pages)


def _single_table_result(
    html: str,
    *,
    caption: str | None,
    page: int = 1,
    bbox: dict[str, float] | None = None,
) -> MinerUParseResult:
    actual_bbox = (
        {"x_min": 0.1, "y_min": 0.1, "x_max": 0.9, "y_max": 0.8} if bbox is None and html else bbox
    )
    return _result(
        [
            MinerUPage(
                page_number=page,
                page_idx=page - 1,
                width_points=400,
                height_points=600,
                elements=[
                    _element(
                        page,
                        0,
                        html,
                        caption,
                        bbox=actual_bbox,
                        missing_bbox=bbox is None and not html,
                    )
                ],
            )
        ]
    )


def _element(
    page: int,
    index: int,
    html: str,
    caption: object,
    *,
    bbox: dict[str, float] | None = None,
    missing_bbox: bool = False,
) -> MinerUElement:
    return MinerUElement(
        page_number=page,
        page_idx=page - 1,
        source_index=index,
        raw_type="table",
        bbox=(
            None
            if missing_bbox
            else bbox or {"x_min": 0.1, "y_min": 0.1, "x_max": 0.9, "y_max": 0.8}
        ),
        table_html=html or None,
        table_caption=caption if isinstance(caption, str) else None,
        text=caption if isinstance(caption, str) else None,
        raw={"type": "table"},
    )


def _result(pages: list[MinerUPage]) -> MinerUParseResult:
    return MinerUParseResult(
        schema_id="docvortex.middle",
        schema_version="2.0",
        producer_version="4.0.12",
        tier="basic",
        parse_mode="ocr",
        source_sha256="c" * 64,
        pages=pages,
        raw_middle_json=Path("middle.json"),
        stdout_log=Path("stdout.log"),
        stderr_log=Path("stderr.log"),
        elapsed_seconds=1,
    )
