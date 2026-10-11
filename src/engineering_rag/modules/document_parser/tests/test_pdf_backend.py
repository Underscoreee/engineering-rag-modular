from io import BytesIO

import pytest

pymupdf = pytest.importorskip("pymupdf")

from engineering_rag.modules.document_parser.internal.pdf_backend import (  # noqa: E402
    PdfInputError,
    PdfResourceLimitError,
    PyMuPdfBackend,
)
from engineering_rag.modules.document_parser.tests.support import (  # noqa: E402
    make_scanned_pdf,
    make_text_pdf,
)


def test_reads_page_metadata_text_layer_and_scan() -> None:
    backend = PyMuPdfBackend()
    with backend.open(BytesIO(make_text_pdf(["PAGE ONE", "PAGE TWO"])), max_bytes=1_000_000) as pdf:
        assert pdf.page_count == 2
        assert pdf.page_metadata(1).width == pytest.approx(360)
        assert pdf.extract_text_spans(1)[0].text == "PAGE ONE"

    with backend.open(BytesIO(make_scanned_pdf()), max_bytes=10_000_000) as pdf:
        assert pdf.extract_text_spans(1) == []
        raster = pdf.rasterize(1, dpi=144, max_pixels=5_000_000)
        assert raster.pixel_width == 1400
        assert raster.pixel_height == 500
        assert raster.png_bytes.startswith(b"\x89PNG")


@pytest.mark.parametrize("content", [b"", b"not a pdf", b"%PDF-1.7 damaged body"])
def test_rejects_empty_and_non_pdf(content: bytes) -> None:
    with pytest.raises(PdfInputError), PyMuPdfBackend().open(BytesIO(content), max_bytes=1000):
        pass


def test_rejects_resource_limit_and_page_limit() -> None:
    content = make_text_pdf(["LIMIT"])
    with (
        pytest.raises(PdfResourceLimitError, match="byte limit"),
        PyMuPdfBackend().open(BytesIO(content), max_bytes=10),
    ):
        pass
    with (
        PyMuPdfBackend().open(BytesIO(content), max_bytes=1_000_000) as pdf,
        pytest.raises(PdfResourceLimitError, match="pixels"),
    ):
        pdf.rasterize(1, dpi=400, max_pixels=100)


def test_rejects_password_protected_pdf() -> None:
    document = pymupdf.open()
    document.new_page()
    content = document.tobytes(
        encryption=pymupdf.PDF_ENCRYPT_AES_256,
        owner_pw="owner",
        user_pw="user",
    )
    document.close()
    with (
        pytest.raises(PdfInputError, match="password-protected"),
        PyMuPdfBackend().open(BytesIO(content), max_bytes=1_000_000),
    ):
        pass


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("crop", [False, True])
def test_text_layer_bbox_uses_visible_page_coordinates(rotation: int, crop: bool) -> None:
    source = make_text_pdf(["SHORT TEXT"], rotate=rotation, crop=crop)
    with pymupdf.open(stream=source, filetype="pdf") as document:
        page = document[0]
        raw = page.get_text("blocks")[0]
        expected = pymupdf.Rect(raw[:4]) * page.rotation_matrix
    with PyMuPdfBackend().open(BytesIO(source), max_bytes=1_000_000) as pdf:
        actual = pdf.extract_text_spans(1)[0].bbox
        metadata = pdf.page_metadata(1)
    assert tuple(actual.model_dump().values()) == pytest.approx(tuple(expected), abs=1e-3)
    assert actual.x_max <= metadata.width
    assert actual.y_max <= metadata.height


def test_partially_visible_text_is_clipped_with_diagnostic() -> None:
    document = pymupdf.open()
    page = document.new_page(width=360, height=240)
    page.insert_text((36, 72), "THIS TEXT EXTENDS BEYOND THE CROP BOUNDARY", fontsize=18)
    page.set_cropbox(pymupdf.Rect(20, 10, 140, 220))
    source = document.tobytes()
    document.close()

    with PyMuPdfBackend().open(BytesIO(source), max_bytes=1_000_000) as pdf:
        span = pdf.extract_text_spans(1)[0]
        metadata = pdf.page_metadata(1)
        messages = pdf.text_diagnostics(1)
    assert span.clipped_to_visible_page is True
    assert span.bbox.x_max == pytest.approx(metadata.width)
    assert messages == ("text block 0 was clipped to the visible CropBox",)
