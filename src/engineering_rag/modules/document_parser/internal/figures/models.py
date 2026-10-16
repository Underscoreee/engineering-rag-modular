"""Private figure evidence models; the frozen Document schema remains unchanged."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from engineering_rag.contracts.common import ArtifactRef
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUBbox


class _PrivateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FigureAssetEvidence(_PrivateModel):
    source_page_number: int = Field(ge=1)
    source_index: int = Field(ge=0)
    raw_reference: str = Field(min_length=1)
    resolved_path: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    size_bytes: int | None = Field(default=None, ge=0)
    bbox: MinerUBbox
    diagnostics: list[str] = Field(default_factory=list)


class FigureSourceConsumption(_PrivateModel):
    source_page_number: int = Field(ge=1)
    source_index: int = Field(ge=0)
    source_block_id: str = Field(min_length=1)
    raw_type: str = Field(min_length=1)
    raw_text: str | None = None
    raw_latex: str | None = None
    raw_bbox: MinerUBbox
    semantic_role: Literal[
        "figure_body",
        "figure_body_and_caption",
        "figure_caption",
        "figure_internal_text",
    ]
    target_block_id: str = Field(min_length=1)
    disposition: Literal["consumed_by_figure"] = "consumed_by_figure"


class FigurePlacement(_PrivateModel):
    block_id: str = Field(min_length=1)
    anchor_source_index: int = Field(ge=0)
    bbox: MinerUBbox
    caption: str = Field(min_length=1)
    figure_number: str = Field(min_length=1)
    figure_caption: str = Field(min_length=1)
    asset: ArtifactRef


class FigureSidecar(_PrivateModel):
    block_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    figure_number: str = Field(min_length=1)
    figure_caption: str = Field(min_length=1)
    full_caption: str = Field(min_length=1)
    figure_bbox: MinerUBbox
    caption_bbox: MinerUBbox | None = None
    source_consumption: list[FigureSourceConsumption] = Field(min_length=1)
    assets: list[FigureAssetEvidence] = Field(min_length=1)
    aggregation_basis: str = Field(min_length=1)
    diagnostics: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FigureAssemblyResult:
    placements: dict[tuple[int, int], FigurePlacement]
    consumed: set[tuple[int, int]]
    sidecars: list[FigureSidecar]
    omitted: list[dict[str, object]]
