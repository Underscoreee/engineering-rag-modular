"""Source and context metadata derived only from public Document V2.4 objects."""

import re
from collections import defaultdict

from engineering_rag.contracts.chunks import ChunkingConfig
from engineering_rag.contracts.common import SourceRef
from engineering_rag.contracts.documents import BlockType, Clause, Document, PageType, Section


class ChunkingInputError(ValueError):
    """The public Document is valid but lacks content required by Chunk V1."""


def section_path(document: Document, section_id: str | None) -> list[str]:
    if section_id is None:
        return []
    sections = {section.section_id: section for section in document.sections}
    current = sections.get(section_id)
    if current is None:
        raise ChunkingInputError(f"unknown section_id: {section_id}")
    path: list[Section] = []
    seen: set[str] = set()
    while current is not None:
        if current.section_id in seen:
            raise ChunkingInputError(f"cyclic section hierarchy at {current.section_id}")
        seen.add(current.section_id)
        path.append(current)
        current = sections.get(current.parent_section_id) if current.parent_section_id else None
    return [_section_label(item) for item in reversed(path)]


def context_header(
    document: Document,
    path: list[str],
    *,
    clause_number: str | None,
    is_explanation: bool,
) -> str:
    standard = f"《{document.standard.standard_name}》（{document.standard.standard_code}）"
    values = [standard]
    if is_explanation:
        values.append("条文说明")
    for item in path:
        if item not in values:
            values.append(item)
    if clause_number and clause_number not in values:
        values.append(clause_number)
    return "\n".join(values)


def source_refs(document: Document, block_ids: list[str] | tuple[str, ...]) -> list[SourceRef]:
    locations = {
        block.block_id: (page.page_number, block)
        for page in document.pages
        for block in page.blocks
    }
    refs: list[SourceRef] = []
    for block_id in block_ids:
        location = locations.get(block_id)
        if location is None:
            raise ChunkingInputError(f"unknown source block: {block_id}")
        page_number, block = location
        refs.append(
            SourceRef(
                document_id=document.document_id,
                page_number=page_number,
                block_id=block_id,
                bbox=block.bbox,
            )
        )
    return refs


def clause_sort_key(document: Document, clause: Clause) -> tuple[int, int, str]:
    positions = {
        block.block_id: (page.page_number, block.reading_order)
        for page in document.pages
        for block in page.blocks
    }
    first = positions.get(clause.source_block_ids[0], (clause.page_start, 0))
    return first[0], first[1], clause.clause_id


def decorative_orphan_block_ids(document: Document) -> set[str]:
    """Identify unambiguous numeric footers and repeated margin text."""
    by_signature: dict[tuple[str, str], list[tuple[int, str]]] = defaultdict(list)
    decorated: set[str] = set()
    for page in document.pages:
        if page.page_type not in {PageType.BODY, PageType.EXPLANATION_BODY}:
            continue
        for block in page.blocks:
            if block.block_type != BlockType.BODY or block.ocr is None or not block.ocr.text:
                continue
            text = _normalize_margin_text(block.ocr.text)
            if not text:
                continue
            zone = (
                "header"
                if block.bbox.y_max <= page.height * 0.12
                else "footer"
                if block.bbox.y_min >= page.height * 0.82
                else "body"
            )
            if zone == "footer" and text.isdigit():
                decorated.add(block.block_id)
            if zone != "body":
                by_signature[(zone, text)].append((page.page_number, block.block_id))
    for occurrences in by_signature.values():
        if len({page for page, _ in occurrences}) >= 2:
            decorated.update(block_id for _, block_id in occurrences)
    return decorated


def validate_config(config: ChunkingConfig) -> None:
    if config.options:
        raise ValueError("Clause-first Chunk V1 does not define config.options")


def _section_label(section: Section) -> str:
    return f"{section.number} {section.title}" if section.number else section.title


def _normalize_margin_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()
