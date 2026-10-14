"""Private table candidates that retain raw MinerU evidence."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from engineering_rag.contracts.documents import LogicalTable
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUBbox


class _PrivateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ParsedHtmlCell(_PrivateModel):
    row: int = Field(ge=0)
    col: int = Field(ge=0)
    row_span: int = Field(ge=1)
    col_span: int = Field(ge=1)
    text: str
    is_header: bool
    source_order: int = Field(ge=0)


class ParsedHtmlGrid(_PrivateModel):
    row_count: int = Field(gt=0)
    column_count: int = Field(gt=0)
    cells: list[ParsedHtmlCell]
    complete: bool
    diagnostics: list[str] = Field(default_factory=list)


class TableFragmentCandidate(_PrivateModel):
    page_number: int = Field(ge=1)
    source_index: int = Field(ge=0)
    block_id: str = Field(min_length=1)
    caption: str | None = None
    table_number: str | None = None
    title: str | None = None
    is_continuation: bool = False
    raw_html: str
    raw_footnotes: list[str] = Field(default_factory=list)
    grid: ParsedHtmlGrid
    header_row_count: int = Field(ge=0)
    header_paths: list[list[str]] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class ContinuationDecision(_PrivateModel):
    should_merge: bool
    reason: str
    evidence: list[str] = Field(default_factory=list)


class TablePlacement(_PrivateModel):
    table_id: str = Field(min_length=1)
    fragment_index: int = Field(ge=0)
    label: str | None = None


class TableNoteEvidence(_PrivateModel):
    source_page_number: int = Field(ge=1)
    source_index: int = Field(ge=0)
    source_block_id: str = Field(min_length=1)
    source_bbox: MinerUBbox
    raw_text: str = Field(min_length=1)
    note_number: int = Field(ge=1)
    consumed_by_table_id: str = Field(min_length=1)


class TableSidecar(_PrivateModel):
    table_id: str = Field(min_length=1)
    table_number: str | None = None
    fragments: list[TableFragmentCandidate]
    continuation_decisions: list[ContinuationDecision] = Field(default_factory=list)
    note_evidence: list[TableNoteEvidence] = Field(default_factory=list)
    unnumbered_notes: list[str] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TableAssemblyResult:
    tables: list[LogicalTable]
    placements: dict[tuple[int, int], TablePlacement]
    sidecars: list[TableSidecar]
    consumed_body: set[tuple[int, int]]
    omitted: list[dict[str, object]]
