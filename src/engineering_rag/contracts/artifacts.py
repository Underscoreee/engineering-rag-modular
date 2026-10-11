"""Versioned, immutable Document artifact snapshot contracts."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, model_validator

from .common import ArtifactRef, ContractModel, NonEmptyStr
from .documents import DOCUMENT_SCHEMA_VERSION, Document


class ArtifactProcessingStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


class ArtifactIntegrityErrorCode(StrEnum):
    RESOURCE_NOT_FOUND = "resource_not_found"
    CHECKSUM_MISMATCH = "checksum_mismatch"
    UNSUPPORTED_SCHEMA_VERSION = "unsupported_schema_version"
    SNAPSHOT_CONFLICT = "snapshot_conflict"


class ArtifactIntegrityError(ContractModel):
    """Structured future I/O failure; distinct from static Pydantic validation."""

    code: ArtifactIntegrityErrorCode
    message: NonEmptyStr
    artifact_id: NonEmptyStr
    artifact_version: NonEmptyStr
    uri: NonEmptyStr | None = None
    retryable: bool = False


class ArtifactManifest(ContractModel):
    """Static index for one immutable ``document.json`` plus asset snapshot."""

    artifact_id: NonEmptyStr
    artifact_version: NonEmptyStr
    schema_version: Literal["2.4"]
    created_at: datetime
    source_document_id: NonEmptyStr
    processing_status: ArtifactProcessingStatus
    document_json_ref: ArtifactRef
    assets: list[ArtifactRef] = Field(default_factory=list)
    parser_version: NonEmptyStr | None = None

    @model_validator(mode="after")
    def validate_static_snapshot(self) -> "ArtifactManifest":
        if self.created_at.tzinfo is None or self.created_at.utcoffset() != UTC.utcoffset(None):
            raise ValueError("created_at must be timezone-aware UTC")
        document_ref = self.document_json_ref
        if document_ref.artifact_id != self.artifact_id:
            raise ValueError("document_json_ref must identify this artifact snapshot")
        if document_ref.artifact_version != self.artifact_version:
            raise ValueError("document_json_ref artifact_version must match manifest")
        if document_ref.schema_version != self.schema_version:
            raise ValueError("document_json_ref schema_version must match manifest")
        if document_ref.artifact_type != "document_json":
            raise ValueError("document_json_ref artifact_type must be document_json")
        if document_ref.media_type != "application/json":
            raise ValueError("document_json_ref media_type must be application/json")
        for reference in [document_ref, *self.assets]:
            if reference.sha256 is None or reference.size_bytes is None:
                raise ValueError("manifest references require sha256 and size_bytes")
            if not urlparse(reference.uri).scheme:
                raise ValueError("manifest reference URI requires a scheme")
        asset_ids = [reference.artifact_id for reference in self.assets]
        asset_uris = [reference.uri for reference in self.assets]
        if len(set(asset_ids)) != len(asset_ids):
            raise ValueError("manifest asset_id values must be unique")
        if len(set(asset_uris)) != len(asset_uris):
            raise ValueError("manifest asset URI values must be unique")
        return self


class DocumentArtifact(ContractModel):
    """In-memory contract bundle used for validation and explicit migration boundaries."""

    manifest: ArtifactManifest
    document: Document | None

    @model_validator(mode="after")
    def validate_bundle(self) -> "DocumentArtifact":
        if self.manifest.processing_status == ArtifactProcessingStatus.FAILED:
            if self.document is not None:
                raise ValueError("failed artifact must not claim a valid Document")
            return self
        if self.document is None:
            raise ValueError("completed or partial artifact requires a Document")
        if self.document.document_id != self.manifest.source_document_id:
            raise ValueError("manifest and Document identities do not match")
        if self.document.schema_version != self.manifest.schema_version:
            raise ValueError("manifest and Document schema versions do not match")
        expected_status = (
            ArtifactProcessingStatus.PARTIAL
            if self.document.processing.partial
            else ArtifactProcessingStatus.COMPLETED
        )
        if self.manifest.processing_status != expected_status:
            raise ValueError("manifest processing_status conflicts with Document.processing")
        manifest_assets = {asset.artifact_id: asset for asset in self.manifest.assets}
        document_assets = [
            block.asset
            for page in self.document.pages
            for block in page.blocks
            if block.asset is not None
        ]
        for asset in document_assets:
            manifest_asset = manifest_assets.get(asset.artifact_id)
            if manifest_asset is None:
                raise ValueError("Document asset is missing from artifact manifest")
            identity = (
                "artifact_type",
                "uri",
                "media_type",
                "artifact_version",
            )
            if any(getattr(asset, field) != getattr(manifest_asset, field) for field in identity):
                raise ValueError("Document asset conflicts with artifact manifest")
        return self


def require_supported_document_schema(target_schema_version: str) -> None:
    """Reject guessed migration targets; this function does not transform any data."""

    if target_schema_version != DOCUMENT_SCHEMA_VERSION:
        raise ValueError(f"unsupported Document schema version: {target_schema_version}")
