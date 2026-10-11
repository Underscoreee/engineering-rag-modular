"""Task 1.1 concrete parser: bounded PDF IO, text layer, and replaceable OCR."""

from contextlib import AbstractContextManager
from time import perf_counter
from typing import BinaryIO, cast
from uuid import NAMESPACE_URL, uuid5

from engineering_rag.contracts.common import ContractError, ErrorCode, FileRef
from engineering_rag.contracts.documents import (
    BboxCoordinateSystem,
    ClauseGroups,
    ContentExtractionStatus,
    Document,
    Page,
    PageBlock,
    PageType,
    ParseRequest,
    ProcessingMetadata,
)
from engineering_rag.contracts.protocols import FileStore

from .config import ParserConfigurationError, ParserSettings
from .diagnostics import (
    OcrConfidenceSummary,
    PageDiagnostic,
    PageObserver,
    ParserDiagnostics,
)
from .layout_baseline import RecognizedFragment, build_provisional_blocks
from .ocr import PageTextRecognizer
from .ocr_rapidocr import RapidOcrRecognizer
from .pdf_backend import PdfDocument, PyMuPdfBackend, pixel_bbox_to_pdf

PARSER_ID = "engineering_rag.document_parser.pymupdf_ocr"
PARSER_VERSION = "1.1.0"


class DocumentParserError(RuntimeError):
    """Base error for a failed Task 1.1 parse operation."""


class SourceReadError(DocumentParserError):
    """Raised when FileStore cannot provide the source stream."""


class PageProcessingError(DocumentParserError):
    """Raised when a selected page cannot be processed in strict mode."""


