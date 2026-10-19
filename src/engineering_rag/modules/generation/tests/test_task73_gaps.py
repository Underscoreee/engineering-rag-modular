"""Task 7.3 adds only missing input/output boundary cases; entirely offline."""

import pytest

from engineering_rag.modules.generation.api import GenerationError, create_generation_service
from engineering_rag.modules.generation.internal.context import ContextBuilder

from .helpers import FakeLLM, evidence, request, settings


def test_blank_standard_code_fails_context_before_a_paid_model_call():
    item = evidence()
    item.standard.standard_code = "  "
    value = request(evidence=[item])
    with pytest.raises(GenerationError, match="invalid_evidence"):
        ContextBuilder(settings()).build(value)
    llm = FakeLLM()
    with pytest.raises(GenerationError, match="invalid_evidence"):
        create_generation_service(llm=llm, settings=settings()).generate(value)
    assert llm.requests == []
