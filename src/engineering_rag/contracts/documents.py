"""Document Schema V2.4: physical pages, logical tables, and semantic clauses."""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, RootModel, StrictInt, model_validator

from .common import (
    ArtifactRef,
    BoundingBox,
    ContractError,
    ContractModel,
    FileRef,
    NonEmptyStr,
    PositivePage,
    TraceContext,
)

DOCUMENT_SCHEMA_VERSION = "2.4"


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
    text: str | None = None
    table_id: NonEmptyStr | None = None
    formula_group: FormulaGroup | None = None
    asset_id: NonEmptyStr | None = None

    @model_validator(mode="after")
    def check_table_reference(self) -> "ClauseContentUnit":
        if self.content_type == ClauseContentType.TABLE and self.table_id is None:
            raise ValueError("table unit requires table_id")
        if self.content_type != ClauseContentType.TABLE and self.table_id is not None:
            raise ValueError("table_id belongs only to table units")
        return self


class ClauseContent(ContractModel):
    plain_text: str | None = None
    content_units: list[ClauseContentUnit] = Field(default_factory=list)
    transcription_status: RecognitionStatus = RecognitionStatus.VERIFIED
    review_warning: str | None = None

    @model_validator(mode="after")
    def check_order(self) -> "ClauseContent":
        orders = [unit.order for unit in self.content_units]
        if orders != sorted(set(orders)):
            raise ValueError("content unit order must be unique and ascending")
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
            for equation in group.equations if group else []:
                if equation.formula_id in formula_ids:
                    errors.append(_error(equation.formula_id, "duplicate formula_id"))
                formula_ids.add(equation.formula_id)
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
        if block.block_type == BlockType.TABLE and block.table_id not in tables:
            if block.fragment_status not in {
                TableFragmentStatus.NOT_PROCESSED,
                TableFragmentStatus.NOT_TRANSCRIBED,
            }:
                errors.append(_error(block_id, "table block references unknown table_id"))
            elif not document.processing.partial:
                errors.append(_error(block_id, "unaggregated table requires partial document"))
    normative = {clause.clause_id: clause for clause in document.clauses.normative}
    all_clauses = document.clauses.normative + document.clauses.explanations
    if len({clause.clause_id for clause in all_clauses}) != len(all_clauses):
        errors.append(_error("clauses", "duplicate clause_id"))
    for clause in document.clauses.normative:
        if clause.page_end > document.page_count:
            errors.append(_error(clause.clause_id, "clause range exceeds page_count"))
        errors.extend(_check_clause(clause, ContentGroup.NORMATIVE, sections, blocks, tables))
        if clause.explains_clause_id is not None:
            errors.append(_error(clause.clause_id, "normative clause cannot explain"))
    for clause in document.clauses.explanations:
        if clause.page_end > document.page_count:
            errors.append(_error(clause.clause_id, "clause range exceeds page_count"))
        errors.extend(_check_clause(clause, ContentGroup.EXPLANATION, sections, blocks, tables))
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
    return errors


def _check_clause(
    clause: Clause,
    group: ContentGroup,
    sections: dict[str, Section],
    blocks: dict[str, tuple[int, PageBlock]],
    tables: dict[str, LogicalTable],
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
    for unit in clause.clause_content.content_units:
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
        if unit.formula_group is not None:
            if unit.content_type != ClauseContentType.FORMULA or len(unit.source_block_ids) != 1:
                errors.append(
                    _error(clause.clause_id, "formula group copy requires one formula block")
                )
            else:
                location = blocks.get(unit.source_block_ids[0])
                source_group = (
                    location[1].ocr.formula_group if location and location[1].ocr else None
                )
                if source_group != unit.formula_group:
                    errors.append(
                        _error(clause.clause_id, "formula group copy conflicts with source")
                    )
    return errors


def _error(field: str, message: str) -> ContractError:
    return ContractError(code="invalid_input", message=message, field=field)
