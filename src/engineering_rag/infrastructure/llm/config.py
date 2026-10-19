"""Explicit environment configuration; no .env loading or credentials at import."""

import os
from collections.abc import Mapping
from ipaddress import ip_address
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from engineering_rag.contracts.llm import StructuredLLMConfig

from .internal.errors import LLMError

MAX_TIMEOUT_SECONDS = 300.0


class LLMSettings(BaseModel):
    """Infrastructure-only settings, not a replacement public generation contract."""

    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    provider: Literal["deepseek", "openai_compatible"]
    base_url: str
    api_key: SecretStr = Field(repr=False)
    model_id: Annotated[str, Field(min_length=1, max_length=256)]
    model_revision: Annotated[str, Field(min_length=1, max_length=256)] | None = None
    timeout_seconds: Annotated[float, Field(gt=0, le=MAX_TIMEOUT_SECONDS, allow_inf_nan=False)] = 60
    # Passed to Query stage configuration; the transport itself NEVER retries.
    max_attempts: Annotated[int, Field(ge=1, le=2, strict=True)] = 2
    temperature: Annotated[float, Field(ge=0, le=2, allow_inf_nan=False)] = 0
    max_output_tokens: Annotated[int, Field(gt=0, strict=True)] = 4096
    response_format: Literal["json_object", "json_schema"] = "json_object"
    response_model_ids: tuple[str, ...] = ()
    token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    send_temperature: bool = True

    @field_validator("base_url")
    @classmethod
    def validate_endpoint(cls, value: str) -> str:
        if not value or any(char.isspace() or ord(char) < 32 for char in value):
            raise ValueError("base URL must be a nonblank HTTP(S) endpoint")
        parsed = urlsplit(value)
        if (
            not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or "?" in value
            or "#" in value
        ):
            raise ValueError("base URL cannot include credentials, query parameters or fragments")
        _ = parsed.port  # Validate invalid port syntax while inputs remain hidden.
        loopback = parsed.hostname.lower() == "localhost"
        try:
            loopback = loopback or ip_address(parsed.hostname).is_loopback
        except ValueError:
            loopback = loopback or False
        if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
            raise ValueError("HTTPS required except an explicitly configured loopback HTTP server")
        return value.rstrip("/")

    @field_validator("api_key")
    @classmethod
    def validate_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value()
        if not secret.strip() or any(char.isspace() or ord(char) < 32 for char in secret):
            raise ValueError(
                "API key must be nonblank and contain no whitespace/control characters"
            )
        return value

    @field_validator("model_id")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if not value.strip() or any(char.isspace() or ord(char) < 32 for char in value):
            raise ValueError("model ID must be a nonblank identity without whitespace")
        return value

    @field_validator("model_revision")
    @classmethod
    def validate_revision(cls, value: str | None) -> str | None:
        if value is not None and (
            not value.strip() or any(char.isspace() or ord(char) < 32 for char in value)
        ):
            raise ValueError("model revision must be a nonblank identity without whitespace")
        return value

    @field_validator("response_model_ids")
    @classmethod
    def validate_aliases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) != len(set(value)) or any(
            not item or len(item) > 256 or any(char.isspace() or ord(char) < 32 for char in item)
            for item in value
        ):
            raise ValueError("response model allowlist must contain unique nonblank IDs")
        return value

    @model_validator(mode="after")
    def validate_provider_and_secret_separation(self) -> "LLMSettings":
        if self.provider == "deepseek" and self.response_format != "json_object":
            raise ValueError("DeepSeek adapter requires json_object response format")
        secret = self.api_key.get_secret_value()
        plain_fields = (self.model_id, self.base_url, *self.response_model_ids)
        if self.model_revision is not None:
            plain_fields += (self.model_revision,)
        if any(secret in value for value in plain_fields):
            raise ValueError("API key cannot appear in non-secret configuration fields")
        return self

    def structured_config(self, config_id: str) -> StructuredLLMConfig:
        """Credentials and HTTP options never enter the public request contract."""
        return StructuredLLMConfig(
            config_id=config_id,
            model_id=self.model_id,
            model_revision=self.model_revision,
            timeout_seconds=self.timeout_seconds,
            temperature=self.temperature,
            max_output_tokens=self.max_output_tokens,
        )

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "LLMSettings":
        env = os.environ if environ is None else environ
        required = {
            "provider": "ERAG_LLM_PROVIDER",
            "base_url": "ERAG_LLM_BASE_URL",
            "api_key": "ERAG_LLM_API_KEY",
            "model_id": "ERAG_LLM_MODEL",
        }
        missing = [name for name in required.values() if not env.get(name, "").strip()]
        if missing:
            raise LLMError(
                "configuration_missing", "missing LLM environment variables: " + ", ".join(missing)
            )
        values: dict[str, object] = {field: env[name] for field, name in required.items()}
        converters = {
            "timeout_seconds": ("ERAG_LLM_TIMEOUT_SECONDS", float),
            "max_attempts": ("ERAG_LLM_MAX_ATTEMPTS", int),
            "temperature": ("ERAG_LLM_TEMPERATURE", float),
            "max_output_tokens": ("ERAG_LLM_MAX_OUTPUT_TOKENS", int),
            "response_format": ("ERAG_LLM_RESPONSE_FORMAT", str),
            "token_parameter": ("ERAG_LLM_TOKEN_PARAMETER", str),
        }
        try:
            for field, (name, convert) in converters.items():
                if name in env:
                    values[field] = convert(env[name])
            if "ERAG_LLM_MODEL_REVISION" in env:
                values["model_revision"] = env["ERAG_LLM_MODEL_REVISION"].strip() or None
            if "ERAG_LLM_RESPONSE_MODEL_IDS" in env:
                aliases = env["ERAG_LLM_RESPONSE_MODEL_IDS"].strip()
                values["response_model_ids"] = (
                    tuple(item.strip() for item in aliases.split(",")) if aliases else ()
                )
            if "ERAG_LLM_SEND_TEMPERATURE" in env:
                option = env["ERAG_LLM_SEND_TEMPERATURE"].strip().lower()
                if option not in {"true", "false"}:
                    raise ValueError("boolean configuration must be true or false")
                values["send_temperature"] = option == "true"
            return cls.model_validate(values)
        except (ValueError, TypeError, ValidationError):
            raise LLMError(
                "configuration_invalid",
                "invalid LLM environment configuration; check ERAG_LLM_* values",
            ) from None
