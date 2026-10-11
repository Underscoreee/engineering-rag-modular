"""Lazy CPU Chinese OCR adapter for rapidocr-onnxruntime 1.x."""

from collections.abc import Callable
from importlib.metadata import PackageNotFoundError, version
from math import isfinite
from typing import Protocol

from .ocr import OcrError, OcrResultError, OcrSpan, OcrUnavailableError
from .pdf_backend import RasterizedPage


class _RapidEngine(Protocol):
    def __call__(self, image: bytes) -> tuple[list[list[object]] | None, object]: ...


class RapidOcrRecognizer:
    """RapidOCR adapter that loads bundled ONNX models on first recognition only."""

    def __init__(self, engine_factory: Callable[[], _RapidEngine] | None = None) -> None:
        self._engine_factory = engine_factory
        self._engine: _RapidEngine | None = None

    @property
    def engine_name(self) -> str:
        return "rapidocr_onnxruntime"

    @property
    def engine_version(self) -> str:
        try:
            return version("rapidocr-onnxruntime")
        except PackageNotFoundError:
            return "unavailable"

    def recognize(self, page: RasterizedPage) -> list[OcrSpan]:
        engine = self._get_engine()
        try:
            result, _elapsed = engine(page.png_bytes)
        except Exception as exc:
            raise OcrError(f"RapidOCR failed on page {page.page_number}: {exc}") from exc
        spans: list[OcrSpan] = []
        for source_index, item in enumerate(result or []):
            spans.append(_parse_item(item, source_index))
        return spans

    def _get_engine(self) -> _RapidEngine:
        if self._engine is None:
            if self._engine_factory is not None:
                self._engine = self._engine_factory()
            else:
                try:
                    from rapidocr_onnxruntime import RapidOCR
                except ImportError as exc:
                    raise OcrUnavailableError(
                        "RapidOCR is unavailable; install the project parser-ocr extra"
                    ) from exc
                self._engine = RapidOCR()
        return self._engine


def _parse_item(item: list[object], source_index: int) -> OcrSpan:
    if not isinstance(item, list) or len(item) < 3:
        raise OcrResultError("RapidOCR item must contain polygon, text, and confidence")
    polygon, text, confidence = item[0], item[1], item[2]
    if not isinstance(text, str) or not text.strip():
        raise OcrResultError("RapidOCR text must be non-empty")
    if not isinstance(polygon, list) or len(polygon) < 4:
        raise OcrResultError("RapidOCR polygon must contain at least four points")
    try:
        points = [(float(point[0]), float(point[1])) for point in polygon]  # type: ignore[index]
        score = float(confidence)
    except (TypeError, ValueError, IndexError) as exc:
        raise OcrResultError("RapidOCR item contains invalid numeric values") from exc
    values = [coordinate for point in points for coordinate in point]
    if not all(isfinite(value) for value in (*values, score)) or not 0 <= score <= 1:
        raise OcrResultError("RapidOCR geometry/confidence is outside its valid range")
    x_values = [point[0] for point in points]
    y_values = [point[1] for point in points]
    return OcrSpan(
        text=text.strip(),
        pixel_bbox=(min(x_values), min(y_values), max(x_values), max(y_values)),
        confidence=score,
        source_index=source_index,
    )
