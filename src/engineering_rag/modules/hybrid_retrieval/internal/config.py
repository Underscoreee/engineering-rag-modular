"""Private configuration for deterministic hybrid score fusion."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import FusionParameterError


@dataclass(frozen=True, slots=True)
class HybridRetrievalConfig:
    """Hybrid-only parameters that are not represented by the public request."""

    rrf_k: int = 60

    def __post_init__(self) -> None:
        if not isinstance(self.rrf_k, int) or isinstance(self.rrf_k, bool) or self.rrf_k <= 0:
            raise FusionParameterError("rrf_k must be a positive integer")
