"""Generation-only settings and model output; no replacement public DTOs."""

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from engineering_rag.contracts.answers import GroundingStatus
from engineering_rag.contracts.common import NonEmptyStr
from engineering_rag.contracts.llm import StructuredLLMConfig

PositiveInt = Annotated[int, Field(gt=0, strict=True)]


class GenerationSettings(BaseModel):
    """Application budgets, not another vendor/credential configuration system."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    llm: StructuredLLMConfig
    provider: NonEmptyStr
    max_context_chars: PositiveInt = 48000
    max_answer_chars: PositiveInt = 12000
    max_history_chars: Annotated[int, Field(ge=0, strict=True)] = 4000
    max_history_turns: Annotated[int, Field(ge=0, strict=True)] = 8
    max_attempts: Annotated[int, Field(ge=1, le=2, strict=True)] = 2


class GenerationOutput(BaseModel):
    """The model proposes evidence IDs, never source identities or quotations."""

    model_config = ConfigDict(extra="forbid")

    answer: NonEmptyStr
    evidence_ids: list[NonEmptyStr] = Field(max_length=256)
    grounding_status: GroundingStatus
    limitations: list[NonEmptyStr] = Field(max_length=16)

    @field_validator("answer")
    @classmethod
    def answer_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("answer cannot be blank")
        return value


class GenerationError(RuntimeError):
    """Sanitized failure; underlying provider errors are never rendered as answers."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Generation failed ({code})")
