"""Deterministic provisional body-block assembly for Task 1.1."""

from dataclasses import dataclass
from uuid import NAMESPACE_URL, uuid5

from engineering_rag.contracts.common import BoundingBox
from engineering_rag.contracts.documents import (
    BboxStatus,
    BlockType,
    OcrContent,
    PageBlock,
    RecognitionStatus,
)


@dataclass(frozen=True, slots=True)
class RecognizedFragment:
    text: str
    bbox: BoundingBox
    source_index: int
    extraction_method: str
    confidence: float | None = None


def build_provisional_blocks(
    document_id: str, page_number: int, fragments: list[RecognizedFragment]
) -> list[PageBlock]:
    ordered = sorted(
        fragments,
        key=lambda item: (
            round(item.bbox.y_min, 3),
            round(item.bbox.x_min, 3),
            round(item.bbox.y_max, 3),
            round(item.bbox.x_max, 3),
            item.source_index,
        ),
    )
    blocks: list[PageBlock] = []
    for reading_order, fragment in enumerate(ordered):
        anchor = ":".join(
            (
                document_id,
                str(page_number),
                fragment.extraction_method,
                str(fragment.source_index),
                *(f"{value:.3f}" for value in _bbox_values(fragment.bbox)),
            )
        )
        blocks.append(
            PageBlock(
                block_id=f"blk-{uuid5(NAMESPACE_URL, anchor).hex}",
                block_type=BlockType.BODY,
                bbox=fragment.bbox,
                reading_order=reading_order,
                ocr=OcrContent(text=fragment.text),
                recognition_status=RecognitionStatus.UNVERIFIED,
                bbox_status=BboxStatus.DETECTED,
                extraction_method=fragment.extraction_method,
            )
        )
    return blocks


def _bbox_values(bbox: BoundingBox) -> tuple[float, float, float, float]:
    return bbox.x_min, bbox.y_min, bbox.x_max, bbox.y_max
