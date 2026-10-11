#!/usr/bin/env python3
"""Prepare bounded local page previews and source mapping for Task 1.2."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dpi", type=int, default=160)
    args = parser.parse_args()
    if not 72 <= args.dpi <= 240:
        parser.error("--dpi must be between 72 and 240")
    cases = json.loads(args.cases.read_text(encoding="utf-8"))["cases"]
    pages = sorted({number for case in cases for number in case["physical_pages"]})
    if len(pages) > 30:
        parser.error("refusing to prepare more than 30 pages")
    import pymupdf

    args.output.mkdir(parents=True, exist_ok=True)
    page_records: dict[str, object] = {}
    with pymupdf.open(args.pdf) as document:
        for number in pages:
            page = document[number - 1]
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(args.dpi / 72, args.dpi / 72))
            image = args.output / "pages" / f"page-{number:04d}.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(pixmap.tobytes("png"))
            page_records[str(number)] = {
                "image": str(image),
                "page_idx": number - 1,
                "width_points": float(page.rect.width),
                "height_points": float(page.rect.height),
                "rotation": int(page.rotation),
                "cropbox": [float(value) for value in page.cropbox],
                "pixel_width": pixmap.width,
                "pixel_height": pixmap.height,
            }
        page_count = document.page_count
    manifest = {
        "source_pdf": str(args.pdf),
        "source_sha256": _sha256(args.pdf),
        "source_size_bytes": args.pdf.stat().st_size,
        "source_page_count": page_count,
        "dpi": args.dpi,
        "local_only": True,
        "pages": page_records,
        "cases": cases,
    }
    path = args.output / "prepared-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(path)
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
