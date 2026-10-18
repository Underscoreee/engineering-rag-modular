"""Hybrid retrieval internal error vocabulary."""


class HybridRetrievalError(RuntimeError):
    """Base error for hybrid orchestration and fusion failures."""


class CandidateConflictError(HybridRetrievalError):
    """The same physical Chunk was returned with conflicting identity data."""


class CandidateResultError(HybridRetrievalError):
    """A dependency returned a result that violates its public contract semantics."""


class FusionParameterError(HybridRetrievalError, ValueError):
    """Fusion parameters or source scores are invalid."""
