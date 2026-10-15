"""Assemble safe HTML fragments into frozen V2.4 logical tables."""

from __future__ import annotations

import re
from uuid import NAMESPACE_URL, uuid5

from engineering_rag.contracts.documents import (
    LogicalTable,
    LogicalTableStatus,
    RawGridExtractionStatus,
    RawTableCell,
    RawTableGrid,
    RecognitionStatus,
    TableFragment,
)
from engineering_rag.modules.document_parser.internal.mineru.models import (
    MinerUElement,
    MinerUParseResult,
)

from .continuation_matcher import decide_continuation
from .header_normalizer import (
    build_columns,
    build_data_rows,
    build_header_paths,
    infer_header_row_count,
)
from .models import (
    ContinuationDecision,
    TableAssemblyResult,
    TableFragmentCandidate,
    TableNoteEvidence,
    TablePlacement,
    TableSidecar,
)
from .notes import parse_table_notes
from .raw_html_parser import TableHtmlError, parse_html_table

TABLE_ASSEMBLER_VERSION = "1.3.1"
_CAPTION = re.compile(
    r"^\s*(?P<prefix>续表|表)\s*(?P<number>\d+(?:\.\d+)*(?:-\d+)?)\s*(?P<title>.*?)\s*$"
)
_ADJACENT_NOTE = re.compile(r"^\s*(?:注\s*[:：]?\s*)?(?P<number>\d+)\s*(?P<text>.+?)\s*$")
_CLAUSE_BOUNDARY = re.compile(r"^\s*\d+\s*\.\s*\d+\s*\.\s*\d+(?![-.\d])")


def assemble_mineru_tables(result: MinerUParseResult) -> TableAssemblyResult:
    candidates: list[TableFragmentCandidate] = []
    note_evidence_by_candidate: dict[tuple[int, int], list[TableNoteEvidence]] = {}
    consumed_body: set[tuple[int, int]] = set()
    omitted: list[dict[str, object]] = []
    for page in result.pages:
        for position, element in enumerate(page.elements):
            if element.raw_type != "table":
                continue
            if element.bbox is None:
                omitted.append(_omission(element.page_number, element.source_index, "missing_bbox"))
                continue
            if not element.table_html:
                omitted.append(_omission(element.page_number, element.source_index, "missing_html"))
                continue
            try:
                grid = parse_html_table(element.table_html)
            except TableHtmlError as exc:
                omitted.append(
                    _omission(
                        element.page_number,
                        element.source_index,
                        "unsafe_or_unrepresentable_html",
                        detail=str(exc),
                    )
                )
                continue
            number, title, continuation = parse_caption(element.table_caption)
            header_rows, header_basis = infer_header_row_count(
                grid, mineru_caption=element.table_caption
            )
            header_paths = build_header_paths(grid, header_rows)
            diagnostics = [*grid.diagnostics, f"header_basis:{header_basis}"]
            if not header_paths:
                diagnostics.append("columns unavailable because header paths are incomplete")
            candidate = TableFragmentCandidate(
                page_number=element.page_number,
                source_index=element.source_index,
                block_id=stable_block_id(
                    result.source_sha256,
                    element.page_number,
                    element.source_index,
                ),
                caption=element.table_caption,
                table_number=number,
                title=title,
                is_continuation=continuation,
                raw_html=element.table_html,
                raw_footnotes=list(element.table_footnotes),
                grid=grid,
                header_row_count=header_rows,
                header_paths=header_paths,
                diagnostics=diagnostics,
            )
            candidates.append(candidate)
            adjacent = _collect_adjacent_notes(
                result.source_sha256,
                page.elements,
                position,
                candidate.raw_footnotes,
            )
            if adjacent:
                candidate.raw_footnotes.extend(item.raw_text for item in adjacent)
                note_evidence_by_candidate[(page.page_number, element.source_index)] = adjacent
                consumed_body.update(
                    (item.source_page_number, item.source_index) for item in adjacent
                )
    groups, decisions = _group_fragments(candidates)
    tables: list[LogicalTable] = []
    placements: dict[tuple[int, int], TablePlacement] = {}
    sidecars: list[TableSidecar] = []
    for group_index, fragments in enumerate(groups):
        table_id = _table_id(result.source_sha256, fragments, group_index)
        table, sidecar = _build_logical_table(
            table_id,
            fragments,
            decisions.get(id(fragments), []),
        )
        sidecar.note_evidence = [
            evidence.model_copy(update={"consumed_by_table_id": table_id})
            for fragment in fragments
            for evidence in note_evidence_by_candidate.get(
                (fragment.page_number, fragment.source_index), []
            )
        ]
        tables.append(table)
        sidecars.append(sidecar)
        for index, fragment in enumerate(fragments):
            placements[(fragment.page_number, fragment.source_index)] = TablePlacement(
                table_id=table_id,
                fragment_index=index,
                label=fragment.caption,
            )
    return TableAssemblyResult(
        tables=tables,
        placements=placements,
        sidecars=sidecars,
        consumed_body=consumed_body,
        omitted=omitted,
    )


