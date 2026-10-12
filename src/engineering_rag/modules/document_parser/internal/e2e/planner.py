"""Deterministic bounded batch planning with protected contiguous groups."""

from .models import BatchPlan


def ensure_full_document_authorized(
    *, selected_page_count: int, page_count: int, explicitly_approved: bool
) -> None:
    """Fail closed before scheduling an unapproved full-document inference."""

    if selected_page_count == page_count and not explicitly_approved:
        raise PermissionError(
            "full-document MinerU inference is NOT_RUN: explicit maintainer approval required"
        )


def plan_batches(
    pages: list[int],
    *,
    max_batch_size: int = 20,
    protected_groups: tuple[tuple[int, ...], ...] = (
        (28, 29),
        (37, 38),
        (49, 50),
        (126, 127),
    ),
) -> list[BatchPlan]:
    if max_batch_size < 1 or max_batch_size > 20:
        raise ValueError("max_batch_size must be between 1 and 20")
    ordered = sorted(set(pages))
    if not ordered or ordered[0] < 1:
        raise ValueError("pages must contain positive 1-based page numbers")
    selected = set(ordered)
    units: list[list[int]] = []
    claimed: set[int] = set()
    groups = {group[0]: list(group) for group in protected_groups if set(group) <= selected}
    for page in ordered:
        if page in claimed:
            continue
        unit = groups.get(page, [page])
        if len(unit) > max_batch_size:
            raise ValueError("protected group exceeds max_batch_size")
        units.append(unit)
        claimed.update(unit)
    batches: list[list[int]] = []
    current: list[int] = []
    for unit in units:
        if current and len(current) + len(unit) > max_batch_size:
            batches.append(current)
            current = []
        current.extend(unit)
    if current:
        batches.append(current)
    return [
        BatchPlan(batch_id=f"batch-{index:03d}", pages=batch)
        for index, batch in enumerate(batches, start=1)
    ]
