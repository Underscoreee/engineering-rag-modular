"""File-store interface; bytes are streamed and URI/path identities stay distinct."""

from engineering_rag.contracts.common import ArtifactRef, FileRef
from engineering_rag.contracts.protocols import FileStore

__all__ = ["ArtifactRef", "FileRef", "FileStore"]
