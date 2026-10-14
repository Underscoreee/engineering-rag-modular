"""Regression tests derived from the Task 1.6 manual-review deltas."""

from pathlib import Path

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import BlockType, StandardMetadata
from engineering_rag.modules.document_parser.internal.mineru.models import (
    MinerUElement,
    MinerUPage,
    MinerUParseResult,
)
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24


def test_three_level_clause_is_body_but_chapter_and_section_remain_titles() -> None:
    adaptation = _adapt(
        _result(
            _page(
                17,
                _text(0, "2 术语和符号", raw_type="paragraph_title"),
                _text(1, "2.1 术语", raw_type="paragraph_title"),
                _text(2, "2.1.1 混凝土结构 concrete structure", raw_type="paragraph_title"),
                _text(3, "1 条文内分项", raw_type="text"),
            )
        )
    )

    assert [block.block_type for block in adaptation.document.pages[0].blocks] == [
        BlockType.TITLE,
        BlockType.TITLE,
        BlockType.BODY,
        BlockType.BODY,
    ]


def test_printed_page_number_is_removed_from_page_blocks_with_diagnostic() -> None:
    adaptation = _adapt(
        _result(
            _page(
                24,
                _text(0, "3.3.2 条文", raw_type="text"),
                _text(
                    1,
                    "9",
                    raw_type="page_number",
                    bbox=(0.85, 0.90, 0.90, 0.92),
                ),
            )
        )
    )

    assert [block.ocr.text for block in adaptation.document.pages[0].blocks] == ["3.3.2 条文"]
    assert any(
        item["reason"] == "printed_page_number_filtered" for item in adaptation.omitted_elements
    )


def test_mislabeled_footer_number_requires_sequence_evidence_before_filtering() -> None:
    adaptation = _adapt(
        _result(
            _page(
                24,
                _text(0, "9", raw_type="page_number", bbox=(0.85, 0.90, 0.90, 0.92)),
            ),
            _page(
                25,
                _text(0, "10", raw_type="page_number", bbox=(0.1, 0.90, 0.15, 0.92)),
            ),
            _page(
                26,
                _text(0, "11", raw_type="text", bbox=(0.85, 0.90, 0.90, 0.92)),
                _text(1, "3", raw_type="text", bbox=(0.1, 0.50, 0.15, 0.53)),
            ),
        )
    )

    assert all(not page.blocks for page in adaptation.document.pages[:2])
    assert [block.ocr.text for block in adaptation.document.pages[2].blocks] == ["3"]
    inferred = next(
        item
        for item in adaptation.omitted_elements
        if item.get("page_number") == 26 and item.get("source_index") == 0
    )
    assert inferred["filter_basis"] == "footer_geometry_and_contiguous_printed_page_sequence"


def test_formula_symbols_and_note_continue_across_page_until_next_clause() -> None:
    page_24 = _page(
        24,
        _equation(0, r"\gamma_0S\leq R\tag{3.3.2-1}"),
        _text(1, "式中：S——作用组合的效应设计值；"),
        _text(
            2,
            r"f_c、f_s——混凝土、钢筋的强度设计值，应根据本规范第",
            raw_content=[
                {"type": "equation_inline", "content": r"f_c"},
                {"type": "text", "content": "、"},
                {"type": "equation_inline", "content": r"f_s"},
                {"type": "text", "content": "——混凝土、钢筋的强度设计值，应根据本规范第"},
            ],
        ),
    )
    page_25 = _page(
        25,
        _text(0, "4.1.4条及第4.2.3条的规定取值；", raw_type="paragraph_title"),
        _text(
            1,
            r"a_k几何参数的标准值；",
            raw_content=[
                {"type": "equation_inline", "content": r"a_k"},
                {"type": "text", "content": "几何参数的标准值；"},
            ],
        ),
        _text(2, r"注：公式（3.3.2-1）中的\gamma_0S为内力设计值。"),
        _text(3, "3.3.3 新条文不得被消费。"),
    )

    adaptation = _adapt(_result(page_24, page_25))
    formula = adaptation.document.pages[0].blocks[0].ocr.formula_group
    assert formula is not None and formula.symbol_explanations is not None
    items = {item.symbol: item.description for item in formula.symbol_explanations.items}
    assert items["S"] == "作用组合的效应设计值"
    assert "4.1.4条及第4.2.3条的规定取值" in items[r"f_c、f_s"]
    assert items[r"a_k"] == "几何参数的标准值"
    assert [block.ocr.text for block in adaptation.document.pages[1].blocks] == [
        "3.3.3 新条文不得被消费。"
    ]
    sidecar = adaptation.formula_sidecars[0]
    assert sidecar.printed_notes[0].source_page_number == 25
    assert sidecar.printed_notes[0].target_formula_group_id == sidecar.formula_group_id
    assert any(component.source_page_number == 25 for component in sidecar.semantic_components)


