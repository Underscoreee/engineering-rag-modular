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


class SymbolSourceCoverage(_PrivateModel):
    source_index: int = Field(ge=0)
    item_indices: list[int] = Field(default_factory=list)
    fully_consumed: bool
    unconsumed_text: str | None = None
    reason: str


class SymbolEvidence(_PrivateModel):
    source_indices: list[int] = Field(min_length=1)
    raw_fragments: list[dict[str, object]] = Field(min_length=1)
    source_coverage: list[SymbolSourceCoverage] = Field(default_factory=list)
    diagnostics: list[str] = Field(default_factory=list)


class FormulaApplicabilityLink(_PrivateModel):
    condition_id: str = Field(min_length=1)
    raw_source_block_ids: list[str] = Field(min_length=1)
    source_page_number: int = Field(ge=1)
    source_index: int = Field(ge=0)
    raw_text: str = Field(min_length=1)
    normalized_text: str = Field(min_length=1)
    bbox: MinerUBbox
    target_formula_ids: list[str] = Field(min_length=1)
    match_evidence: list[str] = Field(min_length=1)
    review_status: Literal["visual_evidence", "unverified", "unresolved"]
    diagnostics: list[str] = Field(default_factory=list)


class FormulaSemanticCoverage(_PrivateModel):
    source_block_id: str = Field(min_length=1)
    source_page_number: int = Field(ge=1)
    source_index: int = Field(ge=0)
    raw_text: str = Field(min_length=1)
    raw_bbox: MinerUBbox
    raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_formula_group_id: str = Field(min_length=1)
    target_symbol_item_indices: list[int] = Field(default_factory=list)
    matched_source_span: str = Field(min_length=1)
    consumed_text_ranges: list[tuple[int, int]] = Field(default_factory=list)
    duplicate_disposition: Literal["consumed", "dedup_unresolved", "protected_reference"]
    review_status: Literal["unverified", "needs_review"]
    cross_page_incomplete: bool = False
    reason: str = Field(min_length=1)


class FormulaSemanticComponent(_PrivateModel):
    source_id: str = Field(min_length=1)
    original_block_id: str = Field(min_length=1)
    source_page_number: int = Field(ge=1)
    source_index: int = Field(ge=0)
    raw_text: str = Field(min_length=1)
    raw_bbox: MinerUBbox
    original_status: RecognitionStatus
    consumed_text_ranges: list[tuple[int, int]] = Field(min_length=1)
    target_formula_group_id: str = Field(min_length=1)
    target_formula_id: str | None = None
    semantic_role: Literal[
        "condition",
        "equation",
        "equation_number",
        "symbol_explanation",
        "printed_note",
    ]
    component_bbox: MinerUBbox
    review_status: Literal["visual_evidence", "unverified", "needs_review"]
    corrected_from: str | None = None
    corrected_to: str | None = None
    correction_evidence: list[str] = Field(default_factory=list)
    cross_page_incomplete: bool = False
    diagnostics: list[str] = Field(default_factory=list)


class FormulaGroupLineage(_PrivateModel):
    old_block_id: str = Field(min_length=1)
    old_formula_group_id: str = Field(min_length=1)
    new_block_id: str = Field(min_length=1)
    new_formula_group_id: str = Field(min_length=1)
    formula_ids: list[str] = Field(min_length=1)


class FormulaPrintedNoteEvidence(_PrivateModel):
    source_page_number: int = Field(ge=1)
    source_index: int = Field(ge=0)
    source_block_id: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)
    raw_bbox: MinerUBbox
    target_formula_group_id: str = Field(min_length=1)
    target_formula_ids: list[str] = Field(default_factory=list)
    referenced_equation_numbers: list[str] = Field(default_factory=list)
    projection_block_id: str = Field(min_length=1)
    projection_disposition: Literal["retained_as_body"] = "retained_as_body"
    review_status: Literal["unverified", "needs_review"] = "unverified"


class FormulaBodyRelationEvidence(_PrivateModel):
    source_page_number: int = Field(ge=1)
    source_index: int = Field(ge=0)
    source_block_id: str = Field(min_length=1)
    raw_text: str = Field(min_length=1)
    raw_bbox: MinerUBbox
    target_formula_group_id: str = Field(min_length=1)
    target_formula_ids: list[str] = Field(default_factory=list)
    semantic_role: Literal["formula_leadin"]
    projection_disposition: Literal["retained_as_body"] = "retained_as_body"
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
    conditions: list[FormulaApplicabilityLink] = Field(default_factory=list)
    symbol_evidence: SymbolEvidence | None = None
    explanation_scope_formula_ids: list[str] = Field(default_factory=list)
    semantic_components: list[FormulaSemanticComponent] = Field(default_factory=list)
    printed_notes: list[FormulaPrintedNoteEvidence] = Field(default_factory=list)
    body_relations: list[FormulaBodyRelationEvidence] = Field(default_factory=list)
    lineage: list[FormulaGroupLineage] = Field(default_factory=list)
    grouping_basis: str
    diagnostics: list[str] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class FormulaAssemblyResult:
    placements: dict[tuple[int, int], FormulaPlacement]
    consumed: set[tuple[int, int]]
    consumed_body: set[tuple[int, int]]
    sidecars: list[FormulaSidecar]
    dedup_coverage: list[FormulaSemanticCoverage]
    omitted: list[dict[str, object]]
