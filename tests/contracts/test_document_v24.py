from copy import deepcopy

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.common import ArtifactRef, BoundingBox, FileRef
from engineering_rag.contracts.documents import (
    BlockType,
    Document,
    Page,
    PageType,
    StandardMetadata,
)


def test_shared_refs_and_version_identity() -> None:
    assert FileRef(file_id="f", uri="artifact://f", mime_type="application/pdf").file_id == "f"
    assert (
        ArtifactRef(
            artifact_id="a",
            artifact_type="image",
            uri="artifact://a",
            media_type="image/png",
            artifact_version="1",
        ).schema_version
        == "1.0"
    )
    assert StandardMetadata(standard_name="虚构", standard_code="D", edition="A").edition != (
        StandardMetadata(standard_name="虚构", standard_code="D", edition="B").edition
    )
    with pytest.raises(ValidationError):
        FileRef(file_id="", uri="artifact://f", mime_type="application/pdf")


def test_exact_page_types_and_unknown(document_data: dict[str, object]) -> None:
    assert {item.value for item in PageType} == {
        "outer_cover",
        "inner_cover",
        "publication_notice",
        "preface",
        "toc_zh",
        "toc_en",
        "body",
        "wording_rules",
        "normative_references",
        "explanation_cover",
        "revision_notes",
        "explanation_toc",
        "explanation_body",
        "unknown",
    }
    data = deepcopy(document_data)
    data["pages"][0]["page_type"] = "unknown"
    Page.model_validate(data["pages"][0])
    data["pages"][0]["page_type"] = "invented"
    with pytest.raises(ValidationError):
        Page.model_validate(data["pages"][0])


def test_block_types_are_exactly_five() -> None:
    assert {item.value for item in BlockType} == {
        "title",
        "body",
        "table",
        "image",
        "formula",
    }


@pytest.mark.parametrize(
    ("path", "name"),
    [
        (("pages", 0), "printed_page_label"),
        (("pages", 0), "primary_page_type"),
        (("pages", 0), "region_type"),
        (("pages", 0, "blocks", 0), "clause_id"),
        (("pages", 0, "blocks", 0), "section_id"),
        (("pages", 0, "blocks", 0), "region_type"),
        (("pages", 0, "blocks", 0, "bbox"), "coordinate_system"),
        (("pages", 0, "blocks", 0, "bbox"), "origin"),
        (("standard",), "is_synthetic_example"),
    ],
)
def test_removed_fields_rejected(document_data: dict[str, object], path: tuple, name: str) -> None:
    data = deepcopy(document_data)
    value = data
    for part in path:
        value = value[part]
    value[name] = "forbidden"
    with pytest.raises(ValidationError):
        Document.model_validate(data)


def test_bbox_page_limits_and_schema_version(document_data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BoundingBox(x_min=10, y_min=0, x_max=5, y_max=1)
    with pytest.raises(ValidationError):
        BoundingBox(x_min=0, y_min=0, x_max=float("nan"), y_max=1)
    data = deepcopy(document_data)
    data["pages"][0]["blocks"][0]["bbox"]["x_max"] = 601
    with pytest.raises(ValidationError, match="bbox exceeds"):
        Document.model_validate(data)
    data = deepcopy(document_data)
    data["schema_version"] = "2.4-proposal"
    with pytest.raises(ValidationError):
        Document.model_validate(data)
    data["schema_version"] = "2.3"
    with pytest.raises(ValidationError):
        Document.model_validate(data)


@pytest.mark.parametrize("change", ["duplicate_page", "page_out_of_range", "duplicate_block"])
def test_page_and_block_identity_rejected(document_data: dict[str, object], change: str) -> None:
    data = deepcopy(document_data)
    if change == "duplicate_page":
        data["pages"][1]["page_number"] = 1
    elif change == "page_out_of_range":
        data["pages"][3]["page_number"] = 5
    else:
        data["pages"][1]["blocks"][0]["block_id"] = "body-1"
    with pytest.raises(ValidationError):
        Document.model_validate(data)
