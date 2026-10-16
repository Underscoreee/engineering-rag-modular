from __future__ import annotations

from pathlib import Path

import pytest

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import BlockType, StandardMetadata
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUParseResult
from engineering_rag.modules.document_parser.internal.mineru.normalizer import (
    normalize_middle_json,
    read_middle_json,
)
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24

ROOT = Path(__file__).resolve().parents[2]
NORMALIZED = (
    ROOT
    / "data/eval/task1_6_e2e/runs/GB50010-2010-v3-partial"
    / "batches/batch-002/normalized-01.json"
)
MIDDLE_JSON = NORMALIZED.parent / "engine/raw/bundle/middle_json.json"


@pytest.fixture(scope="module")
def adaptation():
    result = MinerUParseResult.model_validate_json(NORMALIZED.read_text(encoding="utf-8"))
    return adapt_to_v24(
        result,
        source_file=FileRef(
            file_id="file-gb50010-v3",
            uri="fixture://gb50010-v3",
            mime_type="application/pdf",
            sha256=result.source_sha256,
        ),
        standard=StandardMetadata(
            standard_code="GB 50010-2010",
            standard_name="混凝土结构设计规范",
            edition="2015年版",
        ),
        page_count=441,
    )


def _page(adaptation, number: int):
    return next(page for page in adaptation.document.pages if page.page_number == number)


def _figures(adaptation, number: int):
    return [
        block for block in _page(adaptation, number).blocks if block.block_type == BlockType.IMAGE
    ]


def test_page_55_figure_6_2_10(adaptation) -> None:
    figures = _figures(adaptation, 55)
    assert len(figures) == 1
    assert figures[0].ocr is not None
    assert figures[0].ocr.text == "图6.2.10 矩形截面受弯构件正截面受弯承载力计算"


def test_page_56_figure_6_2_11(adaptation) -> None:
    figures = _figures(adaptation, 56)
    assert len(figures) == 1
    assert figures[0].ocr is not None
    assert figures[0].ocr.text == "图6.2.11 Ⅰ形截面受弯构件受压区高度位置"


def test_page_58_figure_6_2_15(adaptation) -> None:
    figures = _figures(adaptation, 58)
    assert len(figures) == 1
    assert figures[0].ocr is not None
    assert figures[0].ocr.text == "图6.2.15 配置箍筋的钢筋混凝土轴心受压构件"


def test_subfigure_labels_are_not_formulas(adaptation) -> None:
    formulas = [
        equation.latex or ""
        for block in _page(adaptation, 56).blocks
        if block.block_type == BlockType.FORMULA and block.ocr and block.ocr.formula_group
        for equation in block.ocr.formula_group.equations
    ]
    assert not any("h _ { \\mathrm { f } }" in latex and "\\tag" not in latex for latex in formulas)


def test_figure_caption_is_not_body(adaptation) -> None:
    for page_number in (55, 56, 58):
        texts = [
            block.ocr.text
            for block in _page(adaptation, page_number).blocks
            if block.block_type == BlockType.BODY and block.ocr
        ]
        assert not any(text and text.lstrip().startswith("图6.2.") for text in texts)


def test_one_caption_one_image_block(adaptation) -> None:
    assert [len(_figures(adaptation, number)) for number in (55, 56, 58)] == [1, 1, 1]
    assert len(adaptation.figure_sidecars) == 3


def test_figure_source_blocks_not_duplicated(adaptation) -> None:
    source_keys = [
        (record.source_page_number, record.source_index)
        for sidecar in adaptation.figure_sidecars
        for record in sidecar.source_consumption
    ]
    assert len(source_keys) == len(set(source_keys))
    final_ids = {block.block_id for page in adaptation.document.pages for block in page.blocks}
    consumed_non_anchor_ids = {
        record.source_block_id
        for sidecar in adaptation.figure_sidecars
        for record in sidecar.source_consumption
        if record.source_block_id != sidecar.block_id
    }
    assert final_ids.isdisjoint(consumed_non_anchor_ids)


def test_normalizer_preserves_figure_assets_and_caption() -> None:
    payload = read_middle_json(MIDDLE_JSON)
    _, _, _, pages, _ = normalize_middle_json(
        payload,
        expected_pages=[54, 55, 56, 57, 58],
        page_idx_to_original={index: index + 1 for index in range(53, 58)},
    )
    page_55 = next(page for page in pages if page.page_number == 55)
    image = next(element for element in page_55.elements if element.raw_type == "image")
    assert image.image_paths == ["images/page_54_image_0.jpg"]
    assert image.image_caption == "图6.2.10 矩形截面受弯构件正截面受弯承载力计算"


def test_figure_assembly_is_deterministic() -> None:
    result = MinerUParseResult.model_validate_json(NORMALIZED.read_text(encoding="utf-8"))
    arguments = {
        "source_file": FileRef(
            file_id="file-gb50010-v3",
            uri="fixture://gb50010-v3",
            mime_type="application/pdf",
            sha256=result.source_sha256,
        ),
        "standard": StandardMetadata(
            standard_code="GB 50010-2010",
            standard_name="混凝土结构设计规范",
            edition="2015年版",
        ),
        "page_count": 441,
    }
    first = adapt_to_v24(result, **arguments)
    second = adapt_to_v24(result, **arguments)
    assert first.document.model_dump(mode="json") == second.document.model_dump(mode="json")
    assert first.figure_sidecars == second.figure_sidecars
