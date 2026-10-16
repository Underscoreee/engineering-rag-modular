"""Title classification geometry regressions for the MinerU adapter."""

from pathlib import Path

from engineering_rag.contracts.common import BoundingBox, FileRef
from engineering_rag.contracts.documents import BlockType, StandardMetadata
from engineering_rag.modules.document_parser.internal.mineru.models import (
    MinerUElement,
    MinerUPage,
    MinerUParseResult,
)
from engineering_rag.modules.document_parser.internal.mineru.title_geometry import (
    is_horizontally_centered,
)
from engineering_rag.modules.document_parser.internal.mineru.v24_adapter import adapt_to_v24


def test_horizontal_center_predicate_accepts_exact_tolerance_boundary() -> None:
    bbox = BoundingBox(x_min=220, y_min=10, x_max=260, y_max=30)

    assert is_horizontally_centered(bbox, page_width=400)


def test_horizontal_center_predicate_rejects_position_beyond_tolerance() -> None:
    bbox = BoundingBox(x_min=221, y_min=10, x_max=261, y_max=30)

    assert not is_horizontally_centered(bbox, page_width=400)


def test_off_center_mineru_title_candidate_is_downgraded_to_body() -> None:
    adaptation = _adapt(_title_result((0.10, 0.20, 0.30, 0.25)))

    assert adaptation.document.pages[0].blocks[0].block_type is BlockType.BODY


def test_centered_mineru_title_candidate_remains_title() -> None:
    adaptation = _adapt(_title_result((0.35, 0.20, 0.65, 0.25)))

    assert adaptation.document.pages[0].blocks[0].block_type is BlockType.TITLE


def _title_result(bbox: tuple[float, float, float, float]) -> MinerUParseResult:
    element = MinerUElement(
        page_number=53,
        page_idx=52,
        source_index=2,
        raw_type="paragraph_title",
        bbox={"x_min": bbox[0], "y_min": bbox[1], "x_max": bbox[2], "y_max": bbox[3]},
        text="1 钢筋混凝土构件",
        raw={"type": "paragraph_title", "content": "1 钢筋混凝土构件"},
    )
    return MinerUParseResult(
        schema_id="docvortex.middle",
        schema_version="2.0",
        producer_version="4.0.12",
        tier="basic",
        parse_mode="ocr",
        source_sha256="a" * 64,
        pages=[
            MinerUPage(
                page_number=53,
                page_idx=52,
                width_points=400,
                height_points=600,
                elements=[element],
            )
        ],
        raw_middle_json=Path("middle.json"),
        stdout_log=Path("stdout.log"),
        stderr_log=Path("stderr.log"),
        elapsed_seconds=1,
    )


def _adapt(result: MinerUParseResult):  # type: ignore[no-untyped-def]
    return adapt_to_v24(
        result,
        source_file=FileRef(
            file_id="title-geometry-test",
            uri="memory://title-geometry.pdf",
            mime_type="application/pdf",
            sha256=result.source_sha256,
        ),
        standard=StandardMetadata(
            standard_name="虚构标题几何测试标准",
            standard_code="DEMO-TITLE-2026",
            edition="演示版",
        ),
        page_count=100,
    )
