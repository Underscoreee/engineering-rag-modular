"""Task 1.4's 32 synthetic positive/negative formula contract cases."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.common import BoundingBox, FileRef
from engineering_rag.contracts.documents import (
    BlockType,
    Document,
    Equation,
    FormulaNumberStatus,
    PageBlock,
    RecognitionStatus,
    StandardMetadata,
    derive_clause_plain_text,
)
from engineering_rag.modules.document_parser.internal.formulas.assembler import (
    assemble_mineru_formulas,
)
from engineering_rag.modules.document_parser.internal.formulas.models import NumberEvidence
from engineering_rag.modules.document_parser.internal.formulas.number_matcher import match_number
from engineering_rag.modules.document_parser.internal.formulas.symbol_explanations import (
    collect_symbol_explanations,
    parse_plain_symbol_lines,
)
from engineering_rag.modules.document_parser.internal.mineru.models import (
    MinerUElement,
    MinerUPage,
    MinerUParseResult,
)
from engineering_rag.modules.document_parser.internal.mineru.normalizer import (
    MinerUProtocolError,
    normalize_middle_json,
)
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24
from engineering_rag.modules.document_parser.tests.path_helpers import (
    case_file_path,
    repository_root,
)

ROOT = repository_root(__file__)
SPEC = json.loads(case_file_path(__file__, "TASK_1_4_TEST_CASES.json").read_text(encoding="utf-8"))
CASES = SPEC["synthetic_test_cases"]


@pytest.mark.parametrize("case", CASES, ids=[item["id"] for item in CASES])
def test_task_1_4_synthetic_case(case: dict[str, object], tmp_path: Path) -> None:
    case_id = str(case["id"])
    if case_id == "F01":
        document = _adapt(_result([_equation(0, r"E=mc^2\tag{1.1-1}")])).document
        equation = _equations(document)[0]
        assert (equation.equation_number, equation.equation_number_status) == (
            "1.1-1",
            FormulaNumberStatus.PRINTED,
        )
        assert equation.recognition_status == RecognitionStatus.UNVERIFIED
    elif case_id == "F02":
        result = _result(
            [
                _equation(0, r"a=b\tag{6.2.1-1}"),
                _equation(1, r"c=d\tag{6.2.1-2}"),
                _text(2, "式中：a——演示量。"),
            ]
        )
        adaptation = _adapt(result)
        blocks = _formula_blocks(adaptation.document)
        assert len(blocks) == 1
        equations = blocks[0].ocr.formula_group.equations  # type: ignore[union-attr]
        assert len({item.formula_id for item in equations}) == 2
        assert blocks[0].ocr.formula_group.symbol_explanations is not None  # type: ignore[union-attr]
        assert adaptation.formula_sidecars[0].explanation_scope_formula_ids == [
            item.formula_id for item in equations
        ]
    elif case_id in {"F03", "F04"}:
        latex = str(case["input_hint"]["latex"])  # type: ignore[index]
        equation = _equations(_adapt(_result([_equation(0, latex)])).document)[0]
        assert equation.latex == latex
        assert len(_equations(_adapt(_result([_equation(0, latex)])).document)) == 1
    elif case_id == "F05":
        equation = _equations(_adapt(_result([_equation(0, "σ=f_c")])).document)[0]
        assert equation.equation_number is None
        assert equation.equation_number_status == FormulaNumberStatus.UNKNOWN
    elif case_id == "F06":
        equation = Equation(
            formula_id="human-reviewed",
            equation_number=None,
            equation_number_status="confirmed_absent",
            latex="x=y",
            recognition_status="verified",
        )
        assert equation.recognition_status == RecognitionStatus.VERIFIED
    elif case_id == "F07":
        equation = _equations(_adapt(_result([_equation(0, "x=y")])).document)[0]
        assert equation.equation_number_status == FormulaNumberStatus.UNKNOWN
    elif case_id == "F08":
        number, status, diagnostics = match_number(
            [NumberEvidence(raw_text="(6.2.1-1)", source_kind="body_text")]
        )
        assert number is None and status == FormulaNumberStatus.UNKNOWN
        assert any("body reference" in item for item in diagnostics)
    elif case_id == "F09":
        number, status, _ = match_number(
            [
                NumberEvidence(
                    raw_text="(N/mm²)",
                    source_kind="aligned_text",
                    right_of_equation=True,
                    vertical_overlap_ratio=1,
                )
            ]
        )
        assert number is None and status == FormulaNumberStatus.UNKNOWN
    elif case_id == "F10":
        number, _, _ = match_number([NumberEvidence(raw_text="6.2.1", source_kind="body_text")])
        assert number is None
    elif case_id == "F11":
        number, status, diagnostics = match_number(
            [
                NumberEvidence(raw_text="(3.1-1)", source_kind="number_region"),
                NumberEvidence(raw_text="(3.1-2)", source_kind="number_region"),
            ]
        )
        assert number is None and status == FormulaNumberStatus.UNKNOWN
        assert any("conflicting" in item for item in diagnostics)
    elif case_id == "F12":
        element = _equation(0, None, image_path="images/formula.png")
        adaptation = _adapt(_result([element]))
        equation = _equations(adaptation.document)[0]
        assert equation.latex is None
        assert equation.recognition_status == RecognitionStatus.NOT_TRANSCRIBED
        assert adaptation.formula_sidecars[0].equations[0].raw_asset_ref == "images/formula.png"
    elif case_id == "F13":
        latex = str(case["input_hint"]["latex"])  # type: ignore[index]
        assert _equations(_adapt(_result([_equation(0, latex)])).document)[0].latex == latex
    elif case_id == "F14":
        parsed = parse_plain_symbol_lines([str(case["input_hint"]["raw_body"])])  # type: ignore[index]
        assert parsed is not None and len(parsed.items) == 3
        assert parsed.items[0].description == "混凝土压应力"
    elif case_id == "F15":
        lines = [str(item) for item in case["input_hint"]["raw_lines"]]  # type: ignore[index]
        parsed = parse_plain_symbol_lines(lines)
        assert parsed is not None and len(parsed.items) == 2
        assert "按有关规范采用" in parsed.items[0].description
    elif case_id == "F16":
        parsed = parse_plain_symbol_lines([str(case["input_hint"]["raw_body"])])  # type: ignore[index]
        assert parsed is not None and parsed.items[0].symbol == "δ"
        assert parsed.items[0].latex is None
    elif case_id == "F17":
        elements = [_text(0, "式中：a——长度。"), _text(1, "6.2.2 新条文"), _text(2, "无关")]
        parsed, evidence, end = collect_symbol_explanations(elements, 0)
        assert parsed is not None and len(parsed.items) == 1
        assert evidence.source_indices == [0] and end == 1
    elif case_id == "F18":
        blocks = _formula_blocks(
            _adapt(_result([_equation(0, "a=b"), _equation(1, "c=d")])).document
        )
        assert len(blocks) == 2
        assert len({block.formula_group_id for block in blocks}) == 2
    elif case_id == "F19":
        document = _adapt(_result([_text(0, "当f_c≤f时，取β=1.0")])).document
        assert _formula_blocks(document) == []
        assert document.pages[0].blocks[0].block_type == BlockType.BODY
    elif case_id == "F20":
        document = _adapt(_result([_equation(0, "x=y", bbox=[0.1, 0.2, 0.5, 0.8])])).document
        bbox = _formula_blocks(document)[0].bbox
        assert bbox == BoundingBox(x_min=40, y_min=120, x_max=200, y_max=480)
    elif case_id == "F21":
        document = _adapt(_result([_equation(0, "x=y", page=301, page_idx=0)])).document
        assert document.pages[0].page_number == 301
    elif case_id == "F22":
        first = _adapt(_result([_equation(7, "x=1")])).document
        second = _adapt(_result([_equation(7, "x=l")])).document
        assert _formula_blocks(first)[0].block_id == _formula_blocks(second)[0].block_id
        assert _equations(first)[0].formula_id == _equations(second)[0].formula_id
    elif case_id == "F23":
        result = _result(
            [
                _text(0, "保留正文"),
                _table(1),
                _equation(2, r"x=y\tag{1.1-1}"),
            ]
        )
        first = _adapt(result).document
        second = _adapt(result).document
        assert first == second
        assert len(first.tables) == 1
        assert [block.block_type for block in first.pages[0].blocks] == [
            BlockType.BODY,
            BlockType.TABLE,
            BlockType.FORMULA,
        ]
    elif case_id == "F24":
        result = _result([_equation(0, "x=y", bbox=None, force_missing_bbox=True)])
        assembly = assemble_mineru_formulas(result)
        assert assembly.placements == {}
        assert assembly.omitted[0]["reason"] == "missing_or_invalid_bbox"
    elif case_id == "F25":
        with pytest.raises(MinerUProtocolError, match="docvortex.middle"):
            normalize_middle_json({"pdf_info": []}, expected_pages=[1])
    elif case_id == "F26":
        adaptation = _adapt(
            _result([_equation(0, "x=y", image_path="../../outside.png")], raw_root=tmp_path)
        )
        diagnostics = adaptation.formula_sidecars[0].equations[0].diagnostics
        assert "rejected unsafe formula image path" in diagnostics
    elif case_id == "F27":
        with pytest.raises(ValidationError):
            Equation(
                formula_id="f1",
                equation_number="1.2-1",
                equation_number_status="printed",
                latex=None,
                recognition_status="verified",
            )
    elif case_id == "F28":
        with pytest.raises(ValidationError):
            Equation(
                formula_id="f1",
                equation_number=None,
                equation_number_status="confirmed_absent",
                latex="x=y",
                recognition_status="unverified",
            )
    elif case_id == "F29":
        with pytest.raises(ValidationError):
            PageBlock(
                block_id="b1",
                block_type="formula",
                bbox=BoundingBox(x_min=0, y_min=0, x_max=1, y_max=1),
                reading_order=0,
                recognition_status="unverified",
            )
    elif case_id == "F30":
        with pytest.raises(ValidationError):
            PageBlock(
                block_id="b1",
                block_type="body",
                bbox=BoundingBox(x_min=0, y_min=0, x_max=1, y_max=1),
                reading_order=0,
                recognition_status="unverified",
                formula_group_id="fg1",
            )
    elif case_id == "F31":
        document = Document.model_validate_json(
            (ROOT / "examples/document.example.json").read_text(encoding="utf-8")
        )
        rendered = derive_clause_plain_text(document, document.clauses.normative[0])
        assert rendered is not None and "虚构量" in rendered[0]
        assert rendered[0].count("式中：q：虚构量") == 1
    elif case_id == "F32":
        raw = "l_0=O.5"
        adaptation = _adapt(_result([_equation(0, raw)]))
        assert _equations(adaptation.document)[0].latex == raw
        diagnostics = adaptation.formula_sidecars[0].equations[0].diagnostics
        assert any("O/0" in item for item in diagnostics)
        assert any("l/1" in item for item in diagnostics)
    else:  # pragma: no cover - makes additions to the specification fail loudly
        raise AssertionError(f"unimplemented Task 1.4 case: {case_id}")


def _adapt(result: MinerUParseResult):  # type: ignore[no-untyped-def]
    return adapt_to_v24(
        result,
        source_file=FileRef(
            file_id="synthetic-formula-file",
            uri="memory://synthetic.pdf",
            mime_type="application/pdf",
            sha256=result.source_sha256,
        ),
        standard=StandardMetadata(
            standard_name="虚构公式测试标准",
            standard_code="DEMO-FORMULA-2026",
            edition="演示版",
        ),
        page_count=500,
    )


def _result(elements: list[MinerUElement], *, raw_root: Path | None = None) -> MinerUParseResult:
    page = elements[0].page_number if elements else 1
    page_idx = elements[0].page_idx if elements else page - 1
    root = raw_root or Path("raw")
    return MinerUParseResult(
        schema_id="docvortex.middle",
        schema_version="2.0",
        producer_version="4.0.12",
        tier="basic",
        parse_mode="ocr",
        source_sha256="d" * 64,
        pages=[
            MinerUPage(
                page_number=page,
                page_idx=page_idx,
                width_points=400,
                height_points=600,
                elements=elements,
            )
        ],
        raw_middle_json=root / "middle_json.json",
        stdout_log=root / "stdout.log",
        stderr_log=root / "stderr.log",
        elapsed_seconds=1,
    )


def _equation(
    index: int,
    latex: str | None,
    *,
    page: int = 1,
    page_idx: int | None = None,
    bbox: list[float] | None = None,
    force_missing_bbox: bool = False,
    image_path: str = "images/formula.jpg",
) -> MinerUElement:
    actual_bbox = None if force_missing_bbox else bbox or [0.2, 0.2, 0.8, 0.3]
    raw: dict[str, object] = {"type": "equation", "content": latex}
    if image_path:
        raw["image_path"] = image_path
    return MinerUElement(
        page_number=page,
        page_idx=page - 1 if page_idx is None else page_idx,
        source_index=index,
        raw_type="equation",
        bbox=(
            None
            if actual_bbox is None
            else {
                "x_min": actual_bbox[0],
                "y_min": actual_bbox[1],
                "x_max": actual_bbox[2],
                "y_max": actual_bbox[3],
            }
        ),
        latex=latex,
        raw=raw,
    )


def _text(index: int, text: str) -> MinerUElement:
    return MinerUElement(
        page_number=1,
        page_idx=0,
        source_index=index,
        raw_type="text",
        bbox={"x_min": 0.1, "y_min": 0.4, "x_max": 0.9, "y_max": 0.45},
        text=text,
        raw={"type": "text", "content": [{"type": "text", "content": text}]},
    )


def _table(index: int) -> MinerUElement:
    return MinerUElement(
        page_number=1,
        page_idx=0,
        source_index=index,
        raw_type="table",
        bbox={"x_min": 0.1, "y_min": 0.5, "x_max": 0.9, "y_max": 0.7},
        table_html="<table><tr><td>A</td></tr></table>",
        table_caption="表 1.1 演示",
        raw={"type": "table"},
    )


def _formula_blocks(document: Document) -> list[PageBlock]:
    return [
        block
        for page in document.pages
        for block in page.blocks
        if block.block_type == BlockType.FORMULA
    ]


def _equations(document: Document) -> list[Equation]:
    return [
        equation
        for block in _formula_blocks(document)
        if block.ocr is not None and block.ocr.formula_group is not None
        for equation in block.ocr.formula_group.equations
    ]
