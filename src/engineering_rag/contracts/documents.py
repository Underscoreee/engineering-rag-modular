"""Document Schema V2.4: physical pages, logical tables, and semantic clauses."""

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import Field, RootModel, StrictInt, model_validator

from .common import (
    ArtifactRef,
    BoundingBox,
    ContractError,
    ContractModel,
    FileRef,
    NonEmptyStr,
    PositivePage,
    Sha256,
    TraceContext,
)

DOCUMENT_SCHEMA_VERSION = "2.4"
PLAIN_TEXT_RENDERER_VERSION = "1"


class PageType(StrEnum):
    OUTER_COVER = "outer_cover"
    INNER_COVER = "inner_cover"
    PUBLICATION_NOTICE = "publication_notice"
    PREFACE = "preface"
    TOC_ZH = "toc_zh"
    TOC_EN = "toc_en"
    BODY = "body"
    WORDING_RULES = "wording_rules"
    NORMATIVE_REFERENCES = "normative_references"
    EXPLANATION_COVER = "explanation_cover"
    REVISION_NOTES = "revision_notes"
    EXPLANATION_TOC = "explanation_toc"
    EXPLANATION_BODY = "explanation_body"
    UNKNOWN = "unknown"


class BlockType(StrEnum):
    TITLE = "title"
    BODY = "body"
    TABLE = "table"
    IMAGE = "image"
    FORMULA = "formula"


class ContentExtractionStatus(StrEnum):
    NOT_PROCESSED = "not_processed"
    PARTIALLY_TRANSCRIBED = "partially_transcribed"
    COMPLETE = "complete"


class RecognitionStatus(StrEnum):
    NOT_PROCESSED = "not_processed"
    NOT_TRANSCRIBED = "not_transcribed"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class BboxStatus(StrEnum):
    DETECTED = "detected"
    MANUAL_APPROXIMATE = "manual_approximate"
    UNVERIFIED = "unverified"


class FormulaNumberStatus(StrEnum):
    PRINTED = "printed"
    CONFIRMED_ABSENT = "confirmed_absent"
    UNKNOWN = "unknown"


class TableFragmentStatus(StrEnum):
    NOT_PROCESSED = "not_processed"
    NOT_TRANSCRIBED = "not_transcribed"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class LogicalTableStatus(StrEnum):
    STRUCTURE_ONLY = "structure_only"
    UNVERIFIED = "unverified"
    VERIFIED = "verified"


class RawGridExtractionStatus(StrEnum):
    PARTIAL = "partial"
    COMPLETE = "complete"


class ContentGroup(StrEnum):
    NORMATIVE = "normative"
    EXPLANATION = "explanation"


class SectionType(StrEnum):
    CHAPTER = "chapter"
    SECTION = "section"
    APPENDIX = "appendix"
    EXPLANATION = "explanation"
    OTHER = "other"


class ClauseContentType(StrEnum):
    BODY = "body"
    TABLE = "table"
    FORMULA = "formula"
    IMAGE = "image"
    LIST_ITEM = "list_item"


class TableColumnRole(StrEnum):
    ROW_HEADER = "row_header"
    COLUMN_HEADER = "column_header"
    DIMENSION = "dimension"
    VALUE = "value"


class MandatoryEvidenceSourceType(StrEnum):
    OFFICIAL_ANNOUNCEMENT = "official_announcement"
    OFFICIAL_AMENDMENT = "official_amendment"
    PUBLISHED_STANDARD = "published_standard"
    REVIEWED_RECORD = "reviewed_record"


class EvidenceVerificationStatus(StrEnum):
    PENDING = "pending"
    VERIFIED = "verified"
    REJECTED = "rejected"


class BboxCoordinateSystem(ContractModel):
    unit: Literal["pdf_points"]
    origin: Literal["top_left"]


class StandardMetadata(ContractModel):
    standard_name: NonEmptyStr
    standard_code: NonEmptyStr
    edition: str | None = None
    revision: str | None = None
    language: str | None = None


class Equation(ContractModel):
    formula_id: NonEmptyStr
    equation_number: str | None
    equation_number_status: FormulaNumberStatus
    latex: str | None = None
    text: str | None = None
    recognition_status: RecognitionStatus

    @model_validator(mode="after")
    def check_number_and_recognition(self) -> "Equation":
        if (
            self.recognition_status
            in {
                RecognitionStatus.NOT_PROCESSED,
                RecognitionStatus.NOT_TRANSCRIBED,
            }
            and self.latex is not None
        ):
            raise ValueError("unprocessed equation cannot claim recognized latex")
        if self.equation_number_status == FormulaNumberStatus.PRINTED:
            if not self.equation_number:
                raise ValueError("printed equation requires equation_number")
        elif self.equation_number is not None:
            raise ValueError("non-printed or unknown number must be null")
        if (
            self.equation_number_status == FormulaNumberStatus.CONFIRMED_ABSENT
            and self.recognition_status != RecognitionStatus.VERIFIED
        ):
            raise ValueError("absence of printed number must be verified")
        if self.recognition_status == RecognitionStatus.VERIFIED:
            if not self.latex:
                raise ValueError("verified equation requires latex")
            if self.equation_number_status == FormulaNumberStatus.UNKNOWN:
                raise ValueError("verified equation requires resolved number status")
        return self


