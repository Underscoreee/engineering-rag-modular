"""Evidence-based continuation matching with explicit conflict reasons."""

from __future__ import annotations

from .header_normalizer import normalized_header_signature
from .models import ContinuationDecision, TableFragmentCandidate


def decide_continuation(
    previous: TableFragmentCandidate, current: TableFragmentCandidate
) -> ContinuationDecision:
    evidence: list[str] = []
    if current.page_number != previous.page_number + 1:
        return ContinuationDecision(should_merge=False, reason="non_adjacent_source_pages")
    evidence.append("adjacent_original_pages")
    if (
        previous.table_number
        and current.table_number
        and previous.table_number != current.table_number
    ):
        return ContinuationDecision(
            should_merge=False,
            reason="different_table_number",
            evidence=evidence,
        )
    if not current.is_continuation:
        return ContinuationDecision(
            should_merge=False,
            reason="insufficient_positive_evidence",
            evidence=evidence,
        )
    evidence.append("explicit_continuation_caption")
    if previous.table_number and current.table_number:
        evidence.append("same_table_number")
    else:
        return ContinuationDecision(
            should_merge=False,
            reason="missing_table_number",
            evidence=evidence,
        )
    if previous.grid.column_count != current.grid.column_count:
        return ContinuationDecision(
            should_merge=False,
            reason="incompatible_columns",
            evidence=evidence,
        )
    evidence.append("same_column_count")
    previous_signature = normalized_header_signature(previous.header_paths)
    current_signature = normalized_header_signature(current.header_paths)
    if not previous_signature or not current_signature:
        return ContinuationDecision(
            should_merge=False,
            reason="missing_header_signature",
            evidence=evidence,
        )
    matching = sum(
        left == right for left, right in zip(previous_signature, current_signature, strict=True)
    )
    if matching * 2 < len(previous_signature):
        return ContinuationDecision(
            should_merge=False,
            reason="incompatible_columns",
            evidence=evidence,
        )
    evidence.append(f"compatible_header_signature:{matching}/{len(previous_signature)}")
    return ContinuationDecision(
        should_merge=True,
        reason="explicit_continuation_with_compatible_structure",
        evidence=evidence,
    )
