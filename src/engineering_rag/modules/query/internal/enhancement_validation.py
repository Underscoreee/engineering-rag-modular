"""Lossless constraint anchors and reviewed related contexts; fail closed for free prose."""

import re

from .enhancement_models import EnhancementConfig, ExpansionDecision, RelatedContext
from .enhancement_prompts import (
    EXPANSION_SEPARATOR,
    HYDE_CONTEXT_SEPARATOR,
    HYDE_FOOTER,
    HYDE_HEADER,
)
from .rewrite_protection import extract_protected_spans
from .rewrite_synonyms import _contains_term

UNSAFE_CONTEXT = re.compile(
    r"[\n\r，。！？；:=<>≤≥《》]|来源|出处|根据|本规范|规定|原文|"
    r"应当|必须|严禁|不得|不应|不宜|应(?:为|取|满足|采用|按|符合)|可取|至少|至多|不超过|"
    r"全行业|全标准|所有标准|全部标准|等价|等同|相当于|就是|仅限"
)


def validate_context_policy(contexts: list[RelatedContext]) -> None:
    for item in contexts:
        technical = extract_protected_spans(item.phrase)
        if re.search(UNSAFE_CONTEXT, item.phrase) or any(
            span.kind not in {"logic"} for span in technical
        ):
            raise ValueError(
                "reviewed retrieval context must not contain facts, identifiers or parameters"
            )
    phrases = [item.phrase for item in contexts]
    if len(phrases) != len(set(phrases)):
        raise ValueError("related context phrases must be unique")


def available_contexts(config: EnhancementConfig, primary: str) -> list[RelatedContext]:
    return [item for item in config.related_contexts if _contains_term(primary, item.anchor)]


def validate_expansions(
    candidates: list[str],
    primary: str,
    config: EnhancementConfig,
    attempt: int,
) -> tuple[list[str], list[ExpansionDecision]]:
    contexts = {item.phrase: item for item in available_contexts(config, primary)}
    accepted: list[str] = []
    seen: set[str] = set()
    decisions: list[ExpansionDecision] = []
    for index, text in enumerate(candidates):
        key = re.sub(r"\s+", " ", text.strip())
        context = (
            contexts.get(text[len(primary + EXPANSION_SEPARATOR) :])
            if text.startswith(primary + EXPANSION_SEPARATOR)
            else None
        )
        if not text.strip():
            reason = "unsafe_candidate"
        elif text == primary:
            reason = "already_primary"
        elif key in seen:
            reason = "duplicate"
        elif len(text) > config.max_expanded_query_chars:
            reason = "length_budget"
        elif context is None:
            reason = "unsafe_candidate"
        elif len(accepted) >= config.max_expansions:
            reason = "count_budget"
        else:
            reason = "accepted"
            accepted.append(text)
            seen.add(key)
        decisions.append(
            ExpansionDecision(
                index=index,
                attempt=attempt,
                adopted=reason == "accepted",
                reason=reason,
                context_id=context.evidence_id if context else None,
            )
        )
    return accepted, decisions


def validate_hypothesis(text: str, primary: str, config: EnhancementConfig) -> None:
    prefix = HYDE_HEADER + primary
    if (
        len(text) > config.max_hyde_chars
        or not text.startswith(prefix)
        or not text.endswith(HYDE_FOOTER)
    ):
        raise ValueError(
            "hypothesis is over budget or does not preserve its full constraint anchor"
        )
    body = text[len(prefix) : -len(HYDE_FOOTER)]
    if not body:
        return
    if not body.startswith(HYDE_CONTEXT_SEPARATOR):
        raise ValueError("unreviewed hypothetical prose")
    phrases = body[len(HYDE_CONTEXT_SEPARATOR) :].split(HYDE_CONTEXT_SEPARATOR)
    permitted = {item.phrase for item in available_contexts(config, primary)}
    if (
        len(phrases) > config.max_hyde_contexts
        or len(phrases) != len(set(phrases))
        or any(phrase not in permitted for phrase in phrases)
    ):
        raise ValueError("hypothesis contains unverified, duplicate or out-of-scope contexts")