class SymbolExplanationItem(ContractModel):
    symbol: NonEmptyStr
    latex: str | None = None
    description: NonEmptyStr


class SymbolExplanations(ContractModel):
    items: list[SymbolExplanationItem] = Field(min_length=1)


class FormulaGroup(ContractModel):
    equations: list[Equation] = Field(min_length=1)
    symbol_explanations: SymbolExplanations | None = None


class OcrContent(ContractModel):
    text: str | None = None
    formula_group: FormulaGroup | None = None


class PageBlock(ContractModel):
    block_id: NonEmptyStr
    block_type: BlockType
    bbox: BoundingBox
    reading_order: Annotated[int, Field(ge=0)]
    ocr: OcrContent | None = None
    asset: ArtifactRef | None = None
    recognition_status: RecognitionStatus = RecognitionStatus.VERIFIED
    bbox_status: BboxStatus = BboxStatus.DETECTED
    extraction_method: str | None = None
    table_id: NonEmptyStr | None = None
    fragment_index: Annotated[int, Field(ge=0)] | None = None
    fragment_status: TableFragmentStatus | None = None
    formula_group_id: NonEmptyStr | None = None

    @model_validator(mode="after")
    def check_payload(self) -> "PageBlock":
        if self.block_type == BlockType.TABLE:
            if self.table_id is None:
                raise ValueError("table block requires table_id")
            if (
                self.fragment_status
                in {
                    TableFragmentStatus.NOT_PROCESSED,
                    TableFragmentStatus.NOT_TRANSCRIBED,
                }
                and self.recognition_status == RecognitionStatus.VERIFIED
            ):
                raise ValueError("unprocessed table fragment cannot be verified")
        elif any(x is not None for x in (self.table_id, self.fragment_index, self.fragment_status)):
            raise ValueError("table fragment fields belong only to table blocks")
        if self.block_type == BlockType.FORMULA:
            if self.formula_group_id is None:
                raise ValueError("formula block requires formula_group_id")
            if self.recognition_status == RecognitionStatus.VERIFIED and (
                self.ocr is None or self.ocr.formula_group is None
            ):
                raise ValueError("verified formula block requires formula_group")
            if (
                self.recognition_status == RecognitionStatus.VERIFIED
                and self.ocr is not None
                and self.ocr.formula_group is not None
                and any(
                    equation.recognition_status != RecognitionStatus.VERIFIED
                    for equation in self.ocr.formula_group.equations
                )
            ):
                raise ValueError("verified formula block contains unverified equation")
        elif self.formula_group_id is not None or (self.ocr and self.ocr.formula_group):
            raise ValueError("formula_group belongs only to formula blocks")
        if (
            self.block_type in {BlockType.TITLE, BlockType.BODY}
            and self.recognition_status == RecognitionStatus.VERIFIED
            and (self.ocr is None or not self.ocr.text)
        ):
            raise ValueError("verified text block requires OCR text")
        if self.block_type == BlockType.IMAGE and self.asset is None:
            raise ValueError("image block requires asset")
        return self


class Page(ContractModel):
    page_number: PositivePage
    page_type: PageType
    width: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    height: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    content_extraction_status: ContentExtractionStatus
    blocks: list[PageBlock] = Field(default_factory=list)
    page_type_basis: str | None = None

    @model_validator(mode="after")
    def check_status(self) -> "Page":
        if self.content_extraction_status == ContentExtractionStatus.NOT_PROCESSED and self.blocks:
            raise ValueError("not_processed page cannot declare extracted blocks")
        return self


class TableFragment(ContractModel):
    page_number: PositivePage
    block_id: NonEmptyStr
    fragment_index: Annotated[int, Field(ge=0)]
    label: str | None = None


class TableColumn(ContractModel):
    key: NonEmptyStr
    header_path: list[NonEmptyStr] = Field(min_length=1)
    role: TableColumnRole
    derived: bool = False
    description: str | None = None


class TableNote(ContractModel):
    number: Annotated[int, Field(gt=0)]
    content: NonEmptyStr


