"""Deterministic technical protection and auditable, order-preserving local edits."""

import re
import unicodedata
from collections.abc import Sequence

from engineering_rag.contracts.queries import QueryRequest

from .errors import UnderstandingError
from .evidence import STANDARD_CODE, code_key, verify_span
from .models import StandardCandidate, UnderstandingResult
from .rewrite_models import AppliedLanguageRule, LanguageRule, ProtectedSpan, RewriteConfig

PROTECTION_RULE_VERSION = "rewrite-protection-1.0"

NUMBER = re.compile(r"[+\-−]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+\-]?\d+)?")
LOCATOR = re.compile(r"(?:[A-Z]\.)?\d+(?:\.\d+)+(?:-\d+)?|附录\s*[A-Z]")
SYMBOL = re.compile(
    r"\\[A-Za-z]+|[A-Za-z\u0370-\u03ff\u1f00-\u1fff]+|"
    r"[+\-−×÷*/^_=<>≤≥≠≈±∓∈∉∩∪∧∨·°%‰²³⁰-⁹₀-₉′″{}\[\]]"
)
LOGIC = re.compile(
    "|".join(
        sorted(
            {
                "严禁",
                "不得",
                "不应",
                "不宜",
                "不超过",
                "不少于",
                "不低于",
                "不高于",
                "不小于",
                "不大于",
                "不包含",
                "不包括",
                "必须",
                "应",
                "宜",
                "可",
                "仅",
                "至少",
                "至多",
                "除外",
                "如果",
                "除非",
                "当",
                "时",
                "同时满足",
                "满足",
                "且",
                "或",
                "并且",
                "以及",
                "同时",
                "分别",
                "不",
                "无",
                "非",
                "与",
                "和",
                "及",
                "比较",
                "包含",
                "排除",
                "先",
                "后",
                "因为",
                "因此",
                "若",
                "则",
                "否则",
                "大于",
                "小于",
                "等于",
                "正文",
                "条文说明",
                "强制性条文",
                "强条",
            },
            key=lambda word: (-len(word), word),
        )
    )
)
CHINESE_UNITS = (
    "平方毫米|平方厘米|平方米|立方毫米|立方厘米|立方米|毫米|厘米|千米|米|兆帕|千帕|帕|"
    "千牛|牛顿|千克|公斤|吨|克|摄氏度|度|小时|分钟|秒|项|个|层|根"
)
QUANTITY = re.compile(
    rf"(?:{NUMBER.pattern}|[零〇一二两三四五六七八九十百千万]+)\s*"
    rf"(?:[A-Za-zμµΩ℃°%‰]+(?:[*/][A-Za-z]+)?[²³⁰-⁹]*|{CHINESE_UNITS})"
)
TITLE = re.compile(r"《[^》]+》|\d{4}年?版|(?:\d{4}年)?(?:修订版|修订|局部修订)")


def extract_protected_spans(text: str, literals: Sequence[str] = ()) -> list[ProtectedSpan]:
    patterns = {
        "standard": STANDARD_CODE,
        "locator": LOCATOR,
        "number": NUMBER,
        "quantity": QUANTITY,
        "symbol": SYMBOL,
        "logic": LOGIC,
        "title": TITLE,
    }
    result = [
        ProtectedSpan(kind=kind, value=match.group(), start=match.start(), end=match.end())
        for kind, pattern in patterns.items()
        for match in pattern.finditer(text)
    ]
    result.extend(
        ProtectedSpan(kind="scope", value=value, start=match.start(), end=match.end())
        for value in literals
        for match in re.finditer(re.escape(value), text)
    )
    # Catch mathematical operators/modifier letters beyond the common regex examples.
    result.extend(
        ProtectedSpan(kind="symbol", value=char, start=index, end=index + 1)
        for index, char in enumerate(text)
        if unicodedata.category(char) in {"Sm", "Sk", "No", "Lm"}
    )
    unique = {(item.kind, item.start, item.end, item.value): item for item in result}
    return sorted(unique.values(), key=lambda item: (item.start, item.end, item.kind))


def scope_literals(understanding: UnderstandingResult, question: str) -> list[str]:
    values = [
        *understanding.filters.standard_codes,
        *understanding.filters.editions,
        *understanding.filters.clause_numbers,
    ]
    for match in understanding.catalog_matches:
        for record in match.candidates:
            if record.document_id in understanding.filters.document_ids:
                values.extend(
                    value
                    for value in (
                        record.standard.standard_name,
                        record.standard.standard_code,
                        record.standard.edition,
                        record.standard.revision,
                        *record.aliases,
                    )
                    if value is not None
                )
    return list(dict.fromkeys(value for value in values if value.strip() and value in question))