class PyMuPdfDocumentParser:
    """Concrete DocumentParser that always returns a partial V2.4 document."""

    def __init__(
        self,
        file_store: FileStore,
        *,
        recognizer: PageTextRecognizer | None = None,
        pdf_backend: PyMuPdfBackend | None = None,
        page_observer: PageObserver | None = None,
    ) -> None:
        self._file_store = file_store
        self._recognizer = recognizer or RapidOcrRecognizer()
        self._pdf_backend = pdf_backend or PyMuPdfBackend()
        self._page_observer = page_observer
        self.last_diagnostics: ParserDiagnostics | None = None

    def parse(self, request: ParseRequest) -> Document:
        self.last_diagnostics = None
        if request.supplied_standard is None:
            raise ParserConfigurationError(
                "supplied_standard is required; Task 1.1 does not infer identity from filenames"
            )
        settings = ParserSettings.from_contract(request.config)
        self._check_backend_option(settings.ocr_backend)
        if (
            request.source_file.size_bytes is not None
            and request.source_file.size_bytes > settings.max_pdf_bytes
        ):
            raise SourceReadError(
                f"source size exceeds configured {settings.max_pdf_bytes}-byte limit"
            )
        source_context = self._read_source(request.source_file)
        try:
            with (
                source_context as source,
                self._pdf_backend.open(
                    source,
                    max_bytes=settings.max_pdf_bytes,
                    expected_size_bytes=request.source_file.size_bytes,
                    expected_sha256=request.source_file.sha256,
                ) as pdf,
            ):
                page_count = pdf.page_count
                selected_pages = settings.resolve_pages(page_count)
                selected = set(selected_pages)
                document_id = _document_id(request)
                pages: list[Page] = []
                warnings: list[ContractError] = []
                page_diagnostics: list[PageDiagnostic] = []
                for page_number in range(1, page_count + 1):
                    metadata = pdf.page_metadata(page_number)
                    if page_number not in selected:
                        pages.append(
                            Page(
                                page_number=page_number,
                                page_type=PageType.UNKNOWN,
                                width=metadata.width,
                                height=metadata.height,
                                content_extraction_status=(ContentExtractionStatus.NOT_PROCESSED),
                                blocks=[],
                            )
                        )
                        page_diagnostics.append(
                            PageDiagnostic(
                                page_number=page_number,
                                status="not_processed",
                                source="none",
                                text_item_count=0,
                                elapsed_seconds=0.0,
                            )
                        )
                        continue
                    started = perf_counter()
                    try:
                        blocks, source_name, messages, confidence = self._process_page(
                            pdf,
                            document_id=document_id,
                            page_number=page_number,
                            settings=settings,
                        )
                        pages.append(
                            Page(
                                page_number=page_number,
                                page_type=PageType.UNKNOWN,
                                page_type_basis="task1.1_no_page_classifier",
                                width=metadata.width,
                                height=metadata.height,
                                content_extraction_status=(
                                    ContentExtractionStatus.PARTIALLY_TRANSCRIBED
                                ),
                                blocks=blocks,
                            )
                        )
                        if not blocks:
                            warning = ContractError(
                                code=ErrorCode.INTERNAL,
                                message=(
                                    "selected page produced no positioned text; remains partial"
                                ),
                                field=f"pages[{page_number}]",
                                retryable=False,
                            )
                            warnings.append(warning)
                            messages.append(warning.message)
                        page_diagnostics.append(
                            PageDiagnostic(
                                page_number=page_number,
                                status="partially_transcribed",
                                source=source_name,
                                text_item_count=len(blocks),
                                elapsed_seconds=perf_counter() - started,
                                messages=messages,
                                ocr_confidence=confidence,
                            )
                        )
                    except Exception as exc:
                        if settings.on_page_error == "raise":
                            raise PageProcessingError(
                                f"page {page_number} processing failed: {exc}"
                            ) from exc
                        warning = ContractError(
                            code=ErrorCode.INTERNAL,
                            message=f"page processing failed: {exc}",
                            field=f"pages[{page_number}]",
                            retryable=True,
                        )
                        warnings.append(warning)
                        pages.append(
                            Page(
                                page_number=page_number,
                                page_type=PageType.UNKNOWN,
                                width=metadata.width,
                                height=metadata.height,
                                content_extraction_status=(ContentExtractionStatus.NOT_PROCESSED),
                                blocks=[],
                            )
                        )
                        page_diagnostics.append(
                            PageDiagnostic(
                                page_number=page_number,
                                status="failed",
                                source="none",
                                text_item_count=0,
                                elapsed_seconds=perf_counter() - started,
                                messages=[str(exc)],
                            )
                        )
                document = Document(
                    schema_version="2.4",
                    document_id=document_id,
                    bbox_coordinate_system=BboxCoordinateSystem(
                        unit="pdf_points", origin="top_left"
                    ),
                    source_file=request.source_file,
                    standard=request.supplied_standard,
                    page_count=page_count,
                    pages=pages,
                    sections=[],
                    tables=[],
                    clauses=ClauseGroups(),
                    processing=ProcessingMetadata(
                        parser_id=PARSER_ID,
                        parser_version=PARSER_VERSION,
                        partial=True,
                        is_complete_document_ocr=False,
                        warnings=warnings,
                    ),
                )
                self.last_diagnostics = ParserDiagnostics(
                    parser_id=PARSER_ID,
                    parser_version=PARSER_VERSION,
                    pdf_backend=f"PyMuPDF {pdf.backend_version}",
                    ocr_engine=self._recognizer.engine_name,
                    ocr_version=self._recognizer.engine_version,
                    page_count=page_count,
                    selected_pages=list(selected_pages),
                    dpi=settings.dpi,
                    pages=page_diagnostics,
                )
                return Document.model_validate_json(document.model_dump_json())
        except (ParserConfigurationError, DocumentParserError):
            raise
        except Exception as exc:
            raise DocumentParserError(f"document parsing failed: {exc}") from exc

    def _process_page(
        self,
        pdf: PdfDocument,
        *,
        document_id: str,
        page_number: int,
        settings: ParserSettings,
    ) -> tuple[
        list[PageBlock],
        str,
        list[str],
        OcrConfidenceSummary | None,
    ]:
        text_spans = pdf.extract_text_spans(page_number)
        text_length = sum(len(span.text) for span in text_spans)
        messages = list(pdf.text_diagnostics(page_number))
        if not settings.force_ocr and text_length >= settings.min_text_layer_chars:
            messages.append(
                "text layer used; mixed image regions are not independently detected in Task 1.1"
            )
            messages.append("text spans provisionally classified as body blocks")
            fragments = [
                RecognizedFragment(
                    text=span.text,
                    bbox=span.bbox,
                    source_index=span.source_index,
                    extraction_method="pymupdf_text_layer",
                )
                for span in text_spans
            ]
            blocks = build_provisional_blocks(document_id, page_number, fragments)
            if self._page_observer is not None:
                raster = pdf.rasterize(page_number, settings.dpi, settings.max_page_pixels)
                self._page_observer.observe(raster, blocks)
            return blocks, "text_layer", messages, None

        if text_spans:
            messages.append("sparse text layer replaced by full-page OCR")
        raster = pdf.rasterize(page_number, settings.dpi, settings.max_page_pixels)
        ocr_spans = self._recognizer.recognize(raster)
        method = f"{self._recognizer.engine_name}:{self._recognizer.engine_version}"
        fragments = [
            RecognizedFragment(
                text=span.text,
                bbox=pixel_bbox_to_pdf(span.pixel_bbox, raster),
                source_index=span.source_index,
                extraction_method=method,
                confidence=span.confidence,
            )
            for span in ocr_spans
        ]
        blocks = build_provisional_blocks(document_id, page_number, fragments)
        messages.append("OCR spans provisionally classified as body blocks")
        if self._page_observer is not None:
            self._page_observer.observe(raster, blocks)
        confidence = OcrConfidenceSummary.from_values(
            [span.confidence for span in ocr_spans if span.confidence is not None]
        )
        return blocks, "ocr", messages, confidence

    def _read_source(self, reference: FileRef) -> AbstractContextManager[BinaryIO]:
        try:
            return cast(AbstractContextManager[BinaryIO], self._file_store.read(reference))
        except Exception as exc:
            raise SourceReadError(f"FileStore.read failed for {reference.file_id}: {exc}") from exc

    def _check_backend_option(self, option: str) -> None:
        accepted = {"auto", self._recognizer.engine_name}
        if self._recognizer.engine_name == "rapidocr_onnxruntime":
            accepted.add("rapidocr")
        if option not in accepted:
            raise ParserConfigurationError(
                f"configured OCR backend {option!r} does not match injected "
                f"{self._recognizer.engine_name!r}"
            )


def _document_id(request: ParseRequest) -> str:
    standard = request.supplied_standard
    if standard is None:  # checked by parse; keeps this helper total for type checking
        raise ParserConfigurationError("supplied_standard is required")
    identity = "|".join(
        (
            request.source_file.file_id,
            standard.standard_code,
            standard.edition or "",
            standard.revision or "",
        )
    )
    return f"doc-{uuid5(NAMESPACE_URL, identity).hex}"
