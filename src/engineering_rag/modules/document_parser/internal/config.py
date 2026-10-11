"""Validated private configuration for the Task 1.1 parser implementation."""

from dataclasses import dataclass

from engineering_rag.contracts.documents import ParseConfig


class ParserConfigurationError(ValueError):
    """Raised when parser options are missing, unknown, or unsafe."""


@dataclass(frozen=True, slots=True)
class ParserSettings:
    page_selection: str | None = None
    dpi: float = 200.0
    ocr_backend: str = "auto"
    on_page_error: str = "raise"
    force_ocr: bool = False
    min_text_layer_chars: int = 50
    max_pdf_bytes: int = 256 * 1024 * 1024
    max_selected_pages: int = 20
    max_page_pixels: int = 40_000_000

    @classmethod
    def from_contract(cls, config: ParseConfig | None) -> "ParserSettings":
        defaults = cls()
        options = {} if config is None else dict(config.options)
        allowed = {
            "page_selection",
            "dpi",
            "ocr_backend",
            "on_page_error",
            "force_ocr",
            "min_text_layer_chars",
            "max_pdf_bytes",
            "max_selected_pages",
            "max_page_pixels",
        }
        unknown = sorted(set(options) - allowed)
        if unknown:
            raise ParserConfigurationError(f"unknown parser options: {', '.join(unknown)}")

        page_selection = _optional_string(options.get("page_selection"), "page_selection")
        dpi = _number(options.get("dpi", defaults.dpi), "dpi")
        if not 72 <= dpi <= 400:
            raise ParserConfigurationError("dpi must be between 72 and 400")
        ocr_backend = _string(options.get("ocr_backend", defaults.ocr_backend), "ocr_backend")
        on_page_error = _string(
            options.get("on_page_error", defaults.on_page_error), "on_page_error"
        )
        if on_page_error not in {"raise", "continue"}:
            raise ParserConfigurationError("on_page_error must be 'raise' or 'continue'")
        force_ocr = _boolean(options.get("force_ocr", defaults.force_ocr), "force_ocr")
        return cls(
            page_selection=page_selection,
            dpi=dpi,
            ocr_backend=ocr_backend,
            on_page_error=on_page_error,
            force_ocr=force_ocr,
            min_text_layer_chars=_positive_int(
                options.get("min_text_layer_chars", defaults.min_text_layer_chars),
                "min_text_layer_chars",
            ),
            max_pdf_bytes=_positive_int(
                options.get("max_pdf_bytes", defaults.max_pdf_bytes), "max_pdf_bytes"
            ),
            max_selected_pages=_positive_int(
                options.get("max_selected_pages", defaults.max_selected_pages),
                "max_selected_pages",
            ),
            max_page_pixels=_positive_int(
                options.get("max_page_pixels", defaults.max_page_pixels), "max_page_pixels"
            ),
        )

    def resolve_pages(self, page_count: int) -> tuple[int, ...]:
        if self.page_selection is None or self.page_selection.lower() == "all":
            selected = tuple(range(1, page_count + 1))
        else:
            pages: set[int] = set()
            for item in self.page_selection.split(","):
                token = item.strip()
                if not token:
                    raise ParserConfigurationError("page_selection contains an empty item")
                if "-" in token:
                    start_text, end_text = token.split("-", maxsplit=1)
                    try:
                        start, end = int(start_text), int(end_text)
                    except ValueError as exc:
                        raise ParserConfigurationError(f"invalid page range: {token}") from exc
                    if start < 1 or end < start:
                        raise ParserConfigurationError(f"invalid page range: {token}")
                    pages.update(range(start, end + 1))
                else:
                    try:
                        page = int(token)
                    except ValueError as exc:
                        raise ParserConfigurationError(f"invalid page number: {token}") from exc
                    if page < 1:
                        raise ParserConfigurationError("page numbers are 1-based")
                    pages.add(page)
            selected = tuple(sorted(pages))
        if not selected:
            raise ParserConfigurationError("at least one page must be selected")
        if selected[-1] > page_count:
            raise ParserConfigurationError(
                f"selected page {selected[-1]} exceeds PDF page count {page_count}"
            )
        if len(selected) > self.max_selected_pages:
            raise ParserConfigurationError(
                f"selected {len(selected)} pages; limit is {self.max_selected_pages}"
            )
        return selected


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ParserConfigurationError(f"{name} must be a non-empty string")
    return value.strip()


def _optional_string(value: object, name: str) -> str | None:
    if value is None:
        return None
    return _string(value, name)


def _number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParserConfigurationError(f"{name} must be numeric")
    return float(value)


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ParserConfigurationError(f"{name} must be a positive integer")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise ParserConfigurationError(f"{name} must be boolean")
    return value
