"""Safe geometry-backed splitting for mixed OCR body blocks."""

from __future__ import annotations

from uuid import NAMESPACE_URL, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engineering_rag.contracts.common import BoundingBox
from engineering_rag.contracts.documents import BlockType, Document, OcrContent, PageBlock


class TextSpanEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(gt=0)
    bbox: BoundingBox

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
            ordered = sorted(spans, key=lambda item: item.start)
            if not ordered or ordered[0].start != 0 or ordered[-1].end != len(block.ocr.text):
                raise ValueError("span evidence must cover the complete source text")
            if any(
                left.end != right.start for left, right in zip(ordered, ordered[1:], strict=False)
            ):
                raise ValueError("span evidence must be contiguous and non-overlapping")
            replacements: list[PageBlock] = []
            for span in ordered:
                text = block.ocr.text[span.start : span.end]
                if not text:
                    raise ValueError("span evidence cannot create an empty block")
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
