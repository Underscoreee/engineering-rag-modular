"""Fail-closed merge of independently parsed V2.4 batches."""

from engineering_rag.contracts.documents import ClauseGroups, Document, ProcessingMetadata


class DocumentMergeError(ValueError):
    """A batch cannot safely be combined with the source document."""


def merge_documents(documents: list[Document]) -> Document:
    if not documents:
        raise DocumentMergeError("at least one batch document is required")
    base = documents[0]
    if base.source_file.sha256 is None:
        raise DocumentMergeError("source_file.sha256 is required for batch merge")
    expected = _identity(base)
    for index, document in enumerate(documents[1:], start=2):
        actual = _identity(document)
        conflicts = [name for name, value in actual.items() if value != expected[name]]
        if conflicts:
            raise DocumentMergeError(
                f"source identity conflict in batch {index}: {', '.join(conflicts)}"
            )
    pages = sorted(
        (page for document in documents for page in document.pages),
        key=lambda item: item.page_number,
    )
    _unique("page_number", [str(page.page_number) for page in pages])
    blocks = [block for page in pages for block in page.blocks]
    _unique("block_id", [block.block_id for block in blocks])
    tables = [table for document in documents for table in document.tables]
    _unique("table_id", [table.table_id for table in tables])
    formula_groups = [block.formula_group_id for block in blocks if block.formula_group_id]
    _unique("formula_group_id", formula_groups)
    formula_ids = [
        equation.formula_id
        for block in blocks
        if block.ocr and block.ocr.formula_group
        for equation in block.ocr.formula_group.equations
    ]
    _unique("formula_id", formula_ids)
    block_by_id = {
        block.block_id: (page.page_number, block) for page in pages for block in page.blocks
    }
    claimed: dict[str, str] = {}
    for table in tables:
        fragment_ids = [fragment.block_id for fragment in table.fragments]
        if fragment_ids != list(table.source_block_ids):
            raise DocumentMergeError(f"table {table.table_id} fragment order conflict")
        for fragment in table.fragments:
            owner = claimed.setdefault(fragment.block_id, table.table_id)
            if owner != table.table_id:
                raise DocumentMergeError(f"table fragment {fragment.block_id} has two owners")
            location = block_by_id.get(fragment.block_id)
            if location is None:
                raise DocumentMergeError(f"table {table.table_id} references missing block")
            page_number, block = location
            if (
                page_number != fragment.page_number
                or block.table_id != table.table_id
                or block.fragment_index != fragment.fragment_index
            ):
                raise DocumentMergeError(f"table {table.table_id} fragment provenance conflict")
    payload = base.model_dump(mode="json")
    payload.update(
        pages=[page.model_dump(mode="json") for page in pages],
        sections=[],
        tables=[table.model_dump(mode="json") for table in tables],
        clauses=ClauseGroups().model_dump(mode="json"),
        processing=ProcessingMetadata(
            parser_id="engineering_rag.document_parser.mineru.e2e",
            parser_version="1.6.0",
            partial=True,
            is_complete_document_ocr=False,
            warnings=[
                warning for document in documents for warning in document.processing.warnings
            ],
        ).model_dump(mode="json"),
    )
    try:
        return Document.model_validate(payload)
    except ValueError as exc:
        raise DocumentMergeError(f"merged V2.4 document is invalid: {exc}") from exc


def _identity(document: Document) -> dict[str, object]:
    return {
        "schema_version": document.schema_version,
        "document_id": document.document_id,
        "file_id": document.source_file.file_id,
        "sha256": document.source_file.sha256,
        "size_bytes": document.source_file.size_bytes,
        "page_count": document.page_count,
        "standard_code": document.standard.standard_code,
        "edition": document.standard.edition,
        "revision": document.standard.revision,
        "bbox": document.bbox_coordinate_system.model_dump(mode="json"),
    }


def _unique(label: str, values: list[str]) -> None:
    if len(values) != len(set(values)):
        raise DocumentMergeError(f"duplicate or conflicting {label}")
