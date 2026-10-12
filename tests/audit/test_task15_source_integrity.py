"""Additional merge and split evidence gates for the Task 1.5 repair."""

from collections.abc import Callable

import pytest
from scripts.assemble_mineru_clauses import _merge_documents

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import Document, StandardMetadata
from engineering_rag.modules.document_parser.tests.test_semantic_structure import (
    _body,
    _document,
    _page,
)


def _batches() -> tuple[Document, Document]:
    return (
        _document([_page(16, _body("p16", "1.0.1 条文", 0))]),
        _document([_page(17, _body("p17", "1.0.2 条文", 0))]),
    )


@pytest.mark.parametrize(
    "mutate, expected_field",
    [
        (lambda doc: setattr(doc, "document_id", "different-document"), "document_id"),
        (
            lambda doc: setattr(
                doc,
                "source_file",
                doc.source_file.model_copy(update={"file_id": "different-file"}),
            ),
            "file_id",
        ),
        (lambda doc: setattr(doc, "page_count", 499), "page_count"),
        (
            lambda doc: setattr(
                doc,
                "standard",
                StandardMetadata(
                    standard_name="虚构结构设计标准",
                    standard_code="DEMO 2-2026",
                    edition="演示版",
                ),
            ),
            "standard_code",
        ),
        (
            lambda doc: setattr(
                doc,
                "standard",
                StandardMetadata(
                    standard_name="虚构结构设计标准",
                    standard_code="DEMO 1-2026",
                    edition="另一版",
                ),
            ),
            "edition",
        ),
    ],
)
def test_merge_rejects_each_conflicting_batch_identity_field(
    mutate: Callable[[Document], None], expected_field: str
) -> None:
    one, two = _batches()
    mutate(two)
    with pytest.raises(SystemExit, match=expected_field):
        _merge_documents([one, two])


def test_merge_rejects_unverifiable_sha256() -> None:
    one, two = _batches()
    one.source_file = FileRef(
        file_id=one.source_file.file_id,
        uri=one.source_file.uri,
        mime_type=one.source_file.mime_type,
        sha256=None,
    )
    two.source_file = one.source_file
    with pytest.raises(SystemExit, match="sha256|required|manifest"):
        _merge_documents([one, two])


def test_merge_rejects_duplicate_block_identity_across_batches() -> None:
    one, two = _batches()
    two.pages[0].blocks[0] = (
        two.pages[0].blocks[0].model_copy(update={"block_id": one.pages[0].blocks[0].block_id})
    )
    with pytest.raises(SystemExit, match="duplicate block"):
        _merge_documents([one, two])
