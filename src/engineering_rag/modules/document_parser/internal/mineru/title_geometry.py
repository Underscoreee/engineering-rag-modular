"""Geometry predicates used by MinerU title classification."""

from typing import Final

from engineering_rag.contracts.common import BoundingBox

# OCR/layout bboxes can drift slightly; allow a title center to deviate by at most
# ten percent of the full PDF page width from the page's horizontal center.
TITLE_CENTER_TOLERANCE_RATIO: Final[float] = 0.10


def is_horizontally_centered(bbox: BoundingBox, page_width: float) -> bool:
    """Return whether ``bbox`` is centered enough to remain a title candidate."""
    block_center_x = (bbox.x_min + bbox.x_max) / 2
    page_center_x = page_width / 2
    center_tolerance = page_width * TITLE_CENTER_TOLERANCE_RATIO
    return abs(block_center_x - page_center_x) <= center_tolerance
