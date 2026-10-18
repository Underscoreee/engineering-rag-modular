"""Ground candidates in original user text; regex guards do not classify intent."""

import re
import unicodedata

from engineering_rag.contracts.queries import QueryRequest

from .errors import UnderstandingError
from .models import BooleanCandidate, ContentTypeCandidate, SourceEvidence, TextCandidate

# A conservative omission guard, not a standards registry or an intent classifier.
STANDARD_CODE = re.compile(
    r"(?<![A-Za-z0-9])(?:"
    r"(?:GB|JGJ|JTG|JT|CJJ|CJ|DL|SL|CECS|JB|NB|JG|JC|DB\d{2})"
    r"(?:\s*/\s*[TZ])?\s*\d{1,8}(?:\s*[-—–－]\s*\d{4})?"
    r"|[A-Z]{2,8}(?:\s*/\s*[A-Z])?\s*\d{3,8}\s*[-—–－]\s*\d{4}"
    r")(?![\dA-Za-z])"
)
CLAUSE_NUMBER = re.compile(r"(?:\d+(?:\.\d+){2,}|[A-Z]\.\d+(?:\.\d+)*)")


def code_key(text: str) -> str:
    return (
        re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).replace("—", "-").replace("–", "-")
    )


def _source_text(evidence: SourceEvidence, request: QueryRequest) -> str:
    if evidence.source == "question":
        return request.question
    index = evidence.history_index
    if index is None or index >= len(request.history) or request.history[index].role != "user":
        raise UnderstandingError("invalid_evidence", "history source is not a user turn")
    return request.history[index].content


def verify_span(evidence: SourceEvidence, request: QueryRequest) -> None:
    source = _source_text(evidence, request)
    if source[evidence.start : evidence.end] != evidence.quote or evidence.end > len(source):
        raise UnderstandingError(
            "invalid_evidence", "quote does not match its original source span"
        )


def verify_text(candidate: TextCandidate, request: QueryRequest) -> None:
    verify_span(candidate.evidence, request)
    if candidate.value not in candidate.evidence.quote:
        raise UnderstandingError("invalid_evidence", "candidate value is absent from its evidence")


CONTENT_LABELS = {
    "clause": ("条文", "条款"),
    "paragraph": ("段落",),
    "text": ("文本", "正文"),
    "table": ("表格", "表"),
    "formula": ("公式",),
    "figure": ("图片", "插图", "图"),
    "mixed": ("混合内容",),
}
BOOLEAN_LABELS = {
    "is_explanation": {True: ("条文说明",), False: ("正文", "非条文说明")},
    "is_mandatory": {True: ("强制性条文", "强条"), False: ("非强制性条文", "非强条")},
}


def verify_content_type(candidate: ContentTypeCandidate, request: QueryRequest) -> None:
    verify_span(candidate.evidence, request)
    if candidate.evidence.quote.strip() not in CONTENT_LABELS[candidate.value]:
        raise UnderstandingError(
            "invalid_evidence", "content type needs a minimal explicit type label"
        )
    _reject_negated_label(candidate.evidence, request)


def _reject_negated_label(evidence: SourceEvidence, request: QueryRequest) -> None:
    source = _source_text(evidence, request)
    prefix = source[max(0, evidence.start - 3) : evidence.start]
    if re.search(r"(?:非|不含|排除|不要|不查|不是|不只|不限于)$", prefix):
        raise UnderstandingError("invalid_evidence", "filter label is negated in original context")


def verify_boolean(field: str, candidate: BooleanCandidate, request: QueryRequest) -> None:
    verify_span(candidate.evidence, request)
    if candidate.evidence.quote.strip() not in BOOLEAN_LABELS[field][candidate.value]:
        raise UnderstandingError(
            "invalid_evidence", "boolean filter lacks an explicit semantic label"
        )
    # A substring within a negative phrase is not evidence for that filter value.
    _reject_negated_label(candidate.evidence, request)
