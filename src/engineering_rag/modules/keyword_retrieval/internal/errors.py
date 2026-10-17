"""Keyword retrieval implementation errors.

These exceptions describe infrastructure failures without changing the frozen public
Pydantic contracts. They deliberately retain the original exception as ``__cause__``.
"""


class KeywordRetrievalError(RuntimeError):
    """Base error raised by the Elasticsearch implementation."""


class KeywordRequestError(KeywordRetrievalError, ValueError):
    """The request is valid at contract level but unsupported by this implementation."""


class KeywordConfigurationError(KeywordRetrievalError, ValueError):
    """Required Elasticsearch configuration is absent or invalid."""


class KeywordDependencyError(KeywordRetrievalError):
    """The optional official Elasticsearch client is not installed."""


class KeywordIndexNotFoundError(KeywordRetrievalError):
    """The requested Elasticsearch index does not exist."""


class KeywordIndexCompatibilityError(KeywordRetrievalError):
    """An existing index does not use this module's compatible mapping."""


class KeywordIndexCreationError(KeywordRetrievalError):
    """Elasticsearch rejected index creation."""


class KeywordConnectionError(KeywordRetrievalError):
    """The Elasticsearch service could not be reached."""


class KeywordTimeoutError(KeywordRetrievalError):
    """An Elasticsearch operation timed out."""


class KeywordBackendError(KeywordRetrievalError):
    """Elasticsearch rejected an indexing, query, or delete operation."""


class KeywordResponseError(KeywordRetrievalError):
    """Elasticsearch returned a response that cannot satisfy the public contract."""