def test_table_collects_sequential_adjacent_notes_without_crossing_next_clause() -> None:
    page = _page(
        26,
        _table(0, "表3.4.3 受弯构件的挠度限值", ["注：1 第一条；", "2 第二条；"]),
        _text(1, "3 第三条跨行说明；"),
        _text(2, "4 第四条。"),
        _text(3, "3.4.4 新条文不得归入表注。"),
    )
    adaptation = _adapt(_result(page))

    table = adaptation.document.tables[0]
    assert [note.number for note in table.notes or []] == [1, 2, 3, 4]
    assert [block.ocr.text for block in adaptation.document.pages[0].blocks] == [
        "表3.4.3 受弯构件的挠度限值",
        "3.4.4 新条文不得归入表注。",
    ]
    assert [item.source_index for item in adaptation.table_sidecars[0].note_evidence] == [1, 2]


def _adapt(result: MinerUParseResult):  # type: ignore[no-untyped-def]
    return adapt_to_v24(
        result,
        source_file=FileRef(
            file_id="manual-review-test",
            uri="memory://manual-review.pdf",
            mime_type="application/pdf",
            sha256=result.source_sha256,
        ),
        standard=StandardMetadata(
            standard_name="虚构人工核查回归标准",
            standard_code="DEMO-MANUAL-2026",
            edition="演示版",
        ),
        page_count=100,
    )


def _result(*pages: MinerUPage) -> MinerUParseResult:
    return MinerUParseResult(
        schema_id="docvortex.middle",
        schema_version="2.0",
        producer_version="4.0.12",
        tier="basic",
        parse_mode="ocr",
        source_sha256="e" * 64,
        pages=list(pages),
        raw_middle_json=Path("middle.json"),
        stdout_log=Path("stdout.log"),
        stderr_log=Path("stderr.log"),
        elapsed_seconds=1,
    )


def _page(page_number: int, *elements: MinerUElement) -> MinerUPage:
    return MinerUPage(
        page_number=page_number,
        page_idx=page_number - 1,
        width_points=400,
        height_points=600,
        elements=[
            element.model_copy(update={"page_number": page_number, "page_idx": page_number - 1})
            for element in elements
        ],
    )


def _text(
    index: int,
    text: str,
    *,
    raw_type: str = "text",
    bbox: tuple[float, float, float, float] = (0.1, 0.2, 0.9, 0.25),
    raw_content: list[dict[str, str]] | None = None,
) -> MinerUElement:
    return MinerUElement(
        page_number=1,
        page_idx=0,
        source_index=index,
        raw_type=raw_type,
        bbox={"x_min": bbox[0], "y_min": bbox[1], "x_max": bbox[2], "y_max": bbox[3]},
        text=text,
        raw={"type": raw_type, "content": raw_content or [{"type": "text", "content": text}]},
    )


def _equation(index: int, latex: str) -> MinerUElement:
    return MinerUElement(
        page_number=1,
        page_idx=0,
        source_index=index,
        raw_type="equation",
        bbox={"x_min": 0.2, "y_min": 0.2, "x_max": 0.8, "y_max": 0.25},
        latex=latex,
        raw={"type": "equation", "content": latex},
    )


def _table(index: int, caption: str, footnotes: list[str]) -> MinerUElement:
    return MinerUElement(
        page_number=1,
        page_idx=0,
        source_index=index,
        raw_type="table",
        bbox={"x_min": 0.1, "y_min": 0.2, "x_max": 0.9, "y_max": 0.5},
        text=caption,
        table_caption=caption,
        table_html="<table><tr><th>项目</th></tr><tr><td>值</td></tr></table>",
        table_footnotes=footnotes,
        raw={"type": "table"},
    )
