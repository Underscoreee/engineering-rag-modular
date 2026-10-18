"""Strict private Rewrite types. No public Query/LLM contracts are changed."""

from typing import Annotated, Literal

from pydantic import Field

from engineering_rag.contracts.common import TraceContext
from engineering_rag.contracts.llm import LLMTokenUsage, StructuredLLMConfig
from engineering_rag.contracts.queries import ProcessingIntent
from engineering_rag.contracts.retrieval import SearchFilters

from .models import PrivateModel, Text

PositiveInt = Annotated[int, Field(gt=0)]


class LanguageRule(PrivateModel):
    """Caller-reviewed local wording replacement, not a model-authored semantic claim."""

    source: Text
    target: Annotated[str, Field(max_length=256)]
    evidence_id: Text
    position: Literal["anywhere", "prefix", "suffix"] = "anywhere"


class EquivalentTerm(PrivateModel):
    """A caller-trusted equivalence assertion, including its review/reference identity."""

    term: Text
    equivalent: Text
    evidence_id: Text


def default_language_rules() -> list[LanguageRule]:
    pairs = [
        ("到底咋确定", "如何确定"),
        ("到底怎么确定", "如何确定"),
        ("咋确定", "如何确定"),
        ("怎么确定", "如何确定"),
        ("咋计算", "如何计算"),
        ("怎么计算", "如何计算"),
        ("咋算", "如何计算"),
        ("啥意思", "含义是什么"),
        ("是啥", "是什么"),
        ("具休", "具体"),
    ]
    rules = [
        LanguageRule(source=old, target=new, evidence_id="builtin-wording-v1") for old, new in pairs
    ]
    rules.extend(
        [
            LanguageRule(
                source="请间", target="请问", position="prefix", evidence_id="builtin-wording-v1"
            ),
            LanguageRule(
                source="请问", target="", position="prefix", evidence_id="builtin-wording-v1"
            ),
            LanguageRule(
                source="麻烦问一下", target="", position="prefix", evidence_id="builtin-wording-v1"
            ),
            LanguageRule(
                source="?", target="？", position="suffix", evidence_id="builtin-wording-v1"
            ),
        ]
    )
    return rules


class RewriteConfig(PrivateModel):
    llm: StructuredLLMConfig
    max_question_chars: PositiveInt = 8000
    max_history_turns: PositiveInt = 8
    max_history_chars: PositiveInt = 16000
    max_rewritten_chars: PositiveInt = 8000
    max_keyword_synonyms: Annotated[int, Field(ge=0, le=8)] = 4
    max_synonym_chars: PositiveInt = 64
    max_alignment_states: PositiveInt = 50000
    max_attempts: Annotated[int, Field(ge=1, le=2)] = 2
    language_rules: list[LanguageRule] = Field(
        default_factory=default_language_rules, max_length=64
    )
    equivalent_terms: list[EquivalentTerm] = Field(default_factory=list, max_length=128)


class RewriteOutput(PrivateModel):
    rewritten_query: Annotated[str, Field(min_length=1, max_length=16000, pattern=r"\S")]
    # Blank/duplicate/unverified candidates are reviewed and dropped, not returned as synonyms.
    keyword_synonyms: list[Annotated[str, Field(max_length=256)]] = Field(max_length=16)


class ProtectedSpan(PrivateModel):
    kind: Literal["standard", "locator", "number", "quantity", "symbol", "logic", "title", "scope"]
    value: str
    start: int
    end: int


class AppliedLanguageRule(PrivateModel):
    start: int
    end: int
    replacement: str
    evidence_id: str


class SynonymDecision(PrivateModel):
    candidate: str
    adopted: bool
    reason: str
    evidence_id: str | None = None


RewriteFailureCode = Literal[
    "input_budget",
    "scope_conflict",
    "invalid_output",
    "unsafe_rewrite",
    "model_failure",
]


class RewriteAttempt(PrivateModel):
    request_id: str
    status: Literal["success", "invalid_output", "unsafe_rewrite", "model_failure"]
    elapsed_seconds: float
    usage: LLMTokenUsage | None = None


class RewriteResult(PrivateModel):
    original_question: str
    rewritten_query: str
    keyword_synonyms: list[str]
    processing_intent: ProcessingIntent
    filters: SearchFilters
    protected_spans: list[ProtectedSpan]
    applied_rules: list[AppliedLanguageRule]
    synonym_decisions: list[SynonymDecision]
    attempts: list[RewriteAttempt]
    trace: TraceContext | None = None
    prompt_version: str
    policy_fingerprint: str
    model_config_id: str
    model_id: str
    model_revision: str | None


class RewriteError(RuntimeError):
    def __init__(self, code: RewriteFailureCode, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.attempts: tuple[RewriteAttempt, ...] = ()
