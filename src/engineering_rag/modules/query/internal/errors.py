"""One internal exception with stable stage-specific codes and private audit data."""

from typing import Literal

from engineering_rag.contracts.catalog import StandardMetadataMatch

from .models import CandidateDecision, ModelAttempt

ErrorCode = Literal[
    "input_budget",
    "invalid_output",
    "invalid_evidence",
    "model_failure",
    "unmatched_scope",
    "ambiguous_scope",
    "catalog_unavailable",
    "scope_conflict",
]


class UnderstandingError(RuntimeError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.decisions: tuple[CandidateDecision, ...] = ()
        self.attempts: tuple[ModelAttempt, ...] = ()
        self.catalog_matches: tuple[StandardMetadataMatch, ...] = ()