def validate_understanding_scope(request: QueryRequest, understanding: UnderstandingResult) -> None:
    """Check consistency only. Do not rerun Understanding or call its catalog."""
    filters = understanding.filters
    for field in type(request.filters).model_fields:
        old, new = getattr(request.filters, field), getattr(filters, field)
        if isinstance(old, list):
            if old and (not new or not set(new).issubset(old)):
                raise ValueError(f"Understanding expanded caller {field}")
        elif old is not None and old != new:
            raise ValueError(f"Understanding changed caller {field}")
    for decision in understanding.decisions:
        if decision.status != "adopted":
            continue
        candidate = decision.candidate
        evidence = (
            [item.evidence for item in candidate.selectors().values()]
            if isinstance(candidate, StandardCandidate)
            else [candidate.evidence]
        )
        for item in evidence:
            if item.source != "question":
                raise ValueError("adopted historical scope is not current user evidence")
            try:
                verify_span(item, request)
            except UnderstandingError as exc:
                raise ValueError("Understanding evidence belongs to a different question") from exc
        if isinstance(candidate, StandardCandidate):
            if not decision.document_ids or not set(decision.document_ids).issubset(
                filters.document_ids
            ):
                raise ValueError("adopted standard has no corresponding filtered document")
        else:
            field = decision.key.split("[")[0]
            if field not in type(filters).model_fields:
                raise ValueError("adopted candidate has an unsupported filter field")
            applied = getattr(filters, field)
            if (
                candidate.value not in applied
                if isinstance(applied, list)
                else candidate.value != applied
            ):
                raise ValueError("adopted candidate is absent from Understanding filters")
    active_records = [
        record
        for match in understanding.catalog_matches
        for record in match.candidates
        if record.document_id in filters.document_ids
    ]
    codes = {code_key(code) for code in filters.standard_codes}
    codes.update(code_key(item.standard.standard_code) for item in active_records)
    if any(
        code_key(match.group()) not in codes for match in STANDARD_CODE.finditer(request.question)
    ):
        raise ValueError("question standard identity is missing from Understanding scope")
    editions = [
        *filters.editions,
        *(item.standard.edition for item in active_records if item.standard.edition),
    ]
    if editions and any(
        not any(match.group(1) in edition for edition in editions)
        for match in re.finditer(r"(\d{4})年?版", request.question)
    ):
        raise ValueError("question edition conflicts with Understanding scope")
    if filters.clause_numbers:
        clauses = re.findall(r"第\s*(\d+(?:\.\d+){2,})\s*条", request.question)
        if clauses and not set(clauses).intersection(filters.clause_numbers):
            raise ValueError("question clause conflicts with Understanding scope")


def _rule_applies(rule: LanguageRule, original: str, index: int) -> bool:
    return (
        original.startswith(rule.source, index)
        and (rule.position != "prefix" or index == 0)
        and (rule.position != "suffix" or index + len(rule.source) == len(original))
    )


def validate_rewrite(
    original: str,
    rewritten: str,
    config: RewriteConfig,
    literals: Sequence[str] = (),
) -> list[AppliedLanguageRule]:
    """Require unchanged technical token sequences AND a proof of every wording edit.

    Monotone alignment permits copying characters or applying one reviewed local rule.
    No reordering, guessing terms, global NLP, or model-authored edit justification.
    """
    protected = extract_protected_spans(original, literals)
    actual = extract_protected_spans(rewritten, literals)
    for kind in sorted({item.kind for item in [*protected, *actual]}):
        if [item.value for item in protected if item.kind == kind] != [
            item.value for item in actual if item.kind == kind
        ]:
            raise ValueError(f"protected {kind} sequence changed")
    start = (0, 0)
    pending = [start]
    parents: dict[tuple[int, int], tuple[tuple[int, int], LanguageRule | None] | None] = {
        start: None
    }
    target = (len(original), len(rewritten))
    while pending:
        position = pending.pop()
        if position == target:
            edits: list[AppliedLanguageRule] = []
            while (edge := parents[position]) is not None:
                previous, rule = edge
                if rule is not None:
                    edits.append(
                        AppliedLanguageRule(
                            start=previous[0],
                            end=position[0],
                            replacement=rule.target,
                            evidence_id=rule.evidence_id,
                        )
                    )
                position = previous
            return list(reversed(edits))
        old, new = position
        transitions: list[tuple[tuple[int, int], LanguageRule | None]] = []
        for rule in config.language_rules:
            if _rule_applies(rule, original, old) and rewritten.startswith(rule.target, new):
                transitions.append(((old + len(rule.source), new + len(rule.target)), rule))
        if old < len(original) and new < len(rewritten) and original[old] == rewritten[new]:
            transitions.append(((old + 1, new + 1), None))
        for destination, rule in transitions:
            if destination not in parents:
                if len(parents) >= config.max_alignment_states:
                    raise ValueError("safe wording alignment budget exhausted")
                parents[destination] = (position, rule)
                pending.append(destination)
    raise ValueError("unreviewed wording/semantic edit")
