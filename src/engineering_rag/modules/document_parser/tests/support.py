"""Test-only PDF, FileStore, and OCR helpers."""

from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

from engineering_rag.contracts.common import FileRef
from engineering_rag.contracts.documents import ParseConfig, ParseRequest, StandardMetadata
from engineering_rag.modules.document_parser.internal.ocr import OcrSpan
from engineering_rag.modules.document_parser.internal.pdf_backend import RasterizedPage


class MemoryFileStore:
    def __init__(self, content: bytes, *, fail: bool = False) -> None:
        self.content = content
        self.fail = fail

    @contextmanager
    def read(self, reference: FileRef) -> Iterator[BytesIO]:
        del reference
        if self.fail:
            raise OSError("test read failure")
        yield BytesIO(self.content)


class FakeRecognizer:
    engine_name = "fake"
    engine_version = "test-1"

    def __init__(
        self, spans: list[OcrSpan] | None = None, *, error: Exception | None = None
    ) -> None:
        self.spans = spans or []
        self.error = error
        self.calls: list[int] = []

    def recognize(self, page: RasterizedPage) -> list[OcrSpan]:
        self.calls.append(page.page_number)
        if self.error is not None:
            raise self.error
        return self.spans


class FailingRecognizer(FakeRecognizer):
    def __init__(self) -> None:
        super().__init__(error=RuntimeError("synthetic OCR failure"))


def request_for(
    content: bytes,
    *,
    pages: str = "1",
    options: dict[str, str | int | float | bool] | None = None,
) -> tuple[MemoryFileStore, ParseRequest]:
    store = MemoryFileStore(content)
    merged: dict[str, str | int | float | bool] = {"page_selection": pages, "dpi": 144}
    if options:
        merged.update(options)
    request = ParseRequest(
        source_file=FileRef(
            file_id="file-test-pdf",
            uri="memory://test.pdf",
            mime_type="application/pdf",
            size_bytes=len(content),
        ),
        supplied_standard=StandardMetadata(
            standard_name="虚构测试标准",
            standard_code="TEST 1-2026",
            edition="测试版",
            language="zh-CN",
        ),
        config=ParseConfig(config_id="task1.1-test", options=merged),
    )
    return store, request


def make_text_pdf(texts: list[str], *, rotate: int = 0, crop: bool = False) -> bytes:
    import pymupdf

    document = pymupdf.open()
    for text in texts:
        page = document.new_page(width=360, height=240)
        page.insert_text((36, 72), text, fontsize=18)
        if crop:
            page.set_cropbox(pymupdf.Rect(20, 10, 340, 220))
        if rotate:
            page.set_rotation(rotate)
    result = document.tobytes()
    document.close()
    return result


def make_scanned_pdf(text: str = "ENGINEERING PDF 2026") -> bytes:
    import pymupdf
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (1400, 500), "white")
    draw = ImageDraw.Draw(image)
    font_path = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    font = ImageFont.truetype(str(font_path), 90)
    draw.text((80, 100), text, fill="black", font=font)
    image_buffer = BytesIO()
    image.save(image_buffer, format="PNG")

    document = pymupdf.open()
    page = document.new_page(width=700, height=250)
    page.insert_image(page.rect, stream=image_buffer.getvalue())
    result = document.tobytes()
    document.close()
    return result