class RawTableCell(ContractModel):
    row: Annotated[int, Field(ge=0)]
    col: Annotated[int, Field(ge=0)]
    row_span: Annotated[int, Field(ge=1)] = 1
    col_span: Annotated[int, Field(ge=1)] = 1
    text: str | None
    is_header: bool
    recognition_status: RecognitionStatus
    source_block_ids: list[NonEmptyStr] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_recognition(self) -> "RawTableCell":
        if (
            self.recognition_status
            in {
                RecognitionStatus.NOT_PROCESSED,
                RecognitionStatus.NOT_TRANSCRIBED,
            }
            and self.text is not None
        ):
            raise ValueError("unprocessed raw cell text must be null")
        if self.recognition_status == RecognitionStatus.VERIFIED and self.text is None:
            raise ValueError("verified raw cell requires text")
        return self


class RawTableGrid(ContractModel):
    row_count: Annotated[int, Field(gt=0)]
    column_count: Annotated[int, Field(gt=0)]
    cells: list[RawTableCell] = Field(default_factory=list)
    extraction_status: RawGridExtractionStatus

    @model_validator(mode="after")
    def validate_topology(self) -> "RawTableGrid":
        occupied: set[tuple[int, int]] = set()
        for cell in self.cells:
            if cell.row + cell.row_span > self.row_count:
                raise ValueError("raw cell row span exceeds grid")
            if cell.col + cell.col_span > self.column_count:
                raise ValueError("raw cell column span exceeds grid")
            covered = {
                (row, col)
                for row in range(cell.row, cell.row + cell.row_span)
                for col in range(cell.col, cell.col + cell.col_span)
            }
            if occupied & covered:
                raise ValueError("raw table cells overlap")
            occupied.update(covered)
        expected = self.row_count * self.column_count
        if self.extraction_status == RawGridExtractionStatus.COMPLETE and len(occupied) != expected:
            raise ValueError("complete raw grid must cover every grid position")
        return self


class TableRow(RootModel[dict[NonEmptyStr, str | StrictInt | None]]):
    """Flat record: declared business columns plus explicit source metadata keys."""


class LogicalTable(ContractModel):
    table_id: NonEmptyStr
    table_number: str | None = None
    title: str | None = None
    page_start: PositivePage
    page_end: PositivePage
    source_block_ids: list[NonEmptyStr] = Field(min_length=1)
    fragments: list[TableFragment] = Field(min_length=1)
    columns: list[TableColumn] = Field(default_factory=list)
    data: list[TableRow] | None = None
    notes: list[TableNote] | None = None
    raw_grid: RawTableGrid | None = None
    extraction_status: LogicalTableStatus
    normalization_warning: str | None = None

    @model_validator(mode="after")
    def check_shape(self) -> "LogicalTable":
        if self.page_end < self.page_start:
            raise ValueError("table page range is reversed")
        keys = [column.key for column in self.columns]
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate table column key")
        if set(keys) & {"source_page", "source_block_id"}:
            raise ValueError("table source metadata keys cannot be business columns")
        if len({note.number for note in self.notes or []}) != len(self.notes or []):
            raise ValueError("duplicate table note number")
        if self.notes == []:
            raise ValueError("tables without notes must use null")
        if self.extraction_status == LogicalTableStatus.VERIFIED and (
            not self.columns or not self.data
        ):
            raise ValueError("verified table requires columns and data")
        if self.extraction_status == LogicalTableStatus.STRUCTURE_ONLY and self.data is not None:
            raise ValueError("structure-only table cannot claim transcribed data")
        for row in self.data or []:
            cells = row.root
            if set(cells) - {"source_page", "source_block_id"} != set(keys):
                raise ValueError("table row cells must match declared columns")
            if any(
                value is not None and not isinstance(value, str)
                for key, value in cells.items()
                if key in keys
            ):
                raise ValueError("table business cell values must be strings or null")
            source_page = cells.get("source_page")
            if source_page is not None and (
                type(source_page) is not int or not self.page_start <= source_page <= self.page_end
            ):
                raise ValueError("table row source_page outside table range")
            source_block_id = cells.get("source_block_id")
            if source_block_id is not None and (
                not isinstance(source_block_id, str) or not source_block_id
            ):
                raise ValueError("table row source_block_id must be non-empty string")
        return self


class Section(ContractModel):
    section_id: NonEmptyStr
    number: NonEmptyStr | None = None
    title: NonEmptyStr
    section_type: SectionType
    content_group: ContentGroup
    parent_section_id: NonEmptyStr | None = None
    structure_path: list[NonEmptyStr] = Field(min_length=1)


