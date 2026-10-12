"""Safe geometry-backed splitting for mixed OCR body blocks."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engineering_rag.contracts.common import BoundingBox
from engineering_rag.contracts.documents import BlockType, Document, OcrContent, PageBlock

BBOX_CONTAINMENT_TOLERANCE_POINTS = 0.01


class UnsafeBlockSplitError(ValueError):
    """A split was rejected; callers must retain the original block and queue review."""

    def __init__(self, block_id: str, reason: str):
        super().__init__(f"unsafe split for {block_id}: {reason}")
        self.block_id = block_id
        self.reason = reason

    def pending_diagnostic(self) -> dict[str, str]:
        return {
            "relation_type": "block_split_review",
            "source_block_id": self.block_id,
            "decision": "original_block_retained",
            "reason": self.reason,
        }


class TextSpanEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    bbox: BoundingBox
    geometry_reliable: bool = True

    @model_validator(mode="after")
    def check_range(self) -> TextSpanEvidence:
        if self.end <= self.start:
            raise ValueError("span end must follow start")
        return self


def split_body_block(
    document: Document, block_id: str, spans: list[TextSpanEvidence]
) -> tuple[Document, dict[str, list[str]]]:
    """Split one body block only when exact non-overlapping text spans and bboxes exist."""

    candidate = document.model_copy(deep=True)
    for page in candidate.pages:
        for position, block in enumerate(page.blocks):
            if block.block_id != block_id:
                continue
            if block.block_type != BlockType.BODY or block.ocr is None or block.ocr.text is None:
                raise ValueError("safe splitting requires a body block with OCR text")
            ordered = list(spans)
            if ordered != sorted(ordered, key=lambda item: item.start):
                raise UnsafeBlockSplitError(
                    block_id, "text span evidence is not in source text order"
                )
            if not ordered or ordered[0].start != 0 or ordered[-1].end != len(block.ocr.text):
                raise UnsafeBlockSplitError(
                    block_id, "span evidence must cover the complete source text"
                )
            if any(
                left.end != right.start for left, right in zip(ordered, ordered[1:], strict=False)
            ):
                raise UnsafeBlockSplitError(
                    block_id, "span evidence must be contiguous and non-overlapping"
                )
            if any(not span.geometry_reliable for span in ordered):
                raise UnsafeBlockSplitError(
                    block_id,
                    "bbox geometry is not reliable enough for source-preserving splitting",
                )
            for span in ordered:
                if not _bbox_within(span.bbox, block.bbox):
                    raise UnsafeBlockSplitError(
                        block_id,
                        "child bbox geometry must remain within the source block region",
                    )
            if any(
                not _follows_reading_order(left.bbox, right.bbox)
                for left, right in zip(ordered, ordered[1:], strict=False)
            ):
                raise UnsafeBlockSplitError(
                    block_id,
                    "child bbox geometry contradicts the source text reading order",
                )
            replacements: list[PageBlock] = []
            for span in ordered:
                text = block.ocr.text[span.start : span.end]
                if not text:
                    raise UnsafeBlockSplitError(
                        block_id, "span evidence cannot create an empty block"
                    )
                replacements.append(
                    block.model_copy(
                        update={
                            "block_id": _split_id(block.block_id, span.start, span.end),
                            "bbox": span.bbox,
                            "ocr": OcrContent(text=text),
                        }
                    )
                )
            page.blocks[position : position + 1] = replacements
            page.blocks = [
                item.model_copy(update={"reading_order": order})
                for order, item in enumerate(page.blocks)
            ]
            validated = Document.model_validate(candidate.model_dump(mode="json"))
            return validated, {block_id: [item.block_id for item in replacements]}
    raise ValueError(f"unknown block_id: {block_id}")


def _split_id(block_id: str, start: int, end: int) -> str:
    return f"block-{uuid5(NAMESPACE_URL, f'{block_id}|{start}:{end}').hex}"


def _bbox_within(child: BoundingBox, source: BoundingBox) -> bool:
    tolerance = BBOX_CONTAINMENT_TOLERANCE_POINTS
    return (
        child.x_min >= source.x_min - tolerance
        and child.y_min >= source.y_min - tolerance
        and child.x_max <= source.x_max + tolerance
        and child.y_max <= source.y_max + tolerance
    )


def _follows_reading_order(left: BoundingBox, right: BoundingBox) -> bool:
    tolerance = BBOX_CONTAINMENT_TOLERANCE_POINTS
    is_later_line = right.y_min >= left.y_max - tolerance
    vertical_overlap = min(left.y_max, right.y_max) - max(left.y_min, right.y_min)
    is_later_on_same_line = vertical_overlap > tolerance and right.x_min >= left.x_max - tolerance
    return is_later_line or is_later_on_same_line
