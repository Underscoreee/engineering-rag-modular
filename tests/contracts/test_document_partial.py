import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.documents import Document

EXAMPLES = Path(__file__).parents[2] / "examples"
REFERENCE = Path(__file__).parents[2] / "references" / "GB50010_2015_document.v2.4.partial.json"


@pytest.mark.parametrize("name", ["document.example.json", "document.partial.example.json"])
def test_document_examples_round_trip(name: str) -> None:
    document = Document.model_validate_json((EXAMPLES / name).read_text(encoding="utf-8"))
    assert Document.model_validate_json(document.model_dump_json()) == document


def test_partial_states_are_explicit() -> None:
    document = Document.model_validate_json(
        (EXAMPLES / "document.partial.example.json").read_text(encoding="utf-8")
    )
    assert document.processing.partial and not document.processing.is_complete_document_ocr
    assert document.pages[0].content_extraction_status.value == "not_processed"
    assert document.pages[0].blocks == []
    assert document.pages[1].content_extraction_status.value == "partially_transcribed"
    assert document.pages[1].blocks[0].fragment_status.value == "not_transcribed"
    assert document.pages[1].blocks[1].ocr.formula_group.equations[0].latex is None
    assert (
        document.pages[1].blocks[1].ocr.formula_group.equations[0].equation_number_status.value
        == "unknown"
    )
    assert document.pages[1].blocks[1].bbox_status.value == "manual_approximate"


def test_complete_ocr_allows_recognized_but_unverified_block() -> None:
    data = json.loads((EXAMPLES / "document.example.json").read_text())
    data["pages"][0]["blocks"][0]["recognition_status"] = "unverified"
    content = data["clauses"]["normative"][0]["clause_content"]
    content["plain_text"] = None
    content.pop("plain_text_renderer_version")
    content.pop("plain_text_source_digest")
    document = Document.model_validate(data)
    assert document.processing.is_complete_document_ocr is True
    assert document.pages[0].blocks[0].recognition_status.value == "unverified"


def test_partial_document_can_omit_unprocessed_page_listing() -> None:
    data = json.loads((EXAMPLES / "document.partial.example.json").read_text())
    data["pages"] = data["pages"][:2]
    assert Document.model_validate(data).page_count == 3


def test_partial_semantic_extraction_can_follow_complete_ocr() -> None:
    data = json.loads((EXAMPLES / "document.example.json").read_text())
    data["processing"]["partial"] = True
    assert Document.model_validate(data).processing.is_complete_document_ocr is True


def test_unaggregated_fragment_requires_explicit_pending_state() -> None:
    data = json.loads((EXAMPLES / "document.partial.example.json").read_text())
    invalid = deepcopy(data)
    invalid["pages"][1]["blocks"][0]["fragment_status"] = "verified"
    invalid["pages"][1]["blocks"][0]["table_id"] = "missing-table"
    with pytest.raises(ValidationError, match="unknown table_id"):
        Document.model_validate(invalid)
    data["processing"]["partial"] = False
    data["processing"]["is_complete_document_ocr"] = True
    with pytest.raises(ValidationError):
        Document.model_validate(data)


def test_not_processed_page_cannot_declare_blocks() -> None:
    data = json.loads((EXAMPLES / "document.partial.example.json").read_text())
    data["pages"][0]["blocks"] = [data["pages"][1]["blocks"][0]]
    with pytest.raises(ValidationError, match="not_processed page"):
        Document.model_validate(data)


def test_real_proposal_is_read_only_and_not_silent_v24() -> None:
    data = json.loads(REFERENCE.read_text(encoding="utf-8"))
    assert data["page_count"] == len(data["pages"]) == 441
    assert (
        sum(page["content_extraction_status"] == "not_processed" for page in data["pages"]) == 422
    )
    assert data["schema_version"] == "2.4-proposal"
    with pytest.raises(ValidationError):
        Document.model_validate(data)
