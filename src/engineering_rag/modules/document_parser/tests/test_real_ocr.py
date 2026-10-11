import pytest

pytest.importorskip("pymupdf")
pytest.importorskip("PIL")
pytest.importorskip("rapidocr_onnxruntime")

from engineering_rag.modules.document_parser.internal.ocr_rapidocr import (  # noqa: E402
    RapidOcrRecognizer,
)
from engineering_rag.modules.document_parser.internal.parser import (  # noqa: E402
    PyMuPdfDocumentParser,
)
from engineering_rag.modules.document_parser.tests.support import (  # noqa: E402
    make_scanned_pdf,
    request_for,
)


def test_real_rapidocr_reads_synthetic_image_only_pdf() -> None:
    content = make_scanned_pdf("ENGINEERING PDF 2026")
    store, request = request_for(content, options={"force_ocr": True})
    document = PyMuPdfDocumentParser(store, recognizer=RapidOcrRecognizer()).parse(request)

    assert document.pages[0].blocks
    recognized = " ".join(block.ocr.text or "" for block in document.pages[0].blocks if block.ocr)
    assert "ENGINEERING" in recognized.upper()
    assert document.pages[0].blocks[0].bbox.x_max <= document.pages[0].width
    assert document.pages[0].blocks[0].bbox.y_max <= document.pages[0].height
    assert document.pages[0].blocks[0].recognition_status.value == "unverified"
