"""Stable generation API exports."""

from engineering_rag.contracts.answers import AnswerResult, GenerationRequest
from engineering_rag.contracts.protocols import GenerationService, StructuredLLMClient

from .internal.models import GenerationError, GenerationSettings
from .internal.service import DefaultGenerationService


def create_generation_service(
    *, llm: StructuredLLMClient, settings: GenerationSettings
) -> DefaultGenerationService:
    """Inject an existing client/config; never create SDKs or connect at import."""
    return DefaultGenerationService(llm=llm, settings=settings)


__all__ = [
    "AnswerResult",
    "DefaultGenerationService",
    "GenerationError",
    "GenerationRequest",
    "GenerationService",
    "GenerationSettings",
    "create_generation_service",
]
