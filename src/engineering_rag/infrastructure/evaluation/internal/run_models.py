"""Local experiment configuration carried by the existing EvaluationRequest.config."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engineering_rag.contracts.common import Sha256
from engineering_rag.contracts.protocols import (
    HybridRetrievalService,
    QueryService,
    StructuredLLMClient,
)
from engineering_rag.contracts.retrieval import FusionStrategy, HybridSearchRequest

Variant = Literal["raw", "rewrite", "rewrite_expansion", "rewrite_hyde", "full"]
VARIANTS = ("raw", "rewrite", "rewrite_expansion", "rewrite_hyde", "full")
Mode = Literal["validate_only", "offline_test", "retrieval_eval", "llm_e2e_eval"]
Text = Annotated[str, Field(min_length=1, pattern=r"\S")]


class LocalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RunConfig(LocalModel):
    mode: Mode = "validate_only"
    variants: list[Variant] = Field(default_factory=lambda: list(VARIANTS))
    ks: list[Annotated[int, Field(gt=0)]] = Field(default_factory=lambda: [5, 10, 20])
    relevance_threshold: Annotated[int, Field(ge=1, le=3)] = 2
    corpus_path: Path
    corpus_snapshot_id: Text
    output_dir: Path
    run_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")]
    snapshot_manifest: Path | None = None
    require_verified: bool = False
    keyword_index: Text | None = None
    vector_collection: Text | None = None
    embedding_model_id: Text | None = None
    candidate_k: Annotated[int, Field(gt=0)] = 50
    fusion_strategy: FusionStrategy = FusionStrategy.RECIPROCAL_RANK_FUSION
    keyword_weight: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.5
    vector_weight: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.5
    code_revision: str | None = None

    @model_validator(mode="after")
    def check_budgets(self) -> RunConfig:
        if not self.ks or len(set(self.ks)) != len(self.ks):
            raise ValueError("K must be nonempty, positive and unique")
        if not self.variants or len(set(self.variants)) != len(self.variants):
            raise ValueError("variants must be nonempty and unique")
        if max(self.ks) > self.candidate_k:
            raise ValueError("max(K) must not exceed shared candidate_k")
        # Reuse the frozen public fusion validation instead of introducing a new policy.
        HybridSearchRequest.model_validate(
            {
                "keyword": {"query": "budget validation", "index_name": "validation"},
                "vector": {"query": "budget validation", "index_name": "validation"},
                "fusion_strategy": self.fusion_strategy,
                "keyword_weight": self.keyword_weight,
                "vector_weight": self.vector_weight,
                "candidate_k": self.candidate_k,
                "top_k": max(self.ks),
            }
        )
        return self

    @classmethod
    def from_options(cls, options: dict[str, str | int | float | bool]) -> RunConfig:
        import json

        payload = dict(options)
        for key in ("ks", "variants"):
            if key in payload:
                value = payload[key]
                if not isinstance(value, str):
                    raise ValueError(
                        f"{key} must be a comma-separated string in EvaluationRequest.config"
                    )
                parts = value.split(",")
                payload[key] = [int(item) for item in parts] if key == "ks" else parts
        return cls.model_validate_json(json.dumps(payload, allow_nan=False))


class IndexSnapshot(LocalModel):
    """Trusted inventory proof, additionally checked by an injected live verifier.

    A filename/index alias alone is NOT a snapshot. No arbitrary bool in a dataset
    can replace the runtime's read-only check of the actual indexed inventories.
    """

    schema_version: Literal["1.0"] = "1.0"
    snapshot_id: Text
    corpus_snapshot_id: Text
    corpus_sha256: Sha256
    chunking_version: Text
    keyword_index: Text
    vector_collection: Text
    keyword_index_version: Text
    vector_collection_version: Text
    chunk_ids_sha256: Sha256
    document_ids: list[Text] = Field(min_length=1)
    embedding_model_id: Text
    encoding_policy_id: Text
    verified_at: datetime
    verification_evidence: Text

    @model_validator(mode="after")
    def check_time(self) -> IndexSnapshot:
        if self.verified_at.utcoffset() is None:
            raise ValueError("index verification time must be timezone-aware")
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("snapshot document identities must be unique")
        return self

    def identity(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"verified_at", "verification_evidence"})


QueryFactory = Callable[[Variant, StructuredLLMClient, HybridRetrievalService], QueryService]
SnapshotVerifier = Callable[[IndexSnapshot], IndexSnapshot]


@dataclass(frozen=True)
class EvaluationRuntime:
    """Composition-root dependencies, never automatically created by the evaluator.

    Dependency provenance is a trusted operator/adapter declaration, not a way to
    authenticate arbitrary Python code. Real modes also require a live inventory
    verifier. No credentials belong in metadata.
    """

    backend_kind: Literal["offline", "real"]
    hybrid_service: HybridRetrievalService
    query_factory: QueryFactory | None = None
    llm: StructuredLLMClient | None = None
    llm_kind: Literal["offline", "real", "not_configured"] = "not_configured"
    verify_snapshot: SnapshotVerifier | None = None
    metadata: dict[str, str] = field(default_factory=dict)


class EvaluationSafetyError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
