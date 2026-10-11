"""PyMuPDF-backed, bounded PDF access for Document Parser Task 1.1."""

import hashlib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from io import BufferedIOBase
from math import ceil, isfinite
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import BinaryIO

from engineering_rag.contracts.common import BoundingBox


class PdfBackendError(RuntimeError):
    """Base error for PDF input and rendering failures."""


class PdfInputError(PdfBackendError):
    """Raised for empty, non-PDF, damaged, or protected input."""


class PdfResourceLimitError(PdfBackendError):
    """Raised before a configured file or raster limit is exceeded."""


class SourceIntegrityError(PdfInputError):
    """Raised when declared FileRef metadata disagrees with the bytes read."""


@dataclass(frozen=True, slots=True)
class PdfPageMetadata:
    page_number: int
    width: float
    height: float
    rotation: int
    cropbox: tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class TextSpan:
    text: str
    bbox: BoundingBox
    source_index: int
    clipped_to_visible_page: bool = False


@dataclass(frozen=True, slots=True)
class CopiedSource:
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class RasterizedPage:
    page_number: int
    page_width: float
    page_height: float
    pixel_width: int
    pixel_height: int
    dpi: float
    png_bytes: bytes


def pixel_bbox_to_pdf(
    bbox: tuple[float, float, float, float], raster: RasterizedPage
) -> BoundingBox:
    """Map a top-left pixel bbox onto the visible PDF page rectangle."""

    x_min, y_min, x_max, y_max = bbox
    values = (x_min, y_min, x_max, y_max)
    if not all(isfinite(value) for value in values):
        raise ValueError("OCR bbox coordinates must be finite")
    if x_min < 0 or y_min < 0 or x_max > raster.pixel_width or y_max > raster.pixel_height:
        raise ValueError("OCR bbox exceeds rendered page bounds")
    if x_max <= x_min or y_max <= y_min:
        raise ValueError("OCR bbox must have positive area")
    return BoundingBox(
        x_min=x_min * raster.page_width / raster.pixel_width,
        y_min=y_min * raster.page_height / raster.pixel_height,
        x_max=x_max * raster.page_width / raster.pixel_width,
        y_max=y_max * raster.page_height / raster.pixel_height,
    )


def pdf_bbox_to_pixel(bbox: BoundingBox, raster: RasterizedPage) -> tuple[float, ...]:
    """Map a PDF bbox back to pixels for diagnostic overlays."""

    return (
        bbox.x_min * raster.pixel_width / raster.page_width,
        bbox.y_min * raster.pixel_height / raster.page_height,
        bbox.x_max * raster.pixel_width / raster.page_width,
        bbox.y_max * raster.pixel_height / raster.page_height,
    )


