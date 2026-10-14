"""Regression coverage for the page-50 formula context and dedup repair."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import (
    BlockType,
    Clause,
    ClauseContent,
    ClauseContentType,
    ClauseContentUnit,
    ClauseGroups,
    Document,
    PageType,
    Section,
    StandardMetadata,
    derive_clause_plain_text,
)
from engineering_rag.modules.document_parser.internal.formulas.reference_migration import (
    FormulaReferenceMigrationError,
    migrate_formula_clause_references,
)
from engineering_rag.modules.document_parser.internal.mineru.models import (
    MinerUElement,
    MinerUPage,
    MinerUParseResult,
)
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24

SOURCE_SHA256 = "43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682"


def test_page_50_conditions_are_bound_only_to_their_equations() -> None:
    adaptation = _adapt(_page_50_result())
    equations = _equations(adaptation.document)

    assert "ε_c ≤ ε_0" in equations["6.2.1-1"].text
    assert r"\ll" not in equations["6.2.1-1"].text
    assert r"\sigma_{\mathrm{c}}=f_{\mathrm{c}}" in equations["6.2.1-1"].text
    assert equations["6.2.1-1"].text.count("6.2.1-1") == 1
    assert "ε_0 < ε_c ≤ ε_cu" in equations["6.2.1-2"].text
    assert r"\sigma_{\mathrm{c}} = f_{\mathrm{c}}" in equations["6.2.1-2"].text
    assert equations["6.2.1-2"].text.count("6.2.1-2") == 1
    assert all(equations[number].text is None for number in ("6.2.1-3", "6.2.1-4", "6.2.1-5"))

    links = [link for sidecar in adaptation.formula_sidecars for link in sidecar.conditions]
    assert [link.normalized_text for link in links] == ["当 ε_c ≤ ε_0 时", "当 ε_0 < ε_c ≤ ε_cu 时"]
    assert links[0].raw_text.endswith(r"\ll \varepsilon _ { 0 }时")
    assert links[0].target_formula_ids == [equations["6.2.1-1"].formula_id]
    assert links[1].target_formula_ids == [equations["6.2.1-2"].formula_id]


def test_page_50_builds_two_complete_semantic_groups() -> None:
    adaptation = _adapt(_page_50_result())
    document = adaptation.document
    blocks = document.pages[0].blocks
    formula_blocks = [block for block in blocks if block.block_type == BlockType.FORMULA]
    assert len(blocks) == 6
    assert [_numbers(block) for block in formula_blocks] == [
        [f"6.2.1-{index}" for index in range(1, 6)],
        ["6.2.1-6", "6.2.1-7"],
    ]
    assert [
        len(block.ocr.formula_group.symbol_explanations.items)
        for block in formula_blocks
        if block.ocr and block.ocr.formula_group and block.ocr.formula_group.symbol_explanations
    ] == [6, 2]
    assert [
        block.ocr.text
        for block in blocks
        if block.block_type == BlockType.BODY and block.ocr is not None
    ] == [
        "2不考虑混凝土的抗拉强度。",
        "3 混凝土受压的应力与应变关系按下列规定取用:",
        "4 纵向受拉钢筋的极限拉应变取为0.01。",
        "5 纵向钢筋的应力取钢筋应变与其弹性模量的乘积。",
    ]
    for block, sidecar in zip(formula_blocks, adaptation.formula_sidecars, strict=True):
        for component in sidecar.semantic_components:
            assert block.bbox.x_min <= component.component_bbox.x_min * document.pages[0].width
            assert block.bbox.y_min <= component.component_bbox.y_min * document.pages[0].height
            assert block.bbox.x_max >= component.component_bbox.x_max * document.pages[0].width
            assert block.bbox.y_max >= component.component_bbox.y_max * document.pages[0].height


def test_all_preserved_semantic_sources_are_consumed_from_body_view() -> None:
    adaptation = _adapt(_page_50_result())
    body_texts = [
        block.ocr.text
        for block in adaptation.document.pages[0].blocks
        if block.block_type == BlockType.BODY and block.ocr is not None
    ]
    assert not any(
        text and text.startswith("式中:") and "混凝土压应变" in text for text in body_texts
    )
    assert not any(text and text.startswith("f_") and "轴心抗压" in text for text in body_texts)
    assert not any(text and text.startswith("式中:") and "普通钢筋" in text for text in body_texts)
    assert not any(text and text.endswith("混凝土法向应") for text in body_texts)
    assert not any(text and text.startswith("当") for text in body_texts)

    coverage = adaptation.formula_dedup_coverage
    assert len([item for item in coverage if item.duplicate_disposition == "consumed"]) == 8
    incomplete = [item for item in coverage if item.cross_page_incomplete]
    assert len(incomplete) == 1 and incomplete[0].source_index == 20
    assert incomplete[0].raw_text.endswith("混凝土法向应")
    assert incomplete[0].review_status == "needs_review"


def test_clause_plain_text_keeps_formula_context_and_one_authoritative_symbol_copy() -> None:
    document = _adapt(_page_50_result()).document
    document.pages[0].page_type = PageType.BODY
    formula_blocks = [
        block for block in document.pages[0].blocks if block.block_type == BlockType.FORMULA
    ]
    units = [
        ClauseContentUnit(
            order=index,
            content_type=ClauseContentType.FORMULA,
            source_block_ids=[block.block_id],
            formula_ids=[equation.formula_id for equation in block.ocr.formula_group.equations],
        )
        for index, block in enumerate(formula_blocks)
        if block.ocr is not None and block.ocr.formula_group is not None
    ]
    document.sections = [
        Section(
            section_id="section-fixture",
            title="测试用章节",
            section_type="section",
            content_group="normative",
            structure_path=["测试用章节"],
        )
    ]
    clause = Clause(
        clause_id="clause-fixture",
        clause_number="fixture",
        section_id="section-fixture",
        clause_content=ClauseContent(content_units=units, transcription_status="unverified"),
        page_start=50,
        page_end=50,
        source_block_ids=[block.block_id for block in formula_blocks],
    )
    document.clauses.normative = [clause]
    document = Document.model_validate_json(document.model_dump_json())

    rendered = derive_clause_plain_text(document, document.clauses.normative[0])
    assert rendered is not None
    text = rendered[0]
    assert "ε_c ≤ ε_0" in text and "ε_0 < ε_c ≤ ε_cu" in text
    equations = _equations(document)
    assert equations
    assert r"\sigma_{\mathrm{c}}=f_{\mathrm{c}}" in text
    assert r"\sigma_{\mathrm{c}} = f_{\mathrm{c}}" in text
    assert text.count("6.2.1-1") == 1
    assert text.count("6.2.1-2") == 1
    assert text.count("混凝土轴心抗压强度设计值") == 1
    assert text.count("第i层纵向普通钢筋、预应力筋的应力") == 1


def test_repair_is_deterministic_and_round_trips() -> None:
    result = _page_50_result()
    first = _adapt(result)
    second = _adapt(deepcopy(result))
    assert first.document == second.document
    assert first.formula_sidecars == second.formula_sidecars
    assert first.formula_dedup_coverage == second.formula_dedup_coverage
    assert [item.lineage for item in first.formula_sidecars] == [
        item.lineage for item in second.formula_sidecars
    ]
    assert Document.model_validate_json(first.document.model_dump_json()) == first.document


def test_condition_false_positives_are_not_bound() -> None:
    result = _page_50_result()
    result.source_sha256 = "d" * 64
    result.pages[0].elements[0:4] = [
        _text(0, "正文讨论式（6.2.1-1），不构成适用条件。", [0.1, 0.1, 0.8, 0.12]),
        _text(1, r"当 x \ll y 时", [0.01, 0.14, 0.2, 0.16]),
        _equation(2, r"x=y\tag{1.1-1}", [0.7, 0.17, 0.9, 0.2]),
        _equation(3, r"y=z\tag{1.1-2}", [0.7, 0.22, 0.9, 0.25]),
    ]
    result.pages[0].elements = result.pages[0].elements[:4]
    adaptation = _adapt(result)
    assert all(equation.text is None for equation in _equations(adaptation.document).values())
    assert any(
        "unresolved" in diagnostic
        for sidecar in adaptation.formula_sidecars
        for diagnostic in sidecar.diagnostics
    )


def test_mixed_symbol_and_body_block_is_not_deleted() -> None:
    result = _page_50_result()
    result.source_sha256 = "e" * 64
    result.pages[0].elements = [
        _equation(0, r"a=b\tag{1.1-1}", [0.2, 0.2, 0.8, 0.25]),
        _text(1, "式中：a——长度。随后是普通正文", [0.1, 0.3, 0.9, 0.35]),
    ]
    adaptation = _adapt(result)
    bodies = [
        block for block in adaptation.document.pages[0].blocks if block.block_type == BlockType.BODY
    ]
    assert len(bodies) == 1
    assert bodies[0].ocr is not None
    assert bodies[0].ocr.text == "式中：a——长度。随后是普通正文"
    assert adaptation.formula_dedup_coverage[0].duplicate_disposition == "dedup_unresolved"


def test_formula_block_aliases_migrate_formula_references_and_revalidate() -> None:
    adaptation = _adapt(_page_50_result())
    document = adaptation.document
    document.pages[0].page_type = PageType.BODY
    sidecar = adaptation.formula_sidecars[0]
    old_block_ids = [item.old_block_id for item in sidecar.lineage]
    formula_ids = [item.formula_id for item in sidecar.equations]
    clause = Clause(
        clause_id="clause-alias-fixture",
        clause_number="fixture",
        section_id="section-fixture",
        clause_content=ClauseContent(
            content_units=[
                ClauseContentUnit(
                    order=0,
                    content_type=ClauseContentType.FORMULA,
                    source_block_ids=old_block_ids,
                    formula_ids=formula_ids,
                )
            ],
            transcription_status="unverified",
        ),
        page_start=50,
        page_end=50,
        source_block_ids=old_block_ids,
    )
    migrated = migrate_formula_clause_references(
        ClauseGroups(normative=[clause]),
        lineage=sidecar.lineage,
        consumed_body_block_ids=set(),
    )
    document.sections = [
        Section(
            section_id="section-fixture",
            title="测试用章节",
            section_type="section",
            content_group="normative",
            structure_path=["测试用章节"],
        )
    ]
    document.clauses = migrated
    validated = Document.model_validate_json(document.model_dump_json())
    unit = validated.clauses.normative[0].clause_content.content_units[0]
    assert unit.source_block_ids == [sidecar.block_id]


def test_consumed_body_reference_stops_group_migration_safely() -> None:
    adaptation = _adapt(_page_50_result())
    condition_block_id = adaptation.formula_sidecars[0].conditions[0].raw_source_block_ids[0]
    clause = Clause(
        clause_id="clause-unsafe-fixture",
        clause_number="fixture",
        section_id="section-fixture",
        clause_content=ClauseContent(
            content_units=[
                ClauseContentUnit(
                    order=0,
                    content_type=ClauseContentType.BODY,
                    source_block_ids=[condition_block_id],
                )
            ],
            transcription_status="unverified",
        ),
        page_start=50,
        page_end=50,
        source_block_ids=[condition_block_id],
    )
    with pytest.raises(FormulaReferenceMigrationError, match="consumed"):
        migrate_formula_clause_references(
            ClauseGroups(normative=[clause]),
            lineage=adaptation.formula_sidecars[0].lineage,
            consumed_body_block_ids={condition_block_id},
        )


def _adapt(result: MinerUParseResult):  # type: ignore[no-untyped-def]
    return adapt_to_v24(
        result,
        source_file=FileRef(
            file_id="sha256-page-50-fixture",
            uri="fixture.pdf",
            mime_type="application/pdf",
            sha256=result.source_sha256,
        ),
        standard=StandardMetadata(
            standard_name="混凝土结构设计规范",
            standard_code="GB 50010-2010",
            edition="2015年版",
        ),
        page_count=336,
    )


def _page_50_result() -> MinerUParseResult:
    elements = [
        _text(0, "2不考虑混凝土的抗拉强度。", [0.185, 0.086, 0.547, 0.108]),
        _text(1, "3 混凝土受压的应力与应变关系按下列规定取用:", [0.185, 0.113, 0.791, 0.135]),
        _text(2, _condition_one(), [0.188, 0.14, 0.348, 0.162], inline=_condition_one_inline()),
        _equation(
            3,
            r"\sigma_{\mathrm{c}}=f_{\mathrm{c}}\left[1-\left(1-\frac{\varepsilon_{\mathrm{c}}}{\varepsilon_{0}}\right)^{n}\right]\tag{6.2.1-1}",
            [0.364, 0.17, 0.895, 0.209],
        ),
        _text(4, _condition_two(), [0.189, 0.217, 0.414, 0.238], inline=_condition_two_inline()),
        _equation(
            5, r"\sigma_{\mathrm{c}} = f_{\mathrm{c}}\tag{6.2.1-2}", [0.467, 0.244, 0.895, 0.267]
        ),
        _equation(
            6,
            r"n = 2 - \frac{1}{60} \left( f_{cu,k} - 50 \right)\tag{6.2.1-3}",
            [0.371, 0.274, 0.895, 0.312],
        ),
        _equation(
            7,
            r"\varepsilon_{0}=0.002+0.5\left(f_{\mathrm{cu,k}}-50\right)\times10^{-5}\tag{6.2.1-4}",
            [0.294, 0.318, 0.895, 0.342],
        ),
        _equation(
            8,
            r"\varepsilon_{cu}=0.0033-(f_{cu,k}-50)\times10^{-5}\tag{6.2.1-5}",
            [0.306, 0.346, 0.895, 0.369],
        ),
        _symbol_text(
            9,
            "式中:",
            r"\sigma _ { \mathrm { c } }",
            "混凝土压应变为 ε_c 时的混凝土压应力；",
            [0.133, 0.375, 0.752, 0.397],
        ),
        _symbol_text(
            10,
            "",
            r"f_{\mathrm{c}}",
            "混凝土轴心抗压强度设计值，按本规范表4.1.4-1采用；",
            [0.201, 0.402, 0.898, 0.451],
        ),
        _symbol_text(
            11,
            "",
            r"\varepsilon _ { 0 }",
            "混凝土压应力达到 f_c 时的混凝土压应变，当计算值小于0.002时，取为0.002；",
            [0.205, 0.456, 0.9, 0.506],
        ),
        _symbol_text(
            12,
            "",
            r"\varepsilon _ { \mathrm { c u } }",
            "正截面的混凝土极限压应变，当处于轴心受压时取为 ε_0 i",
            [0.198, 0.511, 0.9, 0.588],
        ),
        _symbol_text(
            13,
            "",
            r"f _ { \mathrm { c u , k } }",
            "混凝土立方体抗压强度标准值，按本规范第4.1.1条确定；",
            [0.18, 0.593, 0.899, 0.642],
        ),
        _text(14, "n 系数，当计算的n值大于2.0时，取为2.0。", [0.214, 0.648, 0.819, 0.67]),
        _text(15, "4 纵向受拉钢筋的极限拉应变取为0.01。", [0.187, 0.675, 0.691, 0.696]),
        _text(16, "5 纵向钢筋的应力取钢筋应变与其弹性模量的乘积。", [0.134, 0.702, 0.901, 0.751]),
        _equation(
            17,
            r"-f_{\mathrm{y}}^{\prime} \leqslant \sigma_{\mathrm{s}i} "
            r"\leqslant f_{\mathrm{y}}\tag{6.2.1-6}",
            [0.416, 0.755, 0.896, 0.779],
        ),
        _equation(
            18,
            r"\sigma_{\mathrm{p}0i}-f_{\mathrm{py}}^{\prime} \leqslant "
            r"\sigma_{\mathrm{p}i} \leqslant f_{\mathrm{py}}\tag{6.2.1-7}",
            [0.388, 0.783, 0.896, 0.807],
        ),
        _symbol_text(
            19,
            "式中:",
            r"\sigma _ { s i }",
            "第i层纵向普通钢筋、预应力筋的应力，正值代表拉应力，负值代表压应力；",
            [0.133, 0.811, 0.9, 0.86],
        ),
        _symbol_text(
            20,
            "",
            r"\sigma _ { \mathrm { p 0 } i }",
            "第i层纵向预应力筋截面重心处混凝土法向应",
            [0.248, 0.865, 0.901, 0.888],
        ),
        _text(21, "35", [0.846, 0.903, 0.879, 0.921], raw_type="page_number"),
    ]
    return MinerUParseResult(
        schema_id="docvortex.middle",
        schema_version="2.0",
        producer_version="4.0.12",
        tier="basic",
        parse_mode="ocr",
        source_sha256=SOURCE_SHA256,
        pages=[
            MinerUPage(
                page_number=50, page_idx=49, width_points=595, height_points=842, elements=elements
            )
        ],
        raw_middle_json=Path("fixture/middle_json.json"),
        stdout_log=Path("fixture/stdout.log"),
        stderr_log=Path("fixture/stderr.log"),
        elapsed_seconds=29.466,
    )


def _text(
    index: int, text: str, bbox: list[float], *, inline: str | None = None, raw_type: str = "text"
) -> MinerUElement:
    content = (
        [
            {"type": "text", "content": "当 "},
            {"type": "equation_inline", "content": inline},
            {"type": "text", "content": " 时"},
        ]
        if inline
        else [{"type": "text", "content": text}]
    )
    return MinerUElement(
        page_number=50,
        page_idx=49,
        source_index=index,
        raw_type=raw_type,
        bbox={"x_min": bbox[0], "y_min": bbox[1], "x_max": bbox[2], "y_max": bbox[3]},
        text=text,
        raw={"type": raw_type, "index": index, "bbox": bbox, "content": content},
    )


def _equation(index: int, latex: str, bbox: list[float]) -> MinerUElement:
    return MinerUElement(
        page_number=50,
        page_idx=49,
        source_index=index,
        raw_type="equation",
        bbox={"x_min": bbox[0], "y_min": bbox[1], "x_max": bbox[2], "y_max": bbox[3]},
        latex=latex,
        raw={"type": "equation", "index": index, "bbox": bbox, "content": latex},
    )


def _symbol_text(
    index: int, prefix: str, symbol: str, description: str, bbox: list[float]
) -> MinerUElement:
    text = f"{prefix}{symbol}{description}"
    content = []
    if prefix:
        content.append({"type": "text", "content": prefix})
    content.extend(
        [
            {"type": "equation_inline", "content": symbol},
            {"type": "text", "content": f" {description}"},
        ]
    )
    return MinerUElement(
        page_number=50,
        page_idx=49,
        source_index=index,
        raw_type="text",
        bbox={"x_min": bbox[0], "y_min": bbox[1], "x_max": bbox[2], "y_max": bbox[3]},
        text=text,
        raw={"type": "text", "index": index, "bbox": bbox, "content": content},
    )


def _equations(document: Document):  # type: ignore[no-untyped-def]
    return {
        equation.equation_number: equation
        for page in document.pages
        for block in page.blocks
        if block.ocr and block.ocr.formula_group
        for equation in block.ocr.formula_group.equations
    }


def _numbers(block):  # type: ignore[no-untyped-def]
    return (
        [equation.equation_number for equation in block.ocr.formula_group.equations]
        if block.ocr and block.ocr.formula_group
        else []
    )


def _condition_one() -> str:
    return r"当\varepsilon _ { \mathtt { c } } \ll \varepsilon _ { 0 }时"


def _condition_one_inline() -> str:
    return r"\varepsilon _ { \mathtt { c } } \ll \varepsilon _ { 0 }"


def _condition_two() -> str:
    return (
        r"当\varepsilon _ { 0 } < \varepsilon _ { \mathrm { c } } "
        r"\leqslant \varepsilon _ { \mathrm { c u } }时"
    )


def _condition_two_inline() -> str:
    return (
        r"\varepsilon _ { 0 } < \varepsilon _ { \mathrm { c } } "
        r"\leqslant \varepsilon _ { \mathrm { c u } }"
    )
