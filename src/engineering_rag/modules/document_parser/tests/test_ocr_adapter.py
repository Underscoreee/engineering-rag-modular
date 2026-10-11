import pytest

pytest.importorskip("pymupdf")

from engineering_rag.modules.document_parser.internal.ocr import OcrResultError  # noqa: E402
from engineering_rag.modules.document_parser.internal.ocr_rapidocr import (  # noqa: E402
    RapidOcrRecognizer,
)
from engineering_rag.modules.document_parser.internal.pdf_backend import (  # noqa: E402
    RasterizedPage,
)


class Engine:
    def __init__(self, result: list[list[object]]) -> None:
        self.result = result

    def __call__(self, image: bytes) -> tuple[list[list[object]], list[float]]:
        assert image == b"image"
        return self.result, [0.1, 0.1, 0.1]


def raster() -> RasterizedPage:
    return RasterizedPage(1, 100, 200, 1000, 2000, 200, b"image")


def test_rapidocr_result_is_converted_to_private_spans() -> None:
    raw = [[[[10, 20], [80, 20], [80, 50], [10, 50]], "中文识别", 0.91]]
    recognizer = RapidOcrRecognizer(engine_factory=lambda: Engine(raw))
    spans = recognizer.recognize(raster())
    assert spans[0].text == "中文识别"
    assert spans[0].pixel_bbox == (10, 20, 80, 50)
    assert spans[0].confidence == pytest.approx(0.91)


@pytest.mark.parametrize(
    "raw",
    [
        [["bad", "text", 0.9]],
        [[[[0, 0], [1, 0], [1, 1], [0, 1]], "", 0.9]],
        [[[[0, 0], [1, 0], [1, 1], [0, 1]], "text", 1.5]],
    ],
)
def test_malformed_rapidocr_result_is_rejected(raw: list[list[object]]) -> None:
    recognizer = RapidOcrRecognizer(engine_factory=lambda: Engine(raw))
    with pytest.raises(OcrResultError):
        recognizer.recognize(raster())


def test_rapidocr_models_are_lazy() -> None:
    recognizer = RapidOcrRecognizer()
    assert recognizer._engine is None
