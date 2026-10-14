"""Process-local MinerU 4.0.12 compatibility hook.

MinerU already rejects OCR boxes narrower than its confidence threshold, but
4.0.12 attempts a perspective crop first.  A detector-produced zero-area box
therefore reaches docvortex with a zero output dimension.  This hook moves only
the exact zero-area rejection ahead of the crop and emits an auditable marker.
"""

from __future__ import annotations

import math
import sys
from importlib.metadata import PackageNotFoundError, version
from typing import Any

SUPPORTED_MINERU_VERSION = "4.0.12"


def _has_zero_crop_dimension(result: Any) -> bool:
    try:
        points = result[0] if len(result) == 2 else result
        width = int(
            max(
                math.dist(points[0], points[1]),
                math.dist(points[2], points[3]),
            )
        )
        height = int(
            max(
                math.dist(points[0], points[3]),
                math.dist(points[1], points[2]),
            )
        )
    except (IndexError, TypeError, ValueError):
        return False
    return width <= 0 or height <= 0


def _install() -> None:
    try:
        mineru_version = version("mineru")
    except PackageNotFoundError:
        return
    if mineru_version != SUPPORTED_MINERU_VERSION:
        return

    from mineru.model.ocr import results as ocr_results

    original = ocr_results.get_ocr_result_list

    def get_ocr_result_list(
        ocr_res: list[Any],
        useful_list: list[int],
        ocr_enable: bool,
        bgr_image: Any,
    ) -> list[dict[str, Any]]:
        retained = [item for item in ocr_res if not _has_zero_crop_dimension(item)]
        removed = len(ocr_res) - len(retained)
        if removed:
            print(
                "ENGINEERING_RAG_MINERU_COMPAT "
                f"version={mineru_version} filtered_zero_area_ocr_boxes={removed}",
                file=sys.stderr,
                flush=True,
            )
        return original(retained, useful_list, ocr_enable, bgr_image)

    ocr_results.get_ocr_result_list = get_ocr_result_list


_install()
