"""Offline structured LLM boundary tests; no real model or SDK is involved."""

from typing import Literal

import pytest
from pydantic import BaseModel, ValidationError

from engineering_rag.contracts.common import ContractModel
from engineering_rag.contracts.llm import (
    LLMTokenUsage,
    StructuredLLMConfig,
    StructuredLLMRequest,
    StructuredLLMResponse,
)
from engineering_rag.contracts.protocols import StructuredLLMClient


class FixtureOutput(ContractModel):
    label: Literal["fixture"]
    count: int


def request() -> StructuredLLMRequest:
    return StructuredLLMRequest(
        request_id="fixture-llm-1",
        stage="contract-test",
        input={"text": "虚构测试输入"},
        output_schema=FixtureOutput.model_json_schema(),
        config=StructuredLLMConfig(
            config_id="fixture-config",
            model_id="fixture-model",
            model_revision="fixture-revision",
            timeout_seconds=3,
            max_output_tokens=32,
        ),
    )


class FakeStructuredLLM:
    """Test fixture only; returns declared transport data, not business inference."""

    def generate(self, request: StructuredLLMRequest) -> StructuredLLMResponse:
        return StructuredLLMResponse(
            request_id=request.request_id,
            model_id=request.config.model_id,
            model_revision=request.config.model_revision,
            data={"label": "fixture", "count": 2},
        )


def test_fake_satisfies_protocol_and_validated_output_round_trips() -> None:
    client: StructuredLLMClient = FakeStructuredLLM()
    assert isinstance(client, StructuredLLMClient)
    req = request()
    response = client.generate(req)
    assert response.validate_output(req, FixtureOutput) == FixtureOutput(label="fixture", count=2)
    assert StructuredLLMRequest.model_validate_json(req.model_dump_json()) == req
    assert StructuredLLMResponse.model_validate_json(response.model_dump_json()) == response
    assert response.usage is None
    assert response.provider_request_id is None


@pytest.mark.parametrize(
    "data",
    [
        {"label": "invalid", "count": 2},
        {"label": "fixture", "count": "2"},
        {"label": "fixture", "count": 2, "extra": True},
        {"label": "fixture"},
    ],
)
def test_transport_payload_must_be_validated_before_business_use(data: dict[str, object]) -> None:
    req = request()
    response = FakeStructuredLLM().generate(req)
    response.data = data  # type: ignore[assignment]
    with pytest.raises(ValidationError):
        response.validate_output(req, FixtureOutput)


@pytest.mark.parametrize("field", ["request_id", "model_id", "model_revision"])
def test_response_must_belong_to_request_and_model(field: str) -> None:
    req = request()
    response = FakeStructuredLLM().generate(req)
    setattr(response, field, "wrong")
    with pytest.raises(ValueError, match=field):
        response.validate_output(req, FixtureOutput)


def test_schema_substitution_and_permissive_output_model_are_rejected() -> None:
    req = request()
    response = FakeStructuredLLM().generate(req)
    req.output_schema = {"type": "object"}
    with pytest.raises(ValueError, match="output model"):
        response.validate_output(req, FixtureOutput)

    class PermissiveOutput(BaseModel):
        label: str
        count: int

    req.output_schema = PermissiveOutput.model_json_schema()
    with pytest.raises(ValueError, match="forbid extra"):
        response.validate_output(req, PermissiveOutput)


def test_usage_unknown_zero_partial_and_invalid_counts() -> None:
    assert LLMTokenUsage().total_tokens is None
    assert LLMTokenUsage(input_tokens=0, output_tokens=0, total_tokens=0).total_tokens == 0
    assert LLMTokenUsage(input_tokens=4).output_tokens is None
    with pytest.raises(ValidationError, match="total_tokens"):
        LLMTokenUsage(input_tokens=2, output_tokens=3, total_tokens=4)
    for value in (-1, True, 1.5):
        with pytest.raises(ValidationError):
            LLMTokenUsage(input_tokens=value)


@pytest.mark.parametrize(
    "changes",
    [
        {"timeout_seconds": 0},
        {"timeout_seconds": float("inf")},
        {"max_output_tokens": 0},
        {"max_output_tokens": True},
        {"temperature": float("nan")},
        {"api_key": "not-a-real-key"},
    ],
)
def test_config_rejects_invalid_budgets_and_vendor_fields(changes: dict[str, object]) -> None:
    data = request().config.model_dump(mode="json")
    with pytest.raises(ValidationError):
        StructuredLLMConfig.model_validate({**data, **changes})


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_non_finite_json_is_rejected_instead_of_serialized_as_null(value: float) -> None:
    req = request()
    with pytest.raises(ValidationError):
        StructuredLLMRequest.model_validate(
            {**req.model_dump(mode="python"), "input": {"nested": [value]}}
        )
    with pytest.raises(ValidationError):
        StructuredLLMResponse(request_id="r", model_id="m", data={"nested": [value]})


def test_mutated_transport_data_is_revalidated() -> None:
    req = request()
    response = FakeStructuredLLM().generate(req)
    response.data["invalid"] = float("nan")
    with pytest.raises(ValidationError):
        response.validate_output(req, FixtureOutput)