def _collect_adjacent_notes(
    source_sha256: str,
    elements: list[MinerUElement],
    table_position: int,
    embedded_notes: list[str],
) -> list[TableNoteEvidence]:
    """Consume only a consecutive numbered-note run immediately after a table."""

    existing_numbers = [
        int(match.group("number"))
        for value in embedded_notes
        if (match := _ADJACENT_NOTE.match(value)) is not None
    ]
    expected = max(existing_numbers, default=0) + 1
    evidence: list[TableNoteEvidence] = []
    for element in elements[table_position + 1 :]:
        raw_type = element.raw_type
        text = element.text
        bbox = element.bbox
        if raw_type == "page_number":
            break
        if raw_type != "text" or not text or bbox is None:
            break
        if _CLAUSE_BOUNDARY.match(text):
            break
        match = _ADJACENT_NOTE.match(text)
        if match is None or int(match.group("number")) != expected:
            break
        page_number = element.page_number
        source_index = element.source_index
        evidence.append(
            TableNoteEvidence(
                source_page_number=page_number,
                source_index=source_index,
                source_block_id=_stable_id(
                    "block", source_sha256, str(page_number), str(source_index), "text"
                ),
                source_bbox=bbox,
                raw_text=text,
                note_number=expected,
                consumed_by_table_id="pending",
            )
        )
        expected += 1
    return evidence


def parse_caption(caption: str | None) -> tuple[str | None, str | None, bool]:
    if not caption:
        return None, None, False
    match = _CAPTION.match(caption)
    if match is None:
        return None, caption.strip() or None, False
    title = match.group("title").strip() or None
    return match.group("number"), title, match.group("prefix") == "续表"


def stable_block_id(source_sha256: str, page_number: int, source_index: int) -> str:
    return _stable_id("block", source_sha256, str(page_number), str(source_index), "table")


def _group_fragments(
    candidates: list[TableFragmentCandidate],
) -> tuple[list[list[TableFragmentCandidate]], dict[int, list[ContinuationDecision]]]:
    groups: list[list[TableFragmentCandidate]] = []
    decisions: dict[int, list[ContinuationDecision]] = {}
    for candidate in sorted(candidates, key=lambda item: (item.page_number, item.source_index)):
        merged = False
        attempted: list[ContinuationDecision] = []
        for group in reversed(groups):
            decision = decide_continuation(group[-1], candidate)
            attempted.append(decision)
            if decision.should_merge:
                group.append(candidate)
                decisions.setdefault(id(group), []).append(decision)
                merged = True
                break
            if group[-1].page_number < candidate.page_number - 1:
                break
        if not merged:
            group = [candidate]
            groups.append(group)
            decisions[id(group)] = attempted
    return groups, decisions


