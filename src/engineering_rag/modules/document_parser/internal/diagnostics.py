"""Non-contract parser diagnostics and optional page observation hooks."""

from dataclasses import asdict, dataclass, field
from typing import Protocol

from engineering_rag.contracts.documents import PageBlock

from .pdf_backend import RasterizedPage


@dataclass(frozen=True, slots=True)
class OcrConfidenceSummary:
    count: int
    minimum: float
    maximum: float
    mean: float

    @classmethod
    def from_values(cls, values: list[float]) -> "OcrConfidenceSummary | None":
        if not values:
            return None
        return cls(
            count=len(values),
            minimum=min(values),
            maximum=max(values),
            mean=sum(values) / len(values),
        )


@dataclass(slots=True)
class PageDiagnostic:
    page_number: int
    status: str
    source: str
    text_item_count: int
    elapsed_seconds: float
    messages: list[str] = field(default_factory=list)
    ocr_confidence: OcrConfidenceSummary | None = None


@dataclass(slots=True)
class ParserDiagnostics:
    parser_id: str
    parser_version: str
    pdf_backend: str
    ocr_engine: str
    ocr_version: str
    page_count: int
    selected_pages: list[int]
    dpi: float
    pages: list[PageDiagnostic]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class PageObserver(Protocol):
    """Optional private hook used by the diagnostic CLI for overlays."""

    def observe(self, raster: RasterizedPage, blocks: list[PageBlock]) -> None: ...
