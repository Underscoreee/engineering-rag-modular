from contextlib import contextmanager
from io import BytesIO

import pytest

pytest.importorskip("pymupdf")

from engineering_rag.contracts.common import FileRef  # noqa: E402
from engineering_rag.contracts.documents import ParseConfig, ParseRequest  # noqa: E402
from engineering_rag.modules.document_parser.internal.config import (  # noqa: E402
    ParserConfigurationError,
)
from engineering_rag.modules.document_parser.internal.ocr import OcrSpan  # noqa: E402
from engineering_rag.modules.document_parser.internal.parser import (  # noqa: E402
    DocumentParserError,
    PageProcessingError,
    PyMuPdfDocumentParser,
)
from engineering_rag.modules.document_parser.tests.support import (  # noqa: E402
    FailingRecognizer,
    FakeRecognizer,
    MemoryFileStore,
    make_text_pdf,
    request_for,
)


def test_missing_standard_is_rejected() -> None:
    content = make_text_pdf(["PAGE"])
    store, request = request_for(content)
    request_without_standard = ParseRequest(
        source_file=request.source_file,
        config=request.config,
    )
    with pytest.raises(ParserConfigurationError, match="supplied_standard"):
        PyMuPdfDocumentParser(store, recognizer=FakeRecognizer()).parse(request_without_standard)


@pytest.mark.parametrize("selection", ["0", "2", "bad", "1-"])
def test_invalid_page_selection_is_rejected(selection: str) -> None:
    content = make_text_pdf(["PAGE"])
    store, request = request_for(content, pages=selection)
    with pytest.raises(ParserConfigurationError, match="page|range"):
        PyMuPdfDocumentParser(store, recognizer=FakeRecognizer()).parse(request)


def test_file_store_failure_is_explicit() -> None:
    content = make_text_pdf(["PAGE"])
    _, request = request_for(content)
    with pytest.raises(DocumentParserError, match="read failure"):
        PyMuPdfDocumentParser(
            MemoryFileStore(content, fail=True), recognizer=FakeRecognizer()
        ).parse(request)


def test_ocr_failure_can_raise_or_return_tracked_partial_page() -> None:
    content = make_text_pdf(["PAGE"])
    store, strict_request = request_for(content, options={"force_ocr": True})
    with pytest.raises(PageProcessingError, match="page 1"):
        PyMuPdfDocumentParser(store, recognizer=FailingRecognizer()).parse(strict_request)

    store, continue_request = request_for(
        content,
        options={"force_ocr": True, "on_page_error": "continue"},
    )
    document = PyMuPdfDocumentParser(store, recognizer=FailingRecognizer()).parse(continue_request)
    assert document.pages[0].content_extraction_status.value == "not_processed"
    assert document.pages[0].blocks == []
    assert document.processing.warnings[0].field == "pages[1]"


def test_invalid_ocr_bbox_is_not_silently_clamped() -> None:
    content = make_text_pdf(["PAGE"])
    store, request = request_for(content, options={"force_ocr": True})
    recognizer = FakeRecognizer([OcrSpan("bad", (-1, 0, 20, 20), 0.9, 0)])
    with pytest.raises(PageProcessingError, match="bounds"):
        PyMuPdfDocumentParser(store, recognizer=recognizer).parse(request)


def test_empty_ocr_result_remains_partial_and_adds_warning() -> None:
    content = make_text_pdf(["PAGE"])
    store, request = request_for(content, options={"force_ocr": True})
    parser = PyMuPdfDocumentParser(store, recognizer=FakeRecognizer())
    document = parser.parse(request)
    assert document.pages[0].content_extraction_status.value == "partially_transcribed"
    assert document.pages[0].blocks == []
    assert document.processing.warnings[0].field == "pages[1]"
    assert parser.last_diagnostics is not None
    assert parser.last_diagnostics.pages[0].text_item_count == 0


def test_non_pdf_and_oversized_declared_input_are_rejected() -> None:
    source = FileRef(
        file_id="bad",
        uri="memory://bad",
        mime_type="application/pdf",
        size_bytes=100,
    )
    request = ParseRequest(
        source_file=source,
        supplied_standard=request_for(make_text_pdf(["PAGE"]))[1].supplied_standard,
        config=ParseConfig(
            config_id="limits",
            options={"page_selection": "1", "max_pdf_bytes": 10},
        ),
    )
    with pytest.raises(DocumentParserError, match="size exceeds"):
        PyMuPdfDocumentParser(MemoryFileStore(b"bad"), recognizer=FakeRecognizer()).parse(request)


def test_import_and_construction_do_not_read_files_or_load_ocr() -> None:
    calls = 0

    class Store:
        @contextmanager
        def read(self, reference: FileRef):
            nonlocal calls
            calls += 1
            del reference
            yield BytesIO(b"")

    parser = PyMuPdfDocumentParser(Store(), recognizer=FakeRecognizer())  # type: ignore[arg-type]
    assert parser.last_diagnostics is None
    assert calls == 0
