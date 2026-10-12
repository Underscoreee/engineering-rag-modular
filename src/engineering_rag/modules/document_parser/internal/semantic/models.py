"""Strict private models for Section/Clause reconstruction evidence."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict, Field

from engineering_rag.contracts.documents import Document


class _PrivateModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SemanticSourceEvidence(_PrivateModel):
    source_pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    physical_page: int = Field(ge=1)
    source_block_id: str = Field(min_length=1)
    source_index: int | None = Field(default=None, ge=0)
    span_range: tuple[int, int] | None = None
    source_bbox: dict[str, float]
    raw_text: str | None = None
    candidate_kind: str = Field(min_length=1)
    candidate_label: str | None = None
    content_group: str | None = None
    decision: str = Field(min_length=1)
    decision_reason: str = Field(min_length=1)
    consumed_by: list[str] = Field(default_factory=list)
    review_status: str = "machine_candidate_pending_human_review"


class PendingSemanticRelation(_PrivateModel):
    relation_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    candidate_target_ids: list[str] = Field(default_factory=list)
    physical_pages: list[int] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    evidence_block_ids: list[str] = Field(default_factory=list)
    source_bboxes: dict[str, dict[str, float]] = Field(default_factory=dict)
    blocking_conditions: list[str] = Field(default_factory=list)


class SemanticLineage(_PrivateModel):
    algorithm_version: str
    source_pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    raw_layer_immutable: bool = True
    source_records: list[SemanticSourceEvidence] = Field(default_factory=list)
    old_new_id_map: dict[str, list[str]] = Field(default_factory=dict)
    diagnostics: list[str] = Field(default_factory=list)


class SemanticPendingLinks(_PrivateModel):
    algorithm_version: str
    relations: list[PendingSemanticRelation] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class SemanticAssemblyResult:
    document: Document
    lineage: SemanticLineage
    pending_links: SemanticPendingLinks
    statistics: dict[str, int]
