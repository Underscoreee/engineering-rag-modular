#!/usr/bin/env python3
"""Render normalized MinerU bboxes over the actual PDF pages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--normalized", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=160)
    args = parser.parse_args()
    import pymupdf
    from PIL import Image, ImageDraw

    data = json.loads(args.normalized.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    with pymupdf.open(args.pdf) as document:
        for page in data["pages"]:
            number = page["page_number"]
            pixmap = document[number - 1].get_pixmap(
                matrix=pymupdf.Matrix(args.dpi / 72, args.dpi / 72)
            )
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            draw = ImageDraw.Draw(image)
            colors = {"table": "#00a86b", "equation": "#c2185b"}
            for element in page["elements"]:
                bbox = element.get("bbox")
                if bbox is None:
                    continue
                box = (
                    bbox["x_min"] * pixmap.width,
                    bbox["y_min"] * pixmap.height,
                    bbox["x_max"] * pixmap.width,
                    bbox["y_max"] * pixmap.height,
                )
                color = colors.get(element["raw_type"], "#1565c0")
                draw.rectangle(box, outline=color, width=3)
                draw.text((box[0] + 2, box[1] + 2), element["raw_type"], fill=color)
            image.save(args.output / f"page-{number:04d}-overlay.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
