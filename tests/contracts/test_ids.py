from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.artifacts import ArtifactManifest, DocumentArtifact
from engineering_rag.contracts.documents import Document

EXAMPLES = Path(__file__).parents[2] / "examples"


def test_snapshot_scoped_ids_and_json_round_trip(document_data: dict[str, object]) -> None:
    document = Document.model_validate(document_data)
    assert (
        document.clauses.normative[0].clause_number
        == document.clauses.explanations[0].clause_number
    )
    assert document.clauses.normative[0].clause_id != document.clauses.explanations[0].clause_id
    assert (
        Document.model_validate_json(document.model_dump_json()).document_id == document.document_id
    )


@pytest.mark.parametrize("kind", ["section", "formula", "evidence"])
def test_snapshot_entity_ids_are_unique(document_data: dict[str, object], kind: str) -> None:
    data = deepcopy(document_data)
    if kind == "section":
        data["sections"][1]["section_id"] = data["sections"][0]["section_id"]
    elif kind == "formula":
        data["pages"][3]["blocks"][1]["ocr"]["formula_group"]["equations"][0]["formula_id"] = (
            "f-norm-421-1"
        )
    else:
        duplicate = deepcopy(data["clauses"]["normative"][0]["mandatory_evidence"][0])
        data["clauses"]["normative"][1]["mandatory_evidence"] = [duplicate]
    with pytest.raises(ValidationError):
        Document.model_validate(data)


def test_artifact_identity_is_distinct_from_document_identity() -> None:
    document = Document.model_validate_json(
        (EXAMPLES / "document.partial.example.json").read_text(encoding="utf-8")
    )
    manifest = ArtifactManifest.model_validate_json(
        (EXAMPLES / "artifact_manifest.example.json").read_text(encoding="utf-8")
    )
    bundle = DocumentArtifact(manifest=manifest, document=document)
    assert bundle.manifest.artifact_id != bundle.document.document_id


def test_ocr_change_does_not_define_document_or_clause_identity(
    document_data: dict[str, object],
) -> None:
    original = Document.model_validate(document_data)
    data = deepcopy(document_data)
    data["clauses"]["normative"][0]["clause_content"]["plain_text"] = None
    data["clauses"]["normative"][0]["clause_content"].pop("plain_text_renderer_version")
    data["clauses"]["normative"][0]["clause_content"].pop("plain_text_source_digest")
    data["pages"][0]["blocks"][0]["ocr"]["text"] = "修订后的虚构 OCR 文本"
    changed = Document.model_validate(data)
    assert changed.document_id == original.document_id
    assert changed.clauses.normative[0].clause_id == original.clauses.normative[0].clause_id
