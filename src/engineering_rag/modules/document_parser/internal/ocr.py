"""Replaceable private OCR vocabulary; it is deliberately not a public contract."""

from dataclasses import dataclass
from typing import Protocol

from .pdf_backend import RasterizedPage


class OcrError(RuntimeError):
    """Base error for OCR initialization and recognition failures."""


class OcrUnavailableError(OcrError):
    """Raised when the configured OCR runtime is not installed."""


class OcrResultError(OcrError):
    """Raised when an OCR engine returns malformed geometry or content."""


@dataclass(frozen=True, slots=True)
class OcrSpan:
    text: str
    pixel_bbox: tuple[float, float, float, float]
    confidence: float | None
    source_index: int


class PageTextRecognizer(Protocol):
    @property
    def engine_name(self) -> str: ...

    @property
    def engine_version(self) -> str: ...

    def recognize(self, page: RasterizedPage) -> list[OcrSpan]: ...
