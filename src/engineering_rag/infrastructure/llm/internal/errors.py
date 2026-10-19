"""Safe categories only: provider error bodies and raw exceptions are not copied."""


class LLMError(RuntimeError):
    """Sanitized adapter failure; ``code`` is suitable for structured reports."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or f"LLM request failed ({code})")


class LLMTimeoutError(LLMError, TimeoutError):
    """Preserves the public Query stages' existing bounded timeout retry policy."""


class LLMConnectionError(LLMError, ConnectionError):
    """Preserves the public Query stages' existing bounded connection retry policy."""


class LLMOutputError(LLMError, ValueError):
    """Malformed output may consume the caller's bounded correction budget."""