def _build_logical_table(
    table_id: str,
    fragments: list[TableFragmentCandidate],
    decisions: list[ContinuationDecision],
) -> tuple[LogicalTable, TableSidecar]:
    first = fragments[0]
    columns = build_columns(first.grid, first.header_paths)
    data = []
    if columns:
        for fragment in fragments:
            data.extend(
                build_data_rows(
                    fragment.grid,
                    columns,
                    header_rows=fragment.header_row_count,
                    page_number=fragment.page_number,
                    block_id=fragment.block_id,
                )
            )
    all_notes = [note for fragment in fragments for note in fragment.raw_footnotes]
    notes, unnumbered, note_diagnostics = parse_table_notes(all_notes)
    raw_grid = _global_grid(fragments)
    diagnostics = [
        "machine-derived table remains unverified",
        "vertical rowspan continuation values are null in normalized data",
        *[item for fragment in fragments for item in fragment.diagnostics],
        *note_diagnostics,
    ]
    if len(fragments) > 1:
        diagnostics.append("continuation fragments merged by explicit evidence")
    extraction_status = (
        LogicalTableStatus.UNVERIFIED if columns and data else LogicalTableStatus.STRUCTURE_ONLY
    )
    source_ids = [fragment.block_id for fragment in fragments]
    table = LogicalTable(
        table_id=table_id,
        table_number=first.table_number,
        title=first.title,
        page_start=first.page_number,
        page_end=fragments[-1].page_number,
        source_block_ids=source_ids,
        fragments=[
            TableFragment(
                page_number=fragment.page_number,
                block_id=fragment.block_id,
                fragment_index=index,
                label=fragment.caption,
            )
            for index, fragment in enumerate(fragments)
        ],
        columns=columns,
        data=data or None,
        notes=notes,
        raw_grid=raw_grid,
        extraction_status=extraction_status,
        normalization_warning="; ".join(dict.fromkeys(diagnostics)),
    )
    sidecar = TableSidecar(
        table_id=table_id,
        table_number=first.table_number,
        fragments=fragments,
        continuation_decisions=decisions,
        unnumbered_notes=unnumbered,
        diagnostics=list(dict.fromkeys(diagnostics)),
    )
    return table, sidecar


def _global_grid(fragments: list[TableFragmentCandidate]) -> RawTableGrid | None:
    if not fragments:
        return None
    column_count = fragments[0].grid.column_count
    if any(fragment.grid.column_count != column_count for fragment in fragments):
        return None
    cells: list[RawTableCell] = []
    row_offset = 0
    complete = True
    for fragment in fragments:
        complete = complete and fragment.grid.complete
        for cell in fragment.grid.cells:
            cells.append(
                RawTableCell(
                    row=row_offset + cell.row,
                    col=cell.col,
                    row_span=cell.row_span,
                    col_span=cell.col_span,
                    text=cell.text,
                    is_header=cell.is_header or cell.row < fragment.header_row_count,
                    recognition_status=RecognitionStatus.UNVERIFIED,
                    source_block_ids=[fragment.block_id],
                )
            )
        row_offset += fragment.grid.row_count
    return RawTableGrid(
        row_count=row_offset,
        column_count=column_count,
        cells=cells,
        extraction_status=(
            RawGridExtractionStatus.COMPLETE if complete else RawGridExtractionStatus.PARTIAL
        ),
    )


def _table_id(source_sha256: str, fragments: list[TableFragmentCandidate], group_index: int) -> str:
    first = fragments[0]
    anchor = first.table_number or f"p{first.page_number}-i{first.source_index}-g{group_index}"
    return _stable_id(
        "table", source_sha256, anchor, str(first.page_number), str(first.source_index)
    )


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, '|'.join(parts)).hex}"


def _omission(
    page_number: int, source_index: int, reason: str, *, detail: str | None = None
) -> dict[str, object]:
    result: dict[str, object] = {
        "page_number": page_number,
        "source_index": source_index,
        "raw_type": "table",
        "reason": reason,
    }
    if detail is not None:
        result["detail"] = detail
    return result
