"""Existing Evaluation Protocol plus a read-only Query/retrieval evaluation adapter."""

from engineering_rag.contracts.evaluation import EvaluationReport, EvaluationRequest
from engineering_rag.contracts.protocols import EvaluationService

from .internal.dataset import DatasetValidationError, load_dataset
from .internal.run_models import EvaluationRuntime, IndexSnapshot
from .internal.service import QueryPipelineEvaluator


def create_evaluation_service(
    *, runtime: EvaluationRuntime | None = None
) -> QueryPipelineEvaluator:
    """Inject public dependencies; no backend connections at import or construction."""
    return QueryPipelineEvaluator(runtime=runtime)


__all__ = [
    "DatasetValidationError",
    "EvaluationReport",
    "EvaluationRequest",
    "EvaluationRuntime",
    "EvaluationService",
    "IndexSnapshot",
    "QueryPipelineEvaluator",
    "create_evaluation_service",
    "load_dataset",
]
