from inspect import signature
from pathlib import Path
from typing import get_type_hints

from engineering_rag.contracts.artifacts import ArtifactManifest, DocumentArtifact
from engineering_rag.contracts.protocols import DocumentMigrationService, FileStore
from engineering_rag.infrastructure.file_store.api import (
    DocumentMigrationService as PublicMigrationService,
)
from engineering_rag.infrastructure.file_store.api import FileStore as PublicFileStore

ROOT = Path(__file__).parents[2]


def test_file_store_versioned_artifact_protocol_is_canonical() -> None:
    assert PublicFileStore is FileStore
    assert get_type_hints(FileStore.commit_artifact) == {
        "artifact": DocumentArtifact,
        "return": ArtifactManifest,
    }
    assert list(signature(FileStore.get_artifact).parameters) == [
        "self",
        "artifact_id",
        "artifact_version",
    ]


def test_migration_protocol_is_declaration_only() -> None:
    assert PublicMigrationService is DocumentMigrationService
    assert getattr(DocumentMigrationService, "_is_protocol", False)
    assert get_type_hints(DocumentMigrationService.migrate_document) == {
        "source": DocumentArtifact,
        "target_schema_version": str,
        "return": DocumentArtifact,
    }


def test_file_store_interface_declares_no_backend_implementation() -> None:
    interface = (ROOT / "src/engineering_rag/infrastructure/file_store/INTERFACE.md").read_text(
        encoding="utf-8"
    )
    assert "commit_artifact" in interface
    assert "不得覆盖" in interface
    assert "没有真实存储后端" in interface
