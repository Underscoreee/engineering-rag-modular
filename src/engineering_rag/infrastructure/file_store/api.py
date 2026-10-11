"""File-store interface; bytes are streamed and URI/path identities stay distinct."""

from engineering_rag.contracts.artifacts import ArtifactManifest, DocumentArtifact
from engineering_rag.contracts.common import ArtifactRef, FileRef
from engineering_rag.contracts.protocols import DocumentMigrationService, FileStore

__all__ = [
    "ArtifactManifest",
    "ArtifactRef",
    "DocumentArtifact",
    "DocumentMigrationService",
    "FileRef",
    "FileStore",
]
