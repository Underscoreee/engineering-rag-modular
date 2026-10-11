from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from engineering_rag.contracts.artifacts import (
    ArtifactIntegrityError,
    ArtifactManifest,
    DocumentArtifact,
    require_supported_document_schema,
)
from engineering_rag.contracts.documents import Document

EXAMPLES = Path(__file__).parents[2] / "examples"


def _manifest_data() -> dict[str, object]:
    return ArtifactManifest.model_validate_json(
        (EXAMPLES / "artifact_manifest.example.json").read_text(encoding="utf-8")
    ).model_dump(mode="json")


def test_manifest_and_partial_bundle_round_trip() -> None:
    manifest = ArtifactManifest.model_validate(_manifest_data())
    document = Document.model_validate_json(
        (EXAMPLES / "document.partial.example.json").read_text(encoding="utf-8")
    )
    artifact = DocumentArtifact(manifest=manifest, document=document)
    assert DocumentArtifact.model_validate_json(artifact.model_dump_json()) == artifact
    assert manifest.schema_version == "2.4"
    assert manifest.artifact_version == "1"
    assert manifest.parser_version == "synthetic-parser-0.2"


@pytest.mark.parametrize("mutation", ["hash", "timezone", "version", "media_type"])
def test_manifest_static_validation_rejects_invalid_data(mutation: str) -> None:
    data = deepcopy(_manifest_data())
    if mutation == "hash":
        data["document_json_ref"]["sha256"] = "bad"
    elif mutation == "timezone":
        data["created_at"] = "2026-01-01T00:00:00"
    elif mutation == "version":
        data["document_json_ref"]["artifact_version"] = "2"
    else:
        data["document_json_ref"]["media_type"] = "text/plain"
    with pytest.raises(ValidationError):
        ArtifactManifest.model_validate(data)


def test_artifact_bundle_prevents_snapshot_source_merge() -> None:
    document = Document.model_validate_json(
        (EXAMPLES / "document.partial.example.json").read_text(encoding="utf-8")
    )
    data = _manifest_data()
    data["source_document_id"] = "another-document"
    manifest = ArtifactManifest.model_validate(data)
    with pytest.raises(ValidationError, match="identities do not match"):
        DocumentArtifact(manifest=manifest, document=document)


def test_migration_target_requires_explicit_supported_version() -> None:
    require_supported_document_schema("2.4")
    with pytest.raises(ValueError, match="unsupported"):
        require_supported_document_schema("2.4-proposal")


def test_future_io_errors_are_distinct_from_static_validation() -> None:
    error = ArtifactIntegrityError(
        code="checksum_mismatch",
        message="fixture checksum mismatch",
        artifact_id="artifact",
        artifact_version="1",
        uri="artifact://fixture/document.json",
    )
    assert error.code.value == "checksum_mismatch"


def test_document_asset_must_match_manifest_snapshot() -> None:
    manifest = ArtifactManifest.model_validate(_manifest_data())
    document = Document.model_validate_json(
        (EXAMPLES / "document.partial.example.json").read_text(encoding="utf-8")
    )
    document.pages[1].blocks[1].asset = manifest.assets[0].model_copy(deep=True)
    DocumentArtifact(manifest=manifest, document=document)
    document.pages[1].blocks[1].asset.uri = "artifact://another/snapshot.png"
    with pytest.raises(ValidationError, match="conflicts with artifact manifest"):
        DocumentArtifact(manifest=manifest, document=document)
