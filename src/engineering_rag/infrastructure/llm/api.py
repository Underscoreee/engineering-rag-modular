"""Public infrastructure exports; importing this module never calls a provider."""

from engineering_rag.contracts.llm import (
    StructuredLLMConfig,
    StructuredLLMRequest,
    StructuredLLMResponse,
)
from engineering_rag.contracts.protocols import StructuredLLMClient

from .config import LLMSettings
from .internal.adapter import OpenAICompatibleLLMClient
from .internal.errors import LLMConnectionError, LLMError, LLMOutputError, LLMTimeoutError
from .internal.transport import HTTPResponse, HTTPTransport

__all__ = [
    "HTTPResponse",
    "HTTPTransport",
    "LLMConnectionError",
    "LLMError",
    "LLMOutputError",
    "LLMSettings",
    "LLMTimeoutError",
    "OpenAICompatibleLLMClient",
    "StructuredLLMClient",
    "StructuredLLMConfig",
    "StructuredLLMRequest",
    "StructuredLLMResponse",
]
