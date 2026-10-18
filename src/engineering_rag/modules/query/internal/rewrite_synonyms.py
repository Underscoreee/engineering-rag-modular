"""Only caller-reviewed, source-anchored equivalent terms can survive model proposals."""

import re

from .rewrite_models import RewriteConfig, SynonymDecision
from .rewrite_protection import LOCATOR, LOGIC, NUMBER, STANDARD_CODE


def _contains_term(text: str, term: str) -> bool:
    # Do not infer a Latin abbreviation from a substring inside another identifier.
    prefix = r"(?<![A-Za-z0-9_])" if term[0].isascii() and term[0].isalnum() else ""
    suffix = r"(?![A-Za-z0-9_])" if term[-1].isascii() and term[-1].isalnum() else ""
    return re.search(prefix + re.escape(term) + suffix, text) is not None


def review_synonyms(
    candidates: list[str], original: str, rewritten: str, config: RewriteConfig
) -> tuple[list[str], list[SynonymDecision]]:
    accepted: list[str] = []
    decisions: list[SynonymDecision] = []
    for raw in candidates:
        term = raw.strip()
        reason = "unverified_equivalence"
        record = next(
            (
                entry
                for entry in config.equivalent_terms
                if entry.equivalent == term and _contains_term(original, entry.term)
            ),
            None,
        )
        if not term or len(term) > config.max_synonym_chars:
            reason = "blank_or_over_budget"
        elif term in accepted or term in rewritten:
            reason = "duplicate_or_already_present"
        elif any(
            re.search(pattern, term) for pattern in (STANDARD_CODE, LOCATOR, NUMBER, LOGIC)
        ) or re.search(r"[，。？！；、\n\r:=<>≤≥]", term):
            reason = "identifier_answer_or_constraint_not_a_synonym"
        elif len(accepted) >= config.max_keyword_synonyms:
            reason = "synonym_count_budget"
        elif record is not None:
            accepted.append(term)
            reason = "reviewed_source_anchored_equivalence"
        decisions.append(
            SynonymDecision(
                candidate=raw,
                adopted=reason == "reviewed_source_anchored_equivalence",
                reason=reason,
                evidence_id=record.evidence_id if record else None,
            )
        )
    return accepted, decisions
