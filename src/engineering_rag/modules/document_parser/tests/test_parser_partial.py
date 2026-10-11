import pytest

pytest.importorskip("pymupdf")
pytest.importorskip("PIL")

from engineering_rag.contracts.documents import (  # noqa: E402
    ContentExtractionStatus,
    Document,
    PageType,
    RecognitionStatus,
)
from engineering_rag.modules.document_parser.internal.ocr import OcrSpan  # noqa: E402
from engineering_rag.modules.document_parser.internal.parser import (  # noqa: E402
    PyMuPdfDocumentParser,
)
from engineering_rag.modules.document_parser.tests.support import (  # noqa: E402
    FakeRecognizer,
    make_text_pdf,
    request_for,
)


def test_selected_page_ocr_returns_valid_partial_document_and_stable_ids() -> None:
    content = make_text_pdf(["FIRST", "SECOND"])
    store, request = request_for(content, pages="2", options={"force_ocr": True})
    recognizer = FakeRecognizer([OcrSpan("识别结果", (20, 30, 300, 100), 0.92, source_index=0)])
    parser = PyMuPdfDocumentParser(store, recognizer=recognizer)

    first = parser.parse(request)
    second = parser.parse(request)

    assert first.schema_version == "2.4"
    assert first.page_count == 2
    assert first.processing.partial is True
    assert first.processing.is_complete_document_ocr is False
    assert first.sections == [] and first.tables == []
    assert first.clauses.normative == [] and first.clauses.explanations == []
    assert first.pages[0].content_extraction_status == ContentExtractionStatus.NOT_PROCESSED
    assert first.pages[0].blocks == []
    selected = first.pages[1]
    assert selected.page_number == 2
    assert selected.page_type == PageType.UNKNOWN
    assert selected.content_extraction_status == ContentExtractionStatus.PARTIALLY_TRANSCRIBED
    assert selected.blocks[0].ocr is not None
    assert selected.blocks[0].ocr.text == "识别结果"
    assert selected.blocks[0].recognition_status == RecognitionStatus.UNVERIFIED
    assert selected.blocks[0].reading_order == 0
    assert first.document_id == second.document_id
    assert first.pages[1].blocks[0].block_id == second.pages[1].blocks[0].block_id
    assert Document.model_validate_json(first.model_dump_json()) == first
    assert parser.last_diagnostics is not None
    assert parser.last_diagnostics.selected_pages == [2]


def test_text_layer_is_used_without_calling_ocr_when_sufficient() -> None:
    content = make_text_pdf(["REAL TEXT LAYER"])
    store, request = request_for(content, options={"min_text_layer_chars": 1})
    recognizer = FakeRecognizer(error=AssertionError("OCR must not run"))
    document = PyMuPdfDocumentParser(store, recognizer=recognizer).parse(request)
    assert recognizer.calls == []
    assert document.pages[0].blocks[0].ocr is not None
    assert "REAL TEXT LAYER" in (document.pages[0].blocks[0].ocr.text or "")
    assert document.pages[0].blocks[0].extraction_method == "pymupdf_text_layer"


def test_reading_order_is_deterministic_by_position() -> None:
    content = make_text_pdf(["SCAN"])
    store, request = request_for(content, options={"force_ocr": True})
    recognizer = FakeRecognizer(
        [
            OcrSpan("bottom", (10, 200, 100, 240), 0.9, source_index=0),
            OcrSpan("top-right", (200, 10, 300, 50), 0.9, source_index=1),
            OcrSpan("top-left", (10, 10, 100, 50), 0.9, source_index=2),
        ]
    )
    document = PyMuPdfDocumentParser(store, recognizer=recognizer).parse(request)
    texts = [block.ocr.text for block in document.pages[0].blocks if block.ocr]
    assert texts == ["top-left", "top-right", "bottom"]
    assert [block.reading_order for block in document.pages[0].blocks] == [0, 1, 2]


def test_fake_ocr_confidence_is_reported_only_in_private_diagnostics() -> None:
    content = make_text_pdf(["SCAN"])
    store, request = request_for(content, options={"force_ocr": True})
    recognizer = FakeRecognizer(
        [
            OcrSpan("first", (10, 10, 100, 50), 0.4, source_index=0),
            OcrSpan("second", (10, 60, 100, 100), 0.8, source_index=1),
            OcrSpan("unknown", (10, 110, 100, 150), None, source_index=2),
        ]
    )
    parser = PyMuPdfDocumentParser(store, recognizer=recognizer)
    document = parser.parse(request)
    assert all(
        block.recognition_status == RecognitionStatus.UNVERIFIED
        for block in document.pages[0].blocks
    )
    assert parser.last_diagnostics is not None
    summary = parser.last_diagnostics.pages[0].ocr_confidence
    assert summary is not None
    assert summary.count == 2
    assert summary.minimum == pytest.approx(0.4)
    assert summary.maximum == pytest.approx(0.8)
    assert summary.mean == pytest.approx(0.6)


def test_text_crop_diagnostic_reaches_parser_sidecar() -> None:
    import pymupdf

    source_document = pymupdf.open()
    page = source_document.new_page(width=360, height=240)
    page.insert_text((36, 72), "LONG TEXT EXTENDING PAST CROP", fontsize=18)
    page.set_cropbox(pymupdf.Rect(20, 10, 140, 220))
    content = source_document.tobytes()
    source_document.close()
    store, request = request_for(content, options={"min_text_layer_chars": 1})
    parser = PyMuPdfDocumentParser(store, recognizer=FakeRecognizer())
    document = parser.parse(request)
    assert document.pages[0].blocks[0].bbox.x_max <= document.pages[0].width
    assert parser.last_diagnostics is not None
    assert "clipped to the visible CropBox" in parser.last_diagnostics.pages[0].messages[0]
