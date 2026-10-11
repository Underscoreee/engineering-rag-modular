"""Regressions supplied by the independent Task 1.1 audit."""

import hashlib
from io import BytesIO

import pymupdf
import pytest

from engineering_rag.contracts.documents import ParseRequest
from engineering_rag.modules.document_parser.internal.parser import PyMuPdfDocumentParser
from engineering_rag.modules.document_parser.internal.pdf_backend import PyMuPdfBackend
from engineering_rag.modules.document_parser.tests.support import (
    FakeRecognizer,
    make_text_pdf,
    request_for,
)


@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_text_layer_bbox_agrees_with_rotated_visible_page(rotation: int) -> None:
    source = make_text_pdf(["SHORT TEXT"], rotate=rotation)
    with pymupdf.open(stream=source, filetype="pdf") as document:
        page = document[0]
        raw = page.get_text("blocks")[0]
        expected = pymupdf.Rect(raw[:4]) * page.rotation_matrix
        expected_tuple = tuple(expected)
    with PyMuPdfBackend().open(BytesIO(source), max_bytes=200_000) as pdf:
        actual = pdf.extract_text_spans(1)[0].bbox
    assert (actual.x_min, actual.y_min, actual.x_max, actual.y_max) == pytest.approx(
        expected_tuple, abs=1e-3
    )


def test_rotated_and_cropped_text_layer_returns_valid_document() -> None:
    source = make_text_pdf(["VALID TEXT ROTATED"], rotate=90, crop=True)
    store, request = request_for(source, options={"min_text_layer_chars": 1})
    document = PyMuPdfDocumentParser(
        store,
        recognizer=FakeRecognizer(error=AssertionError("OCR must not be used")),
    ).parse(request)
    assert document.pages[0].blocks
    assert document.pages[0].blocks[0].bbox.x_max <= document.pages[0].width


def test_file_sha256_mismatch_is_rejected() -> None:
    source = make_text_pdf(["SHORT TEXT"])
    store, request = request_for(source, options={"min_text_layer_chars": 1})
    reference = request.source_file.model_copy(update={"sha256": "0" * 64})
    wrong = ParseRequest(
        source_file=reference,
        supplied_standard=request.supplied_standard,
        config=request.config,
    )
    with pytest.raises(Exception, match="(?i)sha256|checksum|digest|integrity"):
        PyMuPdfDocumentParser(store, recognizer=FakeRecognizer()).parse(wrong)


def test_declared_file_size_mismatch_is_rejected() -> None:
    source = make_text_pdf(["SHORT TEXT"])
    store, request = request_for(source, options={"min_text_layer_chars": 1})
    reference = request.source_file.model_copy(update={"size_bytes": len(source) + 1000})
    wrong = ParseRequest(
        source_file=reference,
        supplied_standard=request.supplied_standard,
        config=request.config,
    )
    with pytest.raises(Exception, match="(?i)size|bytes|integrity"):
        PyMuPdfDocumentParser(store, recognizer=FakeRecognizer()).parse(wrong)


def test_matching_declared_file_integrity_is_accepted() -> None:
    source = make_text_pdf(["SHORT TEXT"])
    store, request = request_for(source, options={"min_text_layer_chars": 1})
    reference = request.source_file.model_copy(
        update={
            "size_bytes": len(source),
            "sha256": hashlib.sha256(source).hexdigest(),
        }
    )
    valid = ParseRequest(
        source_file=reference,
        supplied_standard=request.supplied_standard,
        config=request.config,
    )
    assert PyMuPdfDocumentParser(store, recognizer=FakeRecognizer()).parse(valid).page_count == 1


def test_undeclared_file_integrity_fields_remain_optional() -> None:
    source = make_text_pdf(["SHORT TEXT"])
    store, request = request_for(source, options={"min_text_layer_chars": 1})
    reference = request.source_file.model_copy(update={"size_bytes": None, "sha256": None})
    valid = ParseRequest(
        source_file=reference,
        supplied_standard=request.supplied_standard,
        config=request.config,
    )
    assert PyMuPdfDocumentParser(store, recognizer=FakeRecognizer()).parse(valid).page_count == 1
