"""Conservative formula-number matching with explicit positive evidence."""

from __future__ import annotations

import re

from engineering_rag.contracts.documents import FormulaNumberStatus

from .models import NumberEvidence

_TAG = re.compile(r"\\tag\s*\{([^{}]+)\}")
_NUMBER = re.compile(r"^\d+(?:\.\d+)+(?:-\d+)?$")


def evidence_from_latex(latex: str | None) -> list[NumberEvidence]:
    if not latex:
        return []
    return [
        NumberEvidence(
            raw_text=match.group(1),
            normalized_number=normalize_number(match.group(1)),
            source_kind="equation_tag",
            right_of_equation=True,
            vertical_overlap_ratio=1.0,
        )
        for match in _TAG.finditer(latex)
    ]


def match_number(
    evidence: list[NumberEvidence],
) -> tuple[str | None, FormulaNumberStatus, list[str]]:
    diagnostics: list[str] = []
    eligible: list[str] = []
    for item in evidence:
        number = item.normalized_number or normalize_number(item.raw_text)
        if number is None:
            diagnostics.append(f"rejected non-number candidate: {item.raw_text}")
            continue
        if item.source_kind == "body_text":
            diagnostics.append(f"ignored body reference candidate: {item.raw_text}")
            continue
        if item.source_kind == "aligned_text" and not (
            item.right_of_equation
            and item.vertical_overlap_ratio is not None
            and item.vertical_overlap_ratio >= 0.5
        ):
            diagnostics.append(f"rejected weak geometry candidate: {item.raw_text}")
            continue
        eligible.append(number)
    unique = list(dict.fromkeys(eligible))
    if len(unique) == 1:
        return unique[0], FormulaNumberStatus.PRINTED, diagnostics
    if len(unique) > 1:
        diagnostics.append(f"conflicting printed-number candidates: {unique}")
    else:
        diagnostics.append("no reliable printed-number evidence")
    return None, FormulaNumberStatus.UNKNOWN, diagnostics


def normalize_number(value: str) -> str | None:
    candidate = value.strip().strip("()（）").strip()
    return candidate if _NUMBER.fullmatch(candidate) else None
