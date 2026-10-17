"""Typed runtime configuration for the Elasticsearch keyword backend."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, cast

from .errors import KeywordConfigurationError

RefreshPolicy = Literal["wait_for", "true", "false"]


@dataclass(frozen=True, slots=True)
class ElasticsearchKeywordConfig:
    """Configuration kept private to the keyword retrieval implementation."""

    url: str | None = None
    api_key: str | None = None
    default_index: str = "engineering-rag-chunks-v1"
    request_timeout: float = 30.0
    analyzer: str = "standard"
    max_top_k: int = 100
    refresh: RefreshPolicy = "wait_for"

    def __post_init__(self) -> None:
        if self.url is not None and not self.url.strip():
            raise KeywordConfigurationError("Elasticsearch URL must not be blank")
        if not self.default_index.strip():
            raise KeywordConfigurationError("default_index must not be blank")
        if not self.analyzer.strip():
            raise KeywordConfigurationError("analyzer must not be blank")
        if self.request_timeout <= 0:
            raise KeywordConfigurationError("request_timeout must be greater than zero")
        if self.max_top_k <= 0:
            raise KeywordConfigurationError("max_top_k must be greater than zero")
        if self.refresh not in {"wait_for", "true", "false"}:
            raise KeywordConfigurationError("refresh must be wait_for, true, or false")

    @classmethod
    def from_env(cls) -> ElasticsearchKeywordConfig:
        """Load module configuration without connecting to Elasticsearch."""

        return cls(
            url=os.getenv("ELASTICSEARCH_URL"),
            api_key=os.getenv("ELASTICSEARCH_API_KEY"),
            default_index=os.getenv("ENGINEERING_RAG_KEYWORD_INDEX", "engineering-rag-chunks-v1"),
            request_timeout=_read_positive_float("ENGINEERING_RAG_ES_REQUEST_TIMEOUT", 30.0),
            analyzer=os.getenv("ENGINEERING_RAG_ES_ANALYZER", "standard"),
            max_top_k=_read_positive_int("ENGINEERING_RAG_KEYWORD_MAX_TOP_K", 100),
            refresh=_read_refresh_policy(),
        )


def _read_positive_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise KeywordConfigurationError(f"{name} must be a number") from exc
    if parsed <= 0:
        raise KeywordConfigurationError(f"{name} must be greater than zero")
    return parsed


def _read_positive_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise KeywordConfigurationError(f"{name} must be an integer") from exc
    if parsed <= 0:
        raise KeywordConfigurationError(f"{name} must be greater than zero")
    return parsed


def _read_refresh_policy() -> RefreshPolicy:
    value = os.getenv("ENGINEERING_RAG_ES_REFRESH", "wait_for").lower()
    if value not in {"wait_for", "true", "false"}:
        raise KeywordConfigurationError(
            "ENGINEERING_RAG_ES_REFRESH must be wait_for, true, or false"
        )
    return cast(RefreshPolicy, value)