class ClauseContentUnit(ContractModel):
    order: Annotated[int, Field(ge=0)]
    content_type: ClauseContentType
    source_block_ids: list[NonEmptyStr] = Field(min_length=1)
    table_id: NonEmptyStr | None = None
    formula_ids: list[NonEmptyStr] = Field(default_factory=list)
    asset_id: NonEmptyStr | None = None
    list_item_label: str | None = None

    @model_validator(mode="after")
    def check_reference_shape(self) -> "ClauseContentUnit":
        if len(set(self.source_block_ids)) != len(self.source_block_ids):
            raise ValueError("content unit source_block_ids must be unique")
        if self.content_type == ClauseContentType.TABLE and self.table_id is None:
            raise ValueError("table unit requires table_id")
        if self.content_type != ClauseContentType.TABLE and self.table_id is not None:
            raise ValueError("table_id belongs only to table units")
        if self.content_type == ClauseContentType.FORMULA and not self.formula_ids:
            raise ValueError("formula unit requires formula_ids")
        if self.content_type != ClauseContentType.FORMULA and self.formula_ids:
            raise ValueError("formula_ids belong only to formula units")
        if len(set(self.formula_ids)) != len(self.formula_ids):
            raise ValueError("formula_ids must be unique within a content unit")
        if self.content_type == ClauseContentType.IMAGE and self.asset_id is None:
            raise ValueError("image unit requires asset_id")
        if self.content_type != ClauseContentType.IMAGE and self.asset_id is not None:
            raise ValueError("asset_id belongs only to image units")
        if self.content_type != ClauseContentType.LIST_ITEM and self.list_item_label is not None:
            raise ValueError("list_item_label belongs only to list_item units")
        return self


class ClauseContent(ContractModel):
    plain_text: str | None = None
    plain_text_renderer_version: NonEmptyStr | None = None
    plain_text_source_digest: Sha256 | None = None
    content_units: list[ClauseContentUnit] = Field(default_factory=list)
    transcription_status: RecognitionStatus = RecognitionStatus.VERIFIED
    review_warning: str | None = None

    @model_validator(mode="after")
    def check_order(self) -> "ClauseContent":
        orders = [unit.order for unit in self.content_units]
        if orders != sorted(set(orders)):
            raise ValueError("content unit order must be unique and ascending")
        metadata = (self.plain_text_renderer_version, self.plain_text_source_digest)
        if self.plain_text is None and any(item is not None for item in metadata):
            raise ValueError("plain_text metadata requires a cached plain_text")
        if self.plain_text is not None and any(item is None for item in metadata):
            raise ValueError("plain_text cache requires renderer version and source digest")
        return self


class MandatoryEvidence(ContractModel):
    evidence_id: NonEmptyStr
    source_type: MandatoryEvidenceSourceType
    source_document_id: NonEmptyStr | None = None
    source_page: PositivePage | None = None
    external_uri: NonEmptyStr | None = None
    reference_text: NonEmptyStr | None = None
    verification_status: EvidenceVerificationStatus
    conclusion: bool | None
    verified_by: NonEmptyStr | None = None
    verified_at: datetime | None = None

    @model_validator(mode="after")
    def validate_evidence(self) -> "MandatoryEvidence":
        if self.source_page is not None and self.source_document_id is None:
            raise ValueError("source_page requires source_document_id")
        if self.external_uri is not None and not urlparse(self.external_uri).scheme:
            raise ValueError("external_uri requires a URI scheme")
        if self.verification_status == EvidenceVerificationStatus.PENDING:
            if (
                self.conclusion is not None
                or self.verified_by is not None
                or self.verified_at is not None
            ):
                raise ValueError("pending evidence cannot claim conclusion or verification")
            return self
        if self.verified_by is None or self.verified_at is None:
            raise ValueError("reviewed evidence requires verified_by and verified_at")
        if self.verified_at.tzinfo is None or self.verified_at.utcoffset() != UTC.utcoffset(None):
            raise ValueError("verified_at must be timezone-aware UTC")
        if self.verification_status == EvidenceVerificationStatus.REJECTED:
            if self.conclusion is not None:
                raise ValueError("rejected evidence cannot support a conclusion")
            return self
        if self.conclusion is None:
            raise ValueError("verified evidence requires a boolean conclusion")
        if self.external_uri is None and not (
            self.source_document_id is not None and self.source_page is not None
        ):
            raise ValueError("verified evidence requires a document page or external URI")
        return self


class Clause(ContractModel):
    clause_id: NonEmptyStr
    clause_number: NonEmptyStr
    section_id: NonEmptyStr
    clause_content: ClauseContent
    page_start: PositivePage
    page_end: PositivePage
    source_block_ids: list[NonEmptyStr] = Field(min_length=1)
    is_mandatory: bool | None = None
    mandatory_evidence: list[MandatoryEvidence] = Field(default_factory=list)
    explains_clause_id: NonEmptyStr | None = None

    @model_validator(mode="after")
    def check_page_range(self) -> "Clause":
        if self.page_end < self.page_start:
            raise ValueError("clause page range is reversed")
        return self