class PdfDocument:
    """Small wrapper that keeps third-party PyMuPDF types private."""

    def __init__(self, document: object, pymupdf_module: object) -> None:
        self._document = document
        self._pymupdf = pymupdf_module
        self._text_diagnostics: dict[int, tuple[str, ...]] = {}

    @property
    def page_count(self) -> int:
        return int(self._document.page_count)  # type: ignore[attr-defined]

    @property
    def backend_version(self) -> str:
        return str(self._pymupdf.VersionBind)  # type: ignore[attr-defined]

    def page_metadata(self, page_number: int) -> PdfPageMetadata:
        page = self._load_page(page_number)
        rect = page.rect
        cropbox = page.cropbox
        return PdfPageMetadata(
            page_number=page_number,
            width=float(rect.width),
            height=float(rect.height),
            rotation=int(page.rotation),
            cropbox=tuple(float(value) for value in cropbox),
        )

    def extract_text_spans(self, page_number: int) -> list[TextSpan]:
        page = self._load_page(page_number)
        spans: list[TextSpan] = []
        messages: list[str] = []
        visible_page = page.rect
        for source_index, raw in enumerate(page.get_text("blocks", sort=False)):
            if len(raw) < 7 or int(raw[6]) != 0:
                continue
            text = str(raw[4]).strip()
            if not text:
                continue
            source_rect = self._pymupdf.Rect(*raw[:4])  # type: ignore[attr-defined]
            visible_rect = source_rect * page.rotation_matrix
            clipped_rect = visible_rect & visible_page
            if clipped_rect.is_empty or clipped_rect.width <= 0 or clipped_rect.height <= 0:
                messages.append(
                    f"text block {source_index} is outside the visible CropBox and was omitted"
                )
                continue
            clipped = not _rects_close(visible_rect, clipped_rect)
            if clipped:
                messages.append(f"text block {source_index} was clipped to the visible CropBox")
            spans.append(
                TextSpan(
                    text=text,
                    bbox=BoundingBox(
                        x_min=float(clipped_rect.x0),
                        y_min=float(clipped_rect.y0),
                        x_max=float(clipped_rect.x1),
                        y_max=float(clipped_rect.y1),
                    ),
                    source_index=source_index,
                    clipped_to_visible_page=clipped,
                )
            )
        self._text_diagnostics[page_number] = tuple(messages)
        return spans

    def text_diagnostics(self, page_number: int) -> tuple[str, ...]:
        return self._text_diagnostics.get(page_number, ())

    def rasterize(self, page_number: int, dpi: float, max_pixels: int) -> RasterizedPage:
        page = self._load_page(page_number)
        rect = page.rect
        zoom = dpi / 72.0
        expected_pixels = ceil(rect.width * zoom) * ceil(rect.height * zoom)
        if expected_pixels > max_pixels:
            raise PdfResourceLimitError(
                f"page {page_number} render would use {expected_pixels} pixels; "
                f"limit is {max_pixels}"
            )
        matrix = self._pymupdf.Matrix(zoom, zoom)  # type: ignore[attr-defined]
        pixmap = page.get_pixmap(matrix=matrix, colorspace=self._pymupdf.csRGB, alpha=False)
        actual_pixels = int(pixmap.width) * int(pixmap.height)
        if actual_pixels > max_pixels:
            raise PdfResourceLimitError(
                f"page {page_number} rendered to {actual_pixels} pixels; limit is {max_pixels}"
            )
        return RasterizedPage(
            page_number=page_number,
            page_width=float(rect.width),
            page_height=float(rect.height),
            pixel_width=int(pixmap.width),
            pixel_height=int(pixmap.height),
            dpi=dpi,
            png_bytes=pixmap.tobytes("png"),
        )

    def _load_page(self, page_number: int) -> object:
        if not 1 <= page_number <= self.page_count:
            raise PdfInputError(f"page {page_number} is outside 1..{self.page_count}")
        return self._document.load_page(page_number - 1)  # type: ignore[attr-defined]


class PyMuPdfBackend:
    """Open a FileStore stream via a bounded temporary PDF file."""

    @contextmanager
    def open(
        self,
        source: BinaryIO,
        *,
        max_bytes: int,
        expected_size_bytes: int | None = None,
        expected_sha256: str | None = None,
    ) -> Iterator[PdfDocument]:
        try:
            import pymupdf
        except ImportError as exc:  # pragma: no cover - exercised without parser extra
            raise PdfBackendError(
                "PyMuPDF is unavailable; install the project parser extra"
            ) from exc

        with TemporaryDirectory(prefix="engineering-rag-parser-") as directory:
            path = Path(directory) / "source.pdf"
            copied = _copy_bounded(source, path, max_bytes)
            if expected_size_bytes is not None and copied.size_bytes != expected_size_bytes:
                raise SourceIntegrityError(
                    "source size_bytes integrity mismatch: "
                    f"declared {expected_size_bytes}, read {copied.size_bytes}"
                )
            if expected_sha256 is not None and copied.sha256 != expected_sha256:
                raise SourceIntegrityError("source sha256 integrity mismatch")
            if copied.size_bytes == 0:
                raise PdfInputError("PDF input is empty")
            with path.open("rb") as input_file:
                header = input_file.read(1024)
            if b"%PDF-" not in header:
                raise PdfInputError("input does not have a PDF header")
            try:
                document = pymupdf.open(path)
            except Exception as exc:
                raise PdfInputError(f"PyMuPDF could not open input: {exc}") from exc
            try:
                if document.needs_pass:
                    raise PdfInputError("password-protected PDF is not supported")
                if document.page_count <= 0:
                    raise PdfInputError("PDF contains no pages")
                yield PdfDocument(document, pymupdf)
            finally:
                document.close()


def _copy_bounded(source: BinaryIO, target: Path, max_bytes: int) -> CopiedSource:
    if not isinstance(source, BufferedIOBase) and not hasattr(source, "read"):
        raise PdfInputError("FileStore.read did not return a binary stream")
    total = 0
    digest = hashlib.sha256()
    with target.open("wb") as output:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise PdfInputError("FileStore stream must return bytes")
            total += len(chunk)
            if total > max_bytes:
                raise PdfResourceLimitError(f"PDF input exceeds configured {max_bytes}-byte limit")
            output.write(chunk)
            digest.update(chunk)
    return CopiedSource(size_bytes=total, sha256=digest.hexdigest())


def _rects_close(first: object, second: object, tolerance: float = 1e-6) -> bool:
    return all(
        abs(float(left) - float(right)) <= tolerance
        for left, right in zip(first, second, strict=True)
    )
