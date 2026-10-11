"""Run the Task 1.1 parser against a local PDF and write diagnostic artifacts."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from uuid import NAMESPACE_URL, uuid5

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import (
    Document,
    PageBlock,
    ParseConfig,
    ParseRequest,
    StandardMetadata,
)
from engineering_rag.modules.document_parser.api import create_document_parser
from engineering_rag.modules.document_parser.internal.pdf_backend import (
    RasterizedPage,
    pdf_bbox_to_pixel,
)


class LocalReadOnlyFileStore:
    """CLI-only adapter implementing only the injected read capability."""

    def __init__(self, path: Path) -> None:
        self._path = path

    @contextmanager
    def read(self, reference: FileRef) -> Iterator[BinaryIO]:
        del reference
        with self._path.open("rb") as source:
            yield source


class OverlayWriter:
    def __init__(self, output_dir: Path) -> None:
        self._output_dir = output_dir
        self.paths: list[Path] = []

    def observe(self, raster: RasterizedPage, blocks: list[PageBlock]) -> None:
        from PIL import Image, ImageDraw

        image = Image.open(BytesIO(raster.png_bytes)).convert("RGB")
        draw = ImageDraw.Draw(image)
        for block in blocks:
            draw.rectangle(pdf_bbox_to_pixel(block.bbox, raster), outline="red", width=3)
        path = self._output_dir / f"page-{raster.page_number:03d}-overlay.png"
        image.save(path)
        self.paths.append(path)


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--pages", required=True, help="1-based comma/range selection")
    parser.add_argument("--dpi", type=float, default=200)
    parser.add_argument("--standard-name", required=True)
    parser.add_argument("--standard-code", required=True)
    parser.add_argument("--edition")
    parser.add_argument("--revision")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--on-page-error", choices=("raise", "continue"), default="raise")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    path = args.pdf.resolve()
    if not path.is_file():
        print(f"PDF does not exist: {path}", file=sys.stderr)
        return 2
    args.out_dir.mkdir(parents=True, exist_ok=True)
    digest, size = _file_digest(path)
    reference = FileRef(
        file_id=f"local-{uuid5(NAMESPACE_URL, path.as_uri()).hex}",
        uri=path.as_uri(),
        mime_type="application/pdf",
        sha256=digest,
        size_bytes=size,
    )
    selection_count = _selection_upper_bound(args.pages)
    request = ParseRequest(
        source_file=reference,
        supplied_standard=StandardMetadata(
            standard_name=args.standard_name,
            standard_code=args.standard_code,
            edition=args.edition,
            revision=args.revision,
            language="zh-CN",
        ),
        config=ParseConfig(
            config_id="task1.1-cli",
            options={
                "page_selection": args.pages,
                "dpi": args.dpi,
                "ocr_backend": "rapidocr",
                "on_page_error": args.on_page_error,
                "max_selected_pages": max(selection_count, 20),
            },
        ),
    )
    observer = OverlayWriter(args.out_dir)
    parser = create_document_parser(
        LocalReadOnlyFileStore(path),  # type: ignore[arg-type]
        page_observer=observer,
    )
    try:
        document = parser.parse(request)
    except Exception as exc:
        print(f"Task 1.1 parse failed: {exc}", file=sys.stderr)
        return 2
    diagnostics = parser.last_diagnostics
    if diagnostics is None:
        print("Task 1.1 parse did not produce diagnostics", file=sys.stderr)
        return 2
    (args.out_dir / "document.partial.json").write_text(
        document.model_dump_json(indent=2), encoding="utf-8"
    )
    (args.out_dir / "diagnostics.json").write_text(
        json.dumps(diagnostics.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = _summary(document, diagnostics.to_dict(), observer.paths)
    (args.out_dir / "summary.md").write_text(summary, encoding="utf-8")
    print(summary)
    return 0


def _file_digest(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _selection_upper_bound(selection: str) -> int:
    pages: set[int] = set()
    for item in selection.split(","):
        token = item.strip()
        if "-" in token:
            start, end = (int(part) for part in token.split("-", maxsplit=1))
            pages.update(range(start, end + 1))
        else:
            pages.add(int(token))
    return len(pages)


def _summary(document: Document, diagnostics: dict[str, object], overlays: list[Path]) -> str:
    selected = diagnostics["selected_pages"]
    snippets = [
        block.ocr.text
        for page in document.pages
        for block in page.blocks
        if block.ocr is not None and block.ocr.text
    ][:8]
    lines = [
        "# Document Parser Task 1.1 诊断摘要",
        "",
        f"- PDF 总页数：{document.page_count}",
        f"- 选页：{selected}",
        f"- 未处理页数：{document.page_count - len(selected)}",
        f"- OCR 引擎：{diagnostics['ocr_engine']} {diagnostics['ocr_version']}",
        (
            f"- 输出状态：partial={document.processing.partial}，"
            f"完整 OCR={document.processing.is_complete_document_ocr}"
        ),
        f"- Overlay：{', '.join(path.name for path in overlays)}",
        "",
        "## OCR 样本文本",
        "",
        *(f"- {text}" for text in snippets),
        "",
        "## 已知局限",
        "",
        (
            "Task 1.1 仅输出 provisional body blocks；未实现页面分类、复杂版面、"
            "表格、公式、Clause 或强条识别，且未计算未经人工金标支持的准确率。"
        ),
    ]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