class ClauseGroups(ContractModel):
    normative: list[Clause] = Field(default_factory=list)
    explanations: list[Clause] = Field(default_factory=list)


class ProcessingMetadata(ContractModel):
    parser_id: NonEmptyStr
    parser_version: NonEmptyStr
    partial: bool
    is_complete_document_ocr: bool
    warnings: list[ContractError] = Field(default_factory=list)


class Document(ContractModel):
    schema_version: Literal["2.4"]
    document_id: NonEmptyStr
    bbox_coordinate_system: BboxCoordinateSystem
    source_file: FileRef
    standard: StandardMetadata
    page_count: Annotated[int, Field(gt=0)]
    pages: list[Page] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    tables: list[LogicalTable] = Field(default_factory=list)
    clauses: ClauseGroups = Field(default_factory=ClauseGroups)
    processing: ProcessingMetadata

    @model_validator(mode="after")
    def check_references(self) -> "Document":
        errors = validate_document_references(self)
        if errors:
            raise ValueError("; ".join(f"{e.field}: {e.message}" for e in errors))
        return self


class ParseConfig(ContractModel):
    config_id: NonEmptyStr
    options: dict[str, str | int | float | bool] = Field(default_factory=dict)


class ParseRequest(ContractModel):
    source_file: FileRef
    supplied_standard: StandardMetadata | None = None
    config: ParseConfig | None = None
    trace: TraceContext | None = None


def validate_document_references(document: Document) -> list[ContractError]:
    """Check references already declared by a complete or partial Document."""
    errors: list[ContractError] = []
    pages: dict[int, Page] = {}
    blocks: dict[str, tuple[int, PageBlock]] = {}
    formula_ids: set[str] = set()
    formula_groups: set[str] = set()
    assets: dict[str, ArtifactRef] = {}
    for page in document.pages:
        if page.page_number in pages:
            errors.append(_error("pages", "duplicate page_number"))
        pages[page.page_number] = page
        if page.page_number > document.page_count:
            errors.append(_error("pages", "page_number exceeds page_count"))
        orders: set[int] = set()
        for block in page.blocks:
            if block.reading_order in orders:
                errors.append(_error(block.block_id, "duplicate page reading_order"))
            orders.add(block.reading_order)
            if block.block_id in blocks:
                errors.append(_error(block.block_id, "duplicate block_id"))
            blocks[block.block_id] = (page.page_number, block)
            if block.bbox.x_max > page.width or block.bbox.y_max > page.height:
                errors.append(_error(block.block_id, "bbox exceeds page dimensions"))
            group = block.ocr.formula_group if block.ocr else None
            if block.formula_group_id is not None:
                if block.formula_group_id in formula_groups:
                    errors.append(_error(block.formula_group_id, "duplicate formula_group_id"))
                formula_groups.add(block.formula_group_id)
            for equation in group.equations if group else []:
                if equation.formula_id in formula_ids:
                    errors.append(_error(equation.formula_id, "duplicate formula_id"))
                formula_ids.add(equation.formula_id)
            if block.asset is not None:
                previous = assets.get(block.asset.artifact_id)
                if previous is not None and previous != block.asset:
                    errors.append(_error(block.asset.artifact_id, "conflicting asset identity"))
                assets[block.asset.artifact_id] = block.asset
    sections = {section.section_id: section for section in document.sections}
    if len(sections) != len(document.sections):
        errors.append(_error("sections", "duplicate section_id"))
    errors.extend(_check_sections(sections))
    tables = {table.table_id: table for table in document.tables}
    if len(tables) != len(document.tables):
        errors.append(_error("tables", "duplicate table_id"))
    for table in document.tables:
        errors.extend(_check_table(table, blocks))
    for block_id, (_, block) in blocks.items():
        if block.block_type != BlockType.TABLE:
            continue
        table = tables.get(block.table_id or "")
        if table is None:
            errors.append(_error(block_id, "table block references unknown table_id"))
        elif block_id not in table.source_block_ids:
            errors.append(_error(block_id, "table block is missing from logical table fragments"))
    normative = {clause.clause_id: clause for clause in document.clauses.normative}
    all_clauses = document.clauses.normative + document.clauses.explanations
    if len({clause.clause_id for clause in all_clauses}) != len(all_clauses):
        errors.append(_error("clauses", "duplicate clause_id"))
    evidence_ids: set[str] = set()
    for clause in document.clauses.normative:
        if clause.page_end > document.page_count:
            errors.append(_error(clause.clause_id, "clause range exceeds page_count"))
        errors.extend(
            _check_clause(
                clause,
                ContentGroup.NORMATIVE,
                sections,
                blocks,
                tables,
                assets,
                document,
            )
        )
        errors.extend(_check_mandatory_evidence(clause, document, evidence_ids))
        if clause.explains_clause_id is not None:
            errors.append(_error(clause.clause_id, "normative clause cannot explain"))
    for clause in document.clauses.explanations:
        if clause.page_end > document.page_count:
            errors.append(_error(clause.clause_id, "clause range exceeds page_count"))
        errors.extend(
            _check_clause(
                clause,
                ContentGroup.EXPLANATION,
                sections,
                blocks,
                tables,
                assets,
                document,
            )
        )
        if clause.is_mandatory is not None or clause.mandatory_evidence:
            errors.append(
                _error(clause.clause_id, "mandatory evidence belongs only to normative clauses")
            )
        if clause.explains_clause_id is not None and clause.explains_clause_id not in normative:
            errors.append(
                _error(clause.clause_id, "explains_clause_id must target normative clause")
            )
    if not document.processing.partial:
        if not document.processing.is_complete_document_ocr:
            errors.append(_error("processing", "non-partial document requires complete OCR"))
        if len(pages) != document.page_count or any(
            page.content_extraction_status != ContentExtractionStatus.COMPLETE
            for page in pages.values()
        ):
            errors.append(_error("processing", "non-partial document requires all complete pages"))
    if document.processing.is_complete_document_ocr and (
        len(pages) != document.page_count
        or any(
            page.content_extraction_status != ContentExtractionStatus.COMPLETE
            for page in pages.values()
        )
    ):
        errors.append(_error("processing", "complete OCR requires every page marked complete"))
    return errors


