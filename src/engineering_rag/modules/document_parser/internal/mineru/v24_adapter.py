"""Conservative MinerU candidate mapping into frozen partial Document V2.4."""

from __future__ import annotations

import re
from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from engineering_rag.contracts.common import BoundingBox, ContractError, ErrorCode, FileRef
from engineering_rag.contracts.documents import (
    BboxCoordinateSystem,
    BboxStatus,
    BlockType,
    ClauseGroups,
    ContentExtractionStatus,
    Document,
    Equation,
    FormulaGroup,
    FormulaNumberStatus,
    LogicalTable,
    LogicalTableStatus,
    OcrContent,
    Page,
    PageBlock,
    PageType,
    ProcessingMetadata,
    RecognitionStatus,
    StandardMetadata,
    TableFragment,
    TableFragmentStatus,
)

from .models import MinerUElement, MinerUParseResult

_TAG = re.compile(r"\\tag\{([^{}]+)\}\s*$")


@dataclass(frozen=True, slots=True)
class MinerUV24Adaptation:
    document: Document
    omitted_elements: list[dict[str, object]]


def adapt_to_v24(
    result: MinerUParseResult,
    *,
    source_file: FileRef,
    standard: StandardMetadata,
    page_count: int,
) -> MinerUV24Adaptation:
    document_id = _stable_id(
        "doc", source_file.file_id, standard.standard_code, standard.edition or ""
    )
    tables: list[LogicalTable] = []
    pages: list[Page] = []
    omitted: list[dict[str, object]] = []
    warnings: list[ContractError] = []
    for parsed_page in result.pages:
        blocks: list[PageBlock] = []
        for element in parsed_page.elements:
            if element.bbox is None:
                omitted.append(_omission(element, "missing_or_invalid_bbox"))
                continue
            bbox = BoundingBox(
                x_min=element.bbox.x_min * parsed_page.width_points,
                y_min=element.bbox.y_min * parsed_page.height_points,
                x_max=element.bbox.x_max * parsed_page.width_points,
                y_max=element.bbox.y_max * parsed_page.height_points,
            )
            block_id = _stable_id(
                "block",
                result.source_sha256,
                str(element.page_number),
                str(element.source_index),
                element.raw_type,
            )
            if element.raw_type == "table":
                table_id = _stable_id("table", block_id)
                block = PageBlock(
                    block_id=block_id,
                    block_type=BlockType.TABLE,
                    bbox=bbox,
                    reading_order=len(blocks),
                    ocr=OcrContent(text=element.table_caption),
                    recognition_status=RecognitionStatus.UNVERIFIED,
                    bbox_status=BboxStatus.UNVERIFIED,
                    extraction_method=f"mineru:{result.producer_version}",
                    table_id=table_id,
                    fragment_index=0,
                    fragment_status=TableFragmentStatus.UNVERIFIED,
                )
                blocks.append(block)
                tables.append(
                    LogicalTable(
                        table_id=table_id,
                        title=element.table_caption,
                        page_start=element.page_number,
                        page_end=element.page_number,
                        source_block_ids=[block_id],
                        fragments=[
                            TableFragment(
                                page_number=element.page_number,
                                block_id=block_id,
                                fragment_index=0,
                            )
                        ],
                        columns=[],
                        data=None,
                        notes=None,
                        raw_grid=None,
                        extraction_status=LogicalTableStatus.STRUCTURE_ONLY,
                        normalization_warning=(
                            "MinerU HTML is retained in the raw sidecar; Task 1.2 does not "
                            "infer cells or cross-page table identity"
                        ),
                    )
                )
                continue
            if element.raw_type == "equation":
                latex = element.latex
                number_match = _TAG.search(latex or "")
                equation_number = number_match.group(1) if number_match else None
                formula_id = _stable_id("formula", block_id, "0")
                blocks.append(
                    PageBlock(
                        block_id=block_id,
                        block_type=BlockType.FORMULA,
                        bbox=bbox,
                        reading_order=len(blocks),
                        ocr=OcrContent(
                            formula_group=FormulaGroup(
                                equations=[
                                    Equation(
                                        formula_id=formula_id,
                                        equation_number=equation_number,
                                        equation_number_status=(
                                            FormulaNumberStatus.PRINTED
                                            if equation_number
                                            else FormulaNumberStatus.UNKNOWN
                                        ),
                                        latex=latex,
                                        recognition_status=RecognitionStatus.UNVERIFIED,
                                    )
                                ]
                            )
                        ),
                        recognition_status=RecognitionStatus.UNVERIFIED,
                        bbox_status=BboxStatus.UNVERIFIED,
                        extraction_method=f"mineru:{result.producer_version}",
                        formula_group_id=_stable_id("formula-group", block_id),
                    )
                )
                continue
            if element.raw_type in {"image", "figure"}:
                omitted.append(_omission(element, "no_immutable_asset_reference"))
                continue
            if not element.text:
                omitted.append(_omission(element, "no_mappable_text_payload"))
                continue
            block_type = (
                BlockType.TITLE
                if element.raw_type in {"title", "paragraph_title", "document_title", "doc_title"}
                else BlockType.BODY
            )
            blocks.append(
                PageBlock(
                    block_id=block_id,
                    block_type=block_type,
                    bbox=bbox,
                    reading_order=len(blocks),
                    ocr=OcrContent(text=element.text),
                    recognition_status=RecognitionStatus.UNVERIFIED,
                    bbox_status=BboxStatus.UNVERIFIED,
                    extraction_method=f"mineru:{result.producer_version}",
                )
            )
        pages.append(
            Page(
                page_number=parsed_page.page_number,
                page_type=PageType.UNKNOWN,
                page_type_basis="task1.2_mineru_candidate_not_domain_classified",
                width=parsed_page.width_points,
                height=parsed_page.height_points,
                content_extraction_status=ContentExtractionStatus.PARTIALLY_TRANSCRIBED,
                blocks=blocks,
            )
        )
    if omitted:
        warnings.append(
            ContractError(
                code=ErrorCode.UNSUPPORTED,
                message=f"{len(omitted)} MinerU elements retained only in raw sidecar",
                field="pages",
                retryable=False,
            )
        )
    document = Document(
        schema_version="2.4",
        document_id=document_id,
        bbox_coordinate_system=BboxCoordinateSystem(unit="pdf_points", origin="top_left"),
        source_file=source_file,
        standard=standard,
        page_count=page_count,
        pages=pages,
        sections=[],
        tables=tables,
        clauses=ClauseGroups(),
        processing=ProcessingMetadata(
            parser_id="engineering_rag.document_parser.mineru",
            parser_version="1.2.0",
            partial=True,
            is_complete_document_ocr=False,
            warnings=warnings,
        ),
    )
    return MinerUV24Adaptation(
        document=Document.model_validate_json(document.model_dump_json()),
        omitted_elements=omitted,
    )


def _omission(element: MinerUElement, reason: str) -> dict[str, object]:
    return {
        "page_number": element.page_number,
        "source_index": element.source_index,
        "raw_type": element.raw_type,
        "reason": reason,
    }


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, '|'.join(parts)).hex}"
