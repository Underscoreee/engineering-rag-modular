"""Private formula candidates and evidence retained outside frozen V2.4."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from engineering_rag.contracts.documents import FormulaGroup, RecognitionStatus
from engineering_rag.modules.document_parser.internal.mineru.models import MinerUBbox


class _PrivateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NumberEvidence(_PrivateModel):
    raw_text: str
    source_kind: Literal["equation_tag", "number_region", "aligned_text", "body_text"]
    normalized_number: str | None = None
    bbox: MinerUBbox | None = None
    right_of_equation: bool = False
    vertical_overlap_ratio: float | None = Field(default=None, ge=0, le=1)


class FormulaEquationCandidate(_PrivateModel):
    page_number: int = Field(ge=1)
    source_index: int = Field(ge=0)
    source_block_id: str = Field(min_length=1)
    formula_id: str = Field(min_length=1)
    raw_latex: str | None = None
    bbox: MinerUBbox
    number_evidence: list[NumberEvidence] = Field(default_factory=list)
    raw_asset_ref: str | None = None
    source_asset_path: str | None = None
    recognition_status: RecognitionStatus
    diagnostics: list[str] = Field(default_factory=list)


class SymbolEvidence(_PrivateModel):
    source_indices: list[int] = Field(min_length=1)
    raw_fragments: list[dict[str, object]] = Field(min_length=1)
    diagnostics: list[str] = Field(default_factory=list)


class FormulaPlacement(_PrivateModel):
    block_id: str = Field(min_length=1)
    formula_group_id: str = Field(min_length=1)
    anchor_source_index: int = Field(ge=0)
    source_indices: list[int] = Field(min_length=1)
    bbox: MinerUBbox
    formula_group: FormulaGroup
    recognition_status: RecognitionStatus


class FormulaSidecar(_PrivateModel):
    block_id: str = Field(min_length=1)
    formula_group_id: str = Field(min_length=1)
    page_number: int = Field(ge=1)
    source_indices: list[int] = Field(min_length=1)
    equations: list[FormulaEquationCandidate] = Field(min_length=1)
    symbol_evidence: SymbolEvidence | None = None
    grouping_basis: str
    diagnostics: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FormulaAssemblyResult:
    placements: dict[tuple[int, int], FormulaPlacement]
    consumed: set[tuple[int, int]]
    sidecars: list[FormulaSidecar]
    omitted: list[dict[str, object]]
