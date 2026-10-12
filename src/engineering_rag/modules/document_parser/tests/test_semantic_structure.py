"""Task 1.5 synthetic positive, negative, and safe-degradation contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.common import BoundingBox, FileRef
from engineering_rag.contracts.documents import (
    BboxCoordinateSystem,
    BlockType,
    ClauseContentType,
    ClauseGroups,
    ContentExtractionStatus,
    Document,
    Equation,
    FormulaGroup,
    FormulaNumberStatus,
    LogicalTable,
    LogicalTableStatus,
    OcrContent,
    Page,
    PageBlock,
    PageType,
    ProcessingMetadata,
    RecognitionStatus,
    StandardMetadata,
    TableFragment,
    TableFragmentStatus,
    derive_clause_plain_text,
)
from engineering_rag.modules.document_parser.internal.semantic.assembler import (
    assemble_semantics,
)
from engineering_rag.modules.document_parser.internal.semantic.block_splitter import (
    TextSpanEvidence,
    split_body_block,
)

CONFIG = json.loads(
    (Path(__file__).resolve().parents[5] / "TASK_1_5_TEST_CASES.json").read_text(encoding="utf-8")
)
ALL_SYNTHETIC_CASES = {item["id"] for item in CONFIG["synthetic_cases"]}
IMPLEMENTED_CASES = {f"S{number:02d}" for number in range(1, 37)}


def test_all_declared_synthetic_cases_have_regression_coverage() -> None:
    assert ALL_SYNTHETIC_CASES == IMPLEMENTED_CASES


def test_sections_clauses_list_items_and_cache_are_structured() -> None:
    document = _document(
        [
            _page(
                16,
                _title("chapter", "1 总则", 0),
                _body("c101", "1.0.1 第一条正文。", 1),
                _body("c102", "1.0.2 第二条正文。", 2),
                _body("item", "1 条文内分项。", 3),
            )
        ]
    )
    result = assemble_semantics(document)
    assert result.document.pages[0].page_type == PageType.BODY
    section = result.document.sections[0]
    assert (section.number, section.structure_path, section.parent_section_id) == ("1", ["1"], None)
    clauses = result.document.clauses.normative
    assert [clause.clause_number for clause in clauses] == ["1.0.1", "1.0.2"]
    assert clauses[0].clause_content.plain_text == "1.0.1 第一条正文。"
    assert clauses[0].clause_content.plain_text_source_digest is not None
    assert clauses[1].clause_content.content_units[-1].content_type == ClauseContentType.LIST_ITEM
    assert clauses[1].clause_content.content_units[-1].list_item_label == "1"
    assert clauses[1].is_mandatory is None and clauses[1].mandatory_evidence == []


def test_chapter_and_section_form_a_valid_isolated_tree() -> None:
    result = assemble_semantics(
        _document(
            [
                _page(
                    49,
                    _title("chapter", "6 承载能力极限状态计算", 0),
                    _title("section", "6.2 正截面承载力计算", 1),
                    _body("clause", "6.2.1 条文。", 2),
                )
            ]
        )
    )
    chapter, section = result.document.sections
    assert section.parent_section_id == chapter.section_id
    assert section.structure_path == ["6", "6.2"]
    assert result.document.clauses.normative[0].section_id == section.section_id


def test_missing_section_parent_and_unknown_or_toc_pages_do_not_create_clauses() -> None:
    missing_parent = assemble_semantics(
        _document([_page(1, _title("section", "6.2 标题", 0), _body("c", "6.2.1 正文", 1))])
    )
    assert missing_parent.document.sections == []
    assert missing_parent.document.clauses.normative == []
    assert any(
        item.relation_type == "section_parent" for item in missing_parent.pending_links.relations
    )

    unknown = assemble_semantics(_document([_page(8, _body("mention", "按第4.1.1条执行", 0))]))
    assert unknown.document.pages[0].page_type == PageType.UNKNOWN
    assert unknown.document.clauses.normative == []

    toc_page = _page(
        9,
        _title("toc", "目次", 0),
        _body("toc-line-1", "1 总则 1", 1),
        _body("toc-line-2", "2 术语 4", 2),
    )
    toc = assemble_semantics(_document([toc_page]))
    assert toc.document.pages[0].page_type == PageType.TOC_ZH
    assert toc.document.sections == [] and toc.document.clauses.normative == []


def test_cross_page_clause_and_orphan_continuation_degrade_safely() -> None:
    pages = [
        _page(
            49,
            _title("ch", "6 计算", 0),
            _title("sec", "6.2 承载力", 1),
            _body("start", "6.2.1 基本假定:", 2),
        ),
        _page(50, _body("item2", "2 不考虑抗拉强度。", 0), _body("item3", "3 应力关系。", 1)),
    ]
    result = assemble_semantics(_document(pages))
    clause = result.document.clauses.normative[0]
    assert (clause.page_start, clause.page_end) == (49, 50)
    assert [unit.list_item_label for unit in clause.clause_content.content_units] == [
        None,
        "2",
        "3",
    ]

    orphan = assemble_semantics(_document([pages[1]]))
    assert orphan.document.clauses.normative == []
    relation = next(
        item
        for item in orphan.pending_links.relations
        if item.relation_type == "unclassified_content"
    )
    assert relation.evidence_block_ids == ["item2", "item3"]
    assert set(relation.source_bboxes) == {"item2", "item3"}
    assert "no_reliable_preceding_clause_boundary" in relation.blocking_conditions
    assert not any(
        item.relation_type == "unclassified_content" for item in result.pending_links.relations
    )


def test_table_unit_covers_all_fragments_and_stops_at_next_clause() -> None:
    table = LogicalTable(
        table_id="table-912",
        table_number="9.1.2",
        page_start=126,
        page_end=127,
        source_block_ids=["table-a", "table-b"],
        fragments=[
            TableFragment(page_number=126, block_id="table-a", fragment_index=0),
            TableFragment(page_number=127, block_id="table-b", fragment_index=1),
        ],
        extraction_status=LogicalTableStatus.STRUCTURE_ONLY,
    )
    document = _document(
        [
            _page(
                126,
                _title("ch9", "9 结构构件", 0),
                _title("sec91", "9.1 板", 1),
                _body("c912", "9.1.2 板厚规定。", 2),
                _table_block("table-a", "table-912", 0, 3),
            ),
            _page(
                127,
                _table_block("table-b", "table-912", 1, 0),
                _body("c913", "9.1.3 钢筋间距。", 1),
            ),
        ],
        tables=[table],
    )
    result = assemble_semantics(document)
    first, second = result.document.clauses.normative
    table_unit = first.clause_content.content_units[-1]
    assert table_unit.source_block_ids == ["table-a", "table-b"]
    assert table_unit.table_id == "table-912"
    assert second.source_block_ids == ["c913"]


def test_formula_group_is_referenced_once_and_renderer_does_not_duplicate_symbols() -> None:
    formula = PageBlock(
        block_id="formula-block",
        block_type=BlockType.FORMULA,
        bbox=_bbox(150, 220),
        reading_order=3,
        ocr=OcrContent(
            formula_group=FormulaGroup(
                equations=[
                    Equation(
                        formula_id=f"f-{number}",
                        equation_number=f"6.2.1-{number}",
                        equation_number_status=FormulaNumberStatus.PRINTED,
                        latex=f"x_{number}=y",
                        text=("适用条件：x≤y。公式（6.2.1-1）：x_1=y" if number == 1 else None),
                        recognition_status=RecognitionStatus.UNVERIFIED,
                    )
                    for number in range(1, 6)
                ]
            )
        ),
        recognition_status=RecognitionStatus.UNVERIFIED,
        formula_group_id="group-1",
    )
    document = _document(
        [
            _page(
                49,
                _title("ch", "6 计算", 0),
                _title("sec", "6.2 承载力", 1),
                _body("start", "6.2.1 基本假定。", 2),
                formula,
                _body("next", "6.2.2 下一条。", 4),
            )
        ]
    )
    result = assemble_semantics(document)
    clause = result.document.clauses.normative[0]
    unit = clause.clause_content.content_units[-1]
    assert unit.source_block_ids == ["formula-block"]
    assert unit.formula_ids == [f"f-{number}" for number in range(1, 6)]
    rendered = derive_clause_plain_text(result.document, clause)
    assert rendered is not None and rendered[0].count("适用条件") == 1


def test_explanation_identity_linking_and_pending_are_conservative() -> None:
    normative = _page(16, _title("nsec", "1 总则", 0), _body("n101", "1.0.1 正文。", 1))
    cover = _page(
        277,
        _title("cover-a", "混凝土结构设计规范", 0),
        _body("cover-b", "条文说明", 1),
    )
    explanation = _page(
        282,
        _title("esec", "1 总则", 0),
        _body("e101", "1.0.1 说明。", 1),
        _body("e102", "1.0.2 说明。", 2),
    )
    combined = assemble_semantics(_document([normative, cover, explanation]))
    n_clause = combined.document.clauses.normative[0]
    e_clause = combined.document.clauses.explanations[0]
    assert n_clause.clause_id != e_clause.clause_id
    assert e_clause.explains_clause_id == n_clause.clause_id
    assert combined.document.pages[1].page_type == PageType.EXPLANATION_COVER

    partial = assemble_semantics(_document([explanation]), known_explanation_cover_page=277)
    assert partial.document.clauses.explanations[0].explains_clause_id is None
    assert any(
        item.relation_type == "explanation_to_normative" for item in partial.pending_links.relations
    )


def test_stable_ids_json_roundtrip_and_physical_page_number() -> None:
    document = _document(
        [
            _page(
                50,
                _title("ch", "6 计算", 0),
                _title("sec", "6.2 承载力", 1),
                _body("c", "6.2.1 内容", 2),
            )
        ]
    )
    first = assemble_semantics(document).document
    second = assemble_semantics(document).document
    assert first.sections == second.sections and first.clauses == second.clauses
    assert first.pages[0].page_number == 50
    assert Document.model_validate_json(first.model_dump_json()) == first


def test_safe_block_split_requires_complete_geometry_and_preserves_lineage() -> None:
    text = "1.0.1 第一条。1.0.2 第二条。"
    document = _document([_page(16, _body("mixed", text, 0))])
    boundary = text.index("1.0.2")
    split, lineage = split_body_block(
        document,
        "mixed",
        [
            TextSpanEvidence(
                start=0,
                end=boundary,
                bbox=BoundingBox(x_min=20, y_min=20, x_max=195, y_max=40),
            ),
            TextSpanEvidence(
                start=boundary,
                end=len(text),
                bbox=BoundingBox(x_min=195, y_min=20, x_max=380, y_max=40),
            ),
        ],
    )
    assert len(split.pages[0].blocks) == 2
    assert lineage == {"mixed": [block.block_id for block in split.pages[0].blocks]}
    with pytest.raises(ValueError, match="complete source text"):
        split_body_block(
            document,
            "mixed",
            [TextSpanEvidence(start=0, end=boundary, bbox=_bbox(20, 40))],
        )
    with pytest.raises(ValueError, match="not reliable") as rejected:
        split_body_block(
            document,
            "mixed",
            [
                TextSpanEvidence(
                    start=0,
                    end=boundary,
                    bbox=BoundingBox(x_min=20, y_min=20, x_max=195, y_max=40),
                    geometry_reliable=False,
                ),
                TextSpanEvidence(
                    start=boundary,
                    end=len(text),
                    bbox=BoundingBox(x_min=195, y_min=20, x_max=380, y_max=40),
                ),
            ],
        )
    assert rejected.value.pending_diagnostic()["decision"] == "original_block_retained"
    assert document.pages[0].blocks[0].block_id == "mixed"


def test_page_zone_needs_matching_title_hierarchy_not_just_numbered_text() -> None:
    mismatched = assemble_semantics(
        _document(
            [
                _page(
                    301,
                    _title("list-heading", "2 轴心抗拉强度标准值", 0),
                    _body("explanation-clause", "4.1.4 说明文本。", 1),
                )
            ]
        )
    )
    assert mismatched.document.pages[0].page_type == PageType.UNKNOWN
    assert mismatched.document.clauses.normative == []

    explanation_like = assemble_semantics(
        _document(
            [
                _page(
                    282,
                    _title("chapter", "1 总则", 0),
                    _body("revision", "1.0.1 本次修订总结了上一版规范的应用。", 1),
                )
            ]
        )
    )
    assert explanation_like.document.pages[0].page_type == PageType.UNKNOWN


def test_contract_rejects_invalid_formula_reference_and_incomplete_cache_metadata() -> None:
    document = _document([_page(1, _title("ch", "1 总则", 0), _body("c", "1.0.1 正文。", 1))])
    result = assemble_semantics(document).document
    payload = result.model_dump(mode="json")
    payload["clauses"]["normative"][0]["clause_content"]["plain_text"] = "tampered"
    with pytest.raises(ValidationError):
        Document.model_validate(payload)


def test_formula_number_table_number_and_inline_references_are_not_clause_starts() -> None:
    result = assemble_semantics(
        _document(
            [
                _page(
                    1,
                    _body("ref", "按式(6.2.1-1)计算。", 0),
                    _body("table-number", "表9.1.2 数据", 1),
                    _body("item", "2 纵向钢筋。", 2),
                )
            ]
        )
    )
    assert result.document.clauses.normative == []


def test_page_group_source_conflict_is_prevented_by_classification() -> None:
    explanation = _page(282, _title("sec", "1 总则", 0), _body("e", "1.0.1 说明", 1))
    result = assemble_semantics(_document([explanation]), known_explanation_cover_page=277)
    assert result.document.clauses.normative == []
    assert result.document.clauses.explanations[0].source_block_ids == ["e"]


def _document(pages: list[Page], *, tables: list[LogicalTable] | None = None) -> Document:
    return Document(
        schema_version="2.4",
        document_id="document-semantic-fixture",
        bbox_coordinate_system=BboxCoordinateSystem(unit="pdf_points", origin="top_left"),
        source_file=FileRef(
            file_id="fixture-pdf",
            uri="memory://fixture.pdf",
            mime_type="application/pdf",
            sha256="a" * 64,
        ),
        standard=StandardMetadata(
            standard_name="虚构结构设计标准",
            standard_code="DEMO 1-2026",
            edition="演示版",
        ),
        page_count=500,
        pages=pages,
        tables=tables or [],
        clauses=ClauseGroups(),
        processing=ProcessingMetadata(
            parser_id="fixture",
            parser_version="1",
            partial=True,
            is_complete_document_ocr=False,
        ),
    )


def _page(page_number: int, *blocks: PageBlock) -> Page:
    normalized = [
        block.model_copy(update={"reading_order": index}) for index, block in enumerate(blocks)
    ]
    return Page(
        page_number=page_number,
        page_type=PageType.UNKNOWN,
        width=400,
        height=600,
        content_extraction_status=ContentExtractionStatus.PARTIALLY_TRANSCRIBED,
        blocks=normalized,
    )


def _title(block_id: str, text: str, order: int) -> PageBlock:
    return PageBlock(
        block_id=block_id,
        block_type=BlockType.TITLE,
        bbox=_bbox(20 + order * 30, 40 + order * 30),
        reading_order=order,
        ocr=OcrContent(text=text),
        recognition_status=RecognitionStatus.UNVERIFIED,
    )


def _body(block_id: str, text: str, order: int) -> PageBlock:
    return PageBlock(
        block_id=block_id,
        block_type=BlockType.BODY,
        bbox=_bbox(20 + order * 30, 40 + order * 30),
        reading_order=order,
        ocr=OcrContent(text=text),
        recognition_status=RecognitionStatus.UNVERIFIED,
    )


def _table_block(block_id: str, table_id: str, fragment: int, order: int) -> PageBlock:
    return PageBlock(
        block_id=block_id,
        block_type=BlockType.TABLE,
        bbox=_bbox(20 + order * 30, 40 + order * 30),
        reading_order=order,
        recognition_status=RecognitionStatus.UNVERIFIED,
        table_id=table_id,
        fragment_index=fragment,
        fragment_status=TableFragmentStatus.UNVERIFIED,
    )


def _bbox(y_min: float, y_max: float) -> BoundingBox:
    return BoundingBox(x_min=20, y_min=y_min, x_max=380, y_max=y_max)