def _check_sections(sections: dict[str, Section]) -> list[ContractError]:
    errors: list[ContractError] = []
    for section in sections.values():
        parent_id = section.parent_section_id
        if parent_id is not None:
            parent = sections.get(parent_id)
            if parent is None or parent_id == section.section_id:
                errors.append(_error(section.section_id, "invalid parent_section_id"))
            elif parent.content_group != section.content_group:
                errors.append(_error(section.section_id, "parent content_group mismatch"))
            elif (
                len(section.structure_path) != len(parent.structure_path) + 1
                or section.structure_path[:-1] != parent.structure_path
            ):
                errors.append(_error(section.section_id, "structure_path must extend parent path"))
        seen: set[str] = set()
        current: str | None = section.section_id
        while current in sections:
            if current in seen:
                errors.append(_error(section.section_id, "section parent cycle"))
                break
            seen.add(current)
            current = sections[current].parent_section_id
    return errors


def _check_table(
    table: LogicalTable, blocks: dict[str, tuple[int, PageBlock]]
) -> list[ContractError]:
    errors: list[ContractError] = []
    indexes = [fragment.fragment_index for fragment in table.fragments]
    ids = [fragment.block_id for fragment in table.fragments]
    if indexes != list(range(len(indexes))):
        errors.append(_error(table.table_id, "fragment indexes must ascend from zero"))
    if len(set(ids)) != len(ids) or len(set(table.source_block_ids)) != len(ids):
        errors.append(_error(table.table_id, "duplicate table fragment or source block"))
    if ids != table.source_block_ids:
        errors.append(_error(table.table_id, "fragments and source_block_ids order mismatch"))
    previous_page = 0
    for fragment in table.fragments:
        location = blocks.get(fragment.block_id)
        if location is None:
            errors.append(_error(table.table_id, "unknown table fragment block"))
            continue
        page_number, block = location
        if page_number < previous_page or page_number != fragment.page_number:
            errors.append(_error(table.table_id, "fragment page order or page_number mismatch"))
        previous_page = page_number
        if block.block_type != BlockType.TABLE or block.table_id != table.table_id:
            errors.append(_error(table.table_id, "fragment block type or table_id mismatch"))
        if block.fragment_index != fragment.fragment_index:
            errors.append(_error(table.table_id, "fragment index conflicts with page block"))
        if table.extraction_status == LogicalTableStatus.VERIFIED and (
            block.fragment_status != TableFragmentStatus.VERIFIED
        ):
            errors.append(_error(table.table_id, "verified table has unverified fragment"))
        if not table.page_start <= page_number <= table.page_end:
            errors.append(_error(table.table_id, "fragment outside table page range"))
    if table.fragments and (
        table.fragments[0].page_number != table.page_start
        or table.fragments[-1].page_number != table.page_end
    ):
        errors.append(_error(table.table_id, "table page range must match fragments"))
    for row in table.data or []:
        source_block_id = row.root.get("source_block_id")
        if source_block_id is not None and source_block_id not in table.source_block_ids:
            errors.append(_error(table.table_id, "table row source_block_id is not a fragment"))
        if source_block_id is not None and row.root.get("source_page") is not None:
            location = blocks.get(source_block_id)
            if location is not None and location[0] != row.root["source_page"]:
                errors.append(_error(table.table_id, "table row source page and block disagree"))
    if table.raw_grid is not None:
        for cell in table.raw_grid.cells:
            if not set(cell.source_block_ids).issubset(table.source_block_ids):
                errors.append(_error(table.table_id, "raw cell source is not a table fragment"))
    return errors


