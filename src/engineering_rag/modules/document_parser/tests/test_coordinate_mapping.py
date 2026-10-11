from io import BytesIO

import pytest

pytest.importorskip("pymupdf")

from engineering_rag.contracts.common import BoundingBox  # noqa: E402
from engineering_rag.modules.document_parser.internal.pdf_backend import (  # noqa: E402
    PyMuPdfBackend,
    RasterizedPage,
    pdf_bbox_to_pixel,
    pixel_bbox_to_pdf,
)
from engineering_rag.modules.document_parser.tests.support import make_text_pdf  # noqa: E402


def test_pixel_pdf_mapping_round_trip_at_non_square_scale() -> None:
    raster = RasterizedPage(
        page_number=1,
        page_width=400,
        page_height=200,
        pixel_width=1000,
        pixel_height=800,
        dpi=180,
        png_bytes=b"png",
    )
    mapped = pixel_bbox_to_pdf((100, 80, 900, 720), raster)
    assert mapped == BoundingBox(x_min=40, y_min=20, x_max=360, y_max=180)
    assert pdf_bbox_to_pixel(mapped, raster) == pytest.approx((100, 80, 900, 720))


@pytest.mark.parametrize(
    "bbox",
    [(-1, 0, 10, 10), (0, 0, 1001, 10), (5, 5, 5, 8), (0, 0, float("nan"), 2)],
)
def test_invalid_ocr_bbox_is_rejected(bbox: tuple[float, ...]) -> None:
    raster = RasterizedPage(1, 100, 100, 1000, 1000, 200, b"png")
    with pytest.raises(ValueError):
        pixel_bbox_to_pdf(bbox, raster)  # type: ignore[arg-type]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_full_raster_maps_to_visible_rotated_and_cropped_page(rotation: int) -> None:
    content = make_text_pdf(["ROTATED"], rotate=rotation, crop=True)
    with PyMuPdfBackend().open(BytesIO(content), max_bytes=1_000_000) as pdf:
        metadata = pdf.page_metadata(1)
        raster = pdf.rasterize(1, dpi=173, max_pixels=5_000_000)
        full = pixel_bbox_to_pdf((0, 0, raster.pixel_width, raster.pixel_height), raster)
        assert full.x_max == pytest.approx(metadata.width)
        assert full.y_max == pytest.approx(metadata.height)
