"""Strict private models derived from observed MinerU 4.0 MiddleJson output."""

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _PrivateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MinerUBbox(_PrivateModel):
    x_min: float = Field(ge=0, le=1)
    y_min: float = Field(ge=0, le=1)
    x_max: float = Field(gt=0, le=1)
    y_max: float = Field(gt=0, le=1)
    coordinate_space: str = "normalized_top_left"

    @model_validator(mode="after")
    def check_order(self) -> "MinerUBbox":
        if self.x_max <= self.x_min or self.y_max <= self.y_min:
            raise ValueError("MinerU bbox must have positive area")
        return self


class MinerUElement(_PrivateModel):
    page_number: int = Field(ge=1)
    page_idx: int = Field(ge=0)
    source_index: int = Field(ge=0)
    raw_type: str = Field(min_length=1)
    bbox: MinerUBbox | None = None
    text: str | None = None
    latex: str | None = None
    table_html: str | None = None
    table_caption: str | None = None
    table_footnotes: list[str] = Field(default_factory=list)
    raw: dict[str, object]
    diagnostics: list[str] = Field(default_factory=list)


class MinerUPage(_PrivateModel):
    page_number: int = Field(ge=1)
    page_idx: int = Field(ge=0)
    width_points: float = Field(gt=0)
    height_points: float = Field(gt=0)
    elements: list[MinerUElement] = Field(default_factory=list)


class MinerUParseRequest(_PrivateModel):
    source_pdf: Path
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    original_pages: list[int] = Field(min_length=1)
    source_pages: list[int] | None = None
    output_dir: Path
    timeout_seconds: int = Field(default=900, ge=1, le=7200)
    tier: str = "basic"
    ocr_mode: str = "ocr"

    @model_validator(mode="after")
    def check_pages_and_mode(self) -> "MinerUParseRequest":
        if self.original_pages != sorted(set(self.original_pages)):
            raise ValueError("original_pages must be unique and ascending")
        if self.source_pages is not None:
            if self.source_pages != sorted(set(self.source_pages)):
                raise ValueError("source_pages must be unique and ascending")
            if len(self.source_pages) != len(self.original_pages):
                raise ValueError("source_pages and original_pages must have equal length")
        if self.tier not in {"basic", "standard", "advanced"}:
            raise ValueError("scanned PDF requires a model-backed MinerU tier")
        if self.ocr_mode != "ocr":
            raise ValueError("Task 1.2 scanned PDF requests require ocr mode")
        return self


class MinerUParseResult(_PrivateModel):
    schema_id: str
    schema_version: str
    producer_version: str
    tier: str
    parse_mode: str
    source_sha256: str
    pages: list[MinerUPage]
    raw_middle_json: Path
    stdout_log: Path
    stderr_log: Path
    elapsed_seconds: float = Field(ge=0)
    raw_artifacts: list[Path] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)
