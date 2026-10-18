"""Budgets and caller-controlled dependency scope, without secrets or SDK settings."""

from typing import Annotated

from pydantic import Field

from engineering_rag.contracts.catalog import CatalogIndexScope
from engineering_rag.contracts.llm import StructuredLLMConfig

from .models import PrivateModel

PositiveInt = Annotated[int, Field(gt=0)]


class UnderstandingConfig(PrivateModel):
    llm: StructuredLLMConfig
    scope: CatalogIndexScope
    max_question_chars: PositiveInt = 8000
    max_history_turns: PositiveInt = 8
    max_history_chars: PositiveInt = 16000
    max_filter_values: PositiveInt = 32
    max_catalog_lookups: PositiveInt = 128
    max_attempts: Annotated[int, Field(ge=1, le=2)] = 2
    allow_test_catalog: bool = False
