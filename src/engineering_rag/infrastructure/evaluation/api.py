"""Evaluation interface; metrics are descriptors, not implementations."""

from engineering_rag.contracts.evaluation import EvaluationReport, EvaluationRequest
from engineering_rag.contracts.protocols import EvaluationService

__all__ = ["EvaluationReport", "EvaluationRequest", "EvaluationService"]