def _check_clause(
    clause: Clause,
    group: ContentGroup,
    sections: dict[str, Section],
    blocks: dict[str, tuple[int, PageBlock]],
    tables: dict[str, LogicalTable],
    assets: dict[str, ArtifactRef],
    document: Document,
) -> list[ContractError]:
    errors: list[ContractError] = []
    section = sections.get(clause.section_id)
    if section is None or section.content_group != group:
        errors.append(_error(clause.clause_id, "section_id missing or content_group mismatch"))
    if len(set(clause.source_block_ids)) != len(clause.source_block_ids):
        errors.append(_error(clause.clause_id, "duplicate clause source_block_id"))
    for block_id in clause.source_block_ids:
        location = blocks.get(block_id)
        if location is None:
            errors.append(_error(clause.clause_id, f"unknown block_id: {block_id}"))
        elif not clause.page_start <= location[0] <= clause.page_end:
            errors.append(_error(clause.clause_id, "source block outside clause page range"))
    unit_sources: list[str] = []
    for unit in clause.clause_content.content_units:
        unit_sources.extend(
            block_id for block_id in unit.source_block_ids if block_id not in unit_sources
        )
        if not set(unit.source_block_ids).issubset(clause.source_block_ids):
            errors.append(_error(clause.clause_id, "unit sources must belong to clause"))
        for block_id in unit.source_block_ids:
            location = blocks.get(block_id)
            if location is None:
                errors.append(_error(clause.clause_id, "unit references unknown block"))
            elif unit.content_type != ClauseContentType.LIST_ITEM and (
                location[1].block_type.value != unit.content_type.value
            ):
                errors.append(_error(clause.clause_id, "unit and source block type mismatch"))
            elif unit.content_type == ClauseContentType.LIST_ITEM and (
                location[1].block_type != BlockType.BODY
            ):
                errors.append(_error(clause.clause_id, "list_item must source body block"))
        if unit.table_id is not None:
            table = tables.get(unit.table_id)
            if table is None:
                errors.append(_error(clause.clause_id, "unit references unknown table_id"))
            elif not set(table.source_block_ids).issubset(unit.source_block_ids):
                errors.append(_error(clause.clause_id, "table unit must cover all table fragments"))
        if unit.formula_ids:
            available = {
                equation.formula_id
                for block_id in unit.source_block_ids
                if (location := blocks.get(block_id)) is not None
                if location[1].ocr is not None
                if location[1].ocr.formula_group is not None
                for equation in location[1].ocr.formula_group.equations
            }
            if not set(unit.formula_ids).issubset(available):
                errors.append(
                    _error(clause.clause_id, "formula_ids are not supplied by source blocks")
                )
        if unit.asset_id is not None:
            source_assets = {
                location[1].asset.artifact_id
                for block_id in unit.source_block_ids
                if (location := blocks.get(block_id)) is not None
                if location[1].asset is not None
            }
            if unit.asset_id not in assets or unit.asset_id not in source_assets:
                errors.append(_error(clause.clause_id, "asset_id is not supplied by source blocks"))
    if unit_sources != clause.source_block_ids:
        errors.append(
            _error(clause.clause_id, "clause source cache must match ordered unit sources")
        )
    content = clause.clause_content
    if content.plain_text is not None:
        rendered = derive_clause_plain_text(document, clause)
        if rendered is None:
            errors.append(
                _error(clause.clause_id, "plain_text cannot be current with missing source text")
            )
        else:
            text, digest = rendered
            if content.plain_text_renderer_version != PLAIN_TEXT_RENDERER_VERSION:
                errors.append(_error(clause.clause_id, "plain_text renderer version is stale"))
            if content.plain_text_source_digest != digest or content.plain_text != text:
                errors.append(
                    _error(clause.clause_id, "plain_text cache does not match its sources")
                )
    return errors


def _check_mandatory_evidence(
    clause: Clause, document: Document, evidence_ids: set[str]
) -> list[ContractError]:
    errors: list[ContractError] = []
    verified: set[bool] = set()
    for evidence in clause.mandatory_evidence:
        if evidence.evidence_id in evidence_ids:
            errors.append(_error(evidence.evidence_id, "duplicate evidence_id"))
        evidence_ids.add(evidence.evidence_id)
        if (
            evidence.source_document_id == document.document_id
            and evidence.source_page is not None
            and evidence.source_page not in {page.page_number for page in document.pages}
        ):
            errors.append(
                _error(evidence.evidence_id, "evidence page is not declared in source document")
            )
        if (
            evidence.verification_status == EvidenceVerificationStatus.VERIFIED
            and evidence.conclusion is not None
        ):
            verified.add(evidence.conclusion)
    if clause.is_mandatory is not None:
        if clause.is_mandatory not in verified:
            errors.append(
                _error(clause.clause_id, "definite mandatory state lacks verified evidence")
            )
        if len(verified) > 1:
            errors.append(
                _error(clause.clause_id, "definite mandatory state has conflicting evidence")
            )
    return errors


def collect_document_diagnostics(document: Document) -> list[ContractError]:
    """Return non-fatal diagnostics retained by an otherwise valid Document."""

    diagnostics: list[ContractError] = []
    for clause in document.clauses.normative:
        conclusions = {
            evidence.conclusion
            for evidence in clause.mandatory_evidence
            if evidence.verification_status == EvidenceVerificationStatus.VERIFIED
            and evidence.conclusion is not None
        }
        if len(conclusions) > 1:
            diagnostics.append(
                ContractError(
                    code="conflict",
                    field=clause.clause_id,
                    message="verified mandatory evidence has conflicting conclusions",
                )
            )
    return diagnostics


def derive_clause_plain_text(document: Document, clause: Clause) -> tuple[str, str] | None:
    """Render a deterministic cache value from authoritative referenced objects only."""

    blocks = {block.block_id: block for page in document.pages for block in page.blocks}
    tables = {table.table_id: table for table in document.tables}
    pieces: list[str] = []
    dependencies: list[object] = []
    for unit in clause.clause_content.content_units:
        dependencies.append(unit.model_dump(mode="json"))
        if unit.content_type in {ClauseContentType.BODY, ClauseContentType.LIST_ITEM}:
            if any(block_id not in blocks for block_id in unit.source_block_ids):
                return None
            texts = [
                blocks[block_id].ocr.text if blocks[block_id].ocr else None
                for block_id in unit.source_block_ids
            ]
            if any(text is None for text in texts):
                return None
            pieces.extend(text for text in texts if text is not None)
            dependencies.extend(
                blocks[block_id].model_dump(mode="json") for block_id in unit.source_block_ids
            )
        elif unit.content_type == ClauseContentType.TABLE:
            table = tables.get(unit.table_id or "")
            if table is None or table.data is None:
                return None
            header = " | ".join(" / ".join(column.header_path) for column in table.columns)
            rows = [
                " | ".join(str(row.root.get(column.key) or "") for column in table.columns)
                for row in table.data
            ]
            notes = [f"注{note.number}：{note.content}" for note in table.notes or []]
            pieces.append("\n".join(filter(None, [table.title, header, *rows, *notes])))
            dependencies.append(table.model_dump(mode="json"))
        elif unit.content_type == ClauseContentType.FORMULA:
            equations: dict[str, Equation] = {}
            for block_id in unit.source_block_ids:
                if block_id not in blocks:
                    return None
                block = blocks[block_id]
                dependencies.append(block.model_dump(mode="json"))
                group = block.ocr.formula_group if block.ocr else None
                equations.update(
                    {equation.formula_id: equation for equation in group.equations if group}
                    if group
                    else {}
                )
            if any(formula_id not in equations for formula_id in unit.formula_ids):
                return None
            formula_text = [
                equations[formula_id].text or equations[formula_id].latex
                for formula_id in unit.formula_ids
            ]
            if any(text is None for text in formula_text):
                return None
            pieces.extend(text for text in formula_text if text is not None)
        else:
            if any(block_id not in blocks for block_id in unit.source_block_ids):
                return None
            image_texts = [
                blocks[block_id].ocr.text if blocks[block_id].ocr else None
                for block_id in unit.source_block_ids
            ]
            if any(text is None for text in image_texts):
                return None
            pieces.extend(text for text in image_texts if text is not None)
            dependencies.extend(
                blocks[block_id].model_dump(mode="json") for block_id in unit.source_block_ids
            )
    text = "\n".join(pieces)
    payload = json.dumps(dependencies, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return text, hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _error(field: str, message: str) -> ContractError:
    return ContractError(code="invalid_input", message=message, field=field)
