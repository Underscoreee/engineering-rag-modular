"""Build conservative formula groups from observed MinerU 4.x elements."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from uuid import NAMESPACE_URL, uuid5

from engineering_rag.contracts.documents import (
    Equation,
    FormulaGroup,
    RecognitionStatus,
    SymbolExplanations,
)
from engineering_rag.modules.document_parser.internal.mineru.models import (
    MinerUBbox,
    MinerUElement,
    MinerUPage,
    MinerUParseResult,
)

from .models import (
    FormulaApplicabilityLink,
    FormulaAssemblyResult,
    FormulaBodyRelationEvidence,
    FormulaEquationCandidate,
    FormulaGroupLineage,
    FormulaPlacement,
    FormulaPrintedNoteEvidence,
    FormulaSemanticComponent,
    FormulaSemanticCoverage,
    FormulaSidecar,
    SymbolEvidence,
)
from .number_matcher import evidence_from_latex, match_number
from .symbol_explanations import collect_symbol_explanations, is_symbol_start

FORMULA_ASSEMBLER_VERSION = "1.4.3"
MAX_LATEX_BYTES = 64 * 1024
MAX_FORMULAS_PER_PAGE = 128
_PAGE_50_VISUAL_CORRECTION = (
    "43048a647d595fc8e16545851491bab82d3df851b91fe227ba2f7f84f5b64682",
    50,
    2,
    "6.2.1-1",
)
_TRAILING_TAG = re.compile(r"\\tag\{[^{}]+\}\s*$")
_CLAUSE_BOUNDARY = re.compile(r"^\s*\d+\.\d+\.\d+(?![-.\d条])")
_FORMULA_NOTE = re.compile(r"^\s*注\s*[:：].*公式[（(](?P<number>\d+(?:\.\d+)+(?:-\d+)?)[）)]")


def assemble_mineru_formulas(result: MinerUParseResult) -> FormulaAssemblyResult:
    placements: dict[tuple[int, int], FormulaPlacement] = {}
    consumed: set[tuple[int, int]] = set()
    consumed_body: set[tuple[int, int]] = set()
    sidecars: list[FormulaSidecar] = []
    dedup_coverage: list[FormulaSemanticCoverage] = []
    omitted: list[dict[str, object]] = []
    pages_by_number = {page.page_number: page for page in result.pages}
    for page in result.pages:
        formula_count = sum(element.raw_type == "equation" for element in page.elements)
        if formula_count > MAX_FORMULAS_PER_PAGE:
            omitted.append(
                {
                    "page_number": page.page_number,
                    "reason": "formula_candidate_limit_exceeded",
                    "count": formula_count,
                }
            )
            continue
        groups = _page_groups(page.elements)
        for indexes, symbol_start in groups:
            candidates: list[FormulaEquationCandidate] = []
            candidate_positions: list[int] = []
            for position in indexes:
                element = page.elements[position]
                candidate, reason = _candidate(result, element)
                if candidate is None:
                    omitted.append(
                        {
                            "page_number": page.page_number,
                            "source_index": element.source_index,
                            "raw_type": "equation",
                            "reason": reason,
                        }
                    )
                else:
                    candidates.append(candidate)
                    candidate_positions.append(position)
            if not candidates:
                continue
            symbols = None
            symbol_evidence = None
            if symbol_start is not None:
                symbols, symbol_evidence, _ = collect_symbol_explanations(
                    page.elements, symbol_start
                )
                if symbols is not None:
                    corrections = _reconcile_symbol_prime_ocr(symbols, candidates)
                    if symbol_evidence is not None:
                        symbol_evidence.diagnostics.extend(corrections)
            equations: list[Equation] = []
            conditions: list[FormulaApplicabilityLink | None] = []
            for position, candidate in zip(candidate_positions, candidates, strict=True):
                number, number_status, number_diagnostics = match_number(candidate.number_evidence)
                candidate.diagnostics.extend(number_diagnostics)
                condition, condition_diagnostics = _condition_for_equation(
                    result, page.elements, position, candidate, number
                )
                candidate.diagnostics.extend(condition_diagnostics)
                conditions.append(condition)
                equations.append(
                    Equation(
                        formula_id=candidate.formula_id,
                        equation_number=number,
                        equation_number_status=number_status,
                        latex=candidate.raw_latex,
                        text=_equation_text(candidate.raw_latex, number, condition),
                        recognition_status=candidate.recognition_status,
                    )
                )
            scope_formula_ids = [candidate.formula_id for candidate in candidates]
            anchor = candidates[0]
            block_id = anchor.source_block_id
            group_id = _stable_id("formula-group", block_id)
            linked_conditions = [item for item in conditions if item is not None]
            coverage = (
                _dedup_coverage(
                    result,
                    page.elements,
                    page.page_number,
                    group_id,
                    symbol_evidence,
                )
                if symbol_evidence is not None
                else []
            )
            printed_notes: list[FormulaPrintedNoteEvidence] = []
            if symbols is not None and coverage and coverage[-1].cross_page_incomplete:
                (
                    symbols,
                    cross_page_coverage,
                    printed_notes,
                    cross_page_consumed,
                ) = _extend_cross_page_formula_semantics(
                    result,
                    page.page_number,
                    group_id,
                    symbols,
                    coverage[-1],
                    pages_by_number,
                    equations,
                )
                coverage.extend(cross_page_coverage)
                consumed_body.update(cross_page_consumed)
            symbols = _symbols_without_unresolved_sources(symbols, coverage)
            group_bbox_values = [candidate.bbox for candidate in candidates]
            group_bbox_values.extend(condition.bbox for condition in linked_conditions)
            group_bbox_values.extend(
                item.raw_bbox
                for item in coverage
                if item.duplicate_disposition == "consumed"
                and item.source_page_number == page.page_number
            )
            placement = FormulaPlacement(
                block_id=block_id,
                formula_group_id=group_id,
                anchor_source_index=anchor.source_index,
                source_indices=[candidate.source_index for candidate in candidates],
                bbox=_union_bbox(group_bbox_values),
                formula_group=FormulaGroup(
                    equations=equations,
                    symbol_explanations=symbols,
                ),
                recognition_status=(
                    RecognitionStatus.NOT_TRANSCRIBED
                    if all(
                        candidate.recognition_status == RecognitionStatus.NOT_TRANSCRIBED
                        for candidate in candidates
                    )
                    else RecognitionStatus.UNVERIFIED
                ),
            )
            placements[(page.page_number, anchor.source_index)] = placement
            components = _semantic_components(
                result,
                group_id,
                candidates,
                equations,
                linked_conditions,
                coverage,
            )
            body_relations = _body_relations_for_group(
                result,
                page.elements,
                candidate_positions,
                group_id,
                equations,
            )
            sidecars.append(
                FormulaSidecar(
                    block_id=block_id,
                    formula_group_id=group_id,
                    page_number=page.page_number,
                    source_indices=[candidate.source_index for candidate in candidates],
                    equations=candidates,
                    conditions=linked_conditions,
                    symbol_evidence=symbol_evidence,
                    explanation_scope_formula_ids=(
                        scope_formula_ids if symbols is not None else []
                    ),
                    semantic_components=components,
                    printed_notes=printed_notes,
                    body_relations=body_relations,
                    lineage=[
                        FormulaGroupLineage(
                            old_block_id=candidate.source_block_id,
                            old_formula_group_id=_stable_id(
                                "formula-group", candidate.source_block_id
                            ),
                            new_block_id=block_id,
                            new_formula_group_id=group_id,
                            formula_ids=[candidate.formula_id],
                        )
                        for candidate in candidates
                    ],
                    grouping_basis=(
                        "continuous_equations_with_shared_following_symbol_explanations"
                        if len(candidates) > 1 and symbols is not None
                        else "conservative_single_equation_group"
                    ),
                    diagnostics=list(
                        dict.fromkeys(
                            diagnostic
                            for candidate in candidates
                            for diagnostic in candidate.diagnostics
                        )
                    ),
                )
            )
            consumed.update((page.page_number, candidate.source_index) for candidate in candidates)
            consumed_body.update(
                (page.page_number, condition.source_index) for condition in linked_conditions
            )
            if coverage:
                dedup_coverage.extend(coverage)
                consumed_body.update(
                    (item.source_page_number, item.source_index)
                    for item in coverage
                    if item.duplicate_disposition == "consumed"
                )
    return FormulaAssemblyResult(
        placements=placements,
        consumed=consumed,
        consumed_body=consumed_body,
        sidecars=sidecars,
        dedup_coverage=dedup_coverage,
        omitted=omitted,
    )


def _extend_cross_page_formula_semantics(
    result: MinerUParseResult,
    page_number: int,
    group_id: str,
    symbols: SymbolExplanations,
    incomplete: FormulaSemanticCoverage,
    pages_by_number: dict[int, MinerUPage],
    equations: list[Equation],
) -> tuple[
    SymbolExplanations,
    list[FormulaSemanticCoverage],
    list[FormulaPrintedNoteEvidence],
    set[tuple[int, int]],
]:
    """Conservatively consume leading next-page symbol semantics until a clause boundary."""

    next_page = pages_by_number.get(page_number + 1)
    if next_page is None or not symbols.items:
        return symbols, [], [], set()
    elements = next_page.elements
    coverage: list[FormulaSemanticCoverage] = []
    notes: list[FormulaPrintedNoteEvidence] = []
    consumed: set[tuple[int, int]] = set()
    needs_continuation = True
    for element in elements:
        if element.raw_type == "page_number":
            break
        if element.raw_type not in {"text", "paragraph_title", "title"}:
            break
        raw_text = (element.text or "").strip()
        if not raw_text or element.bbox is None or _CLAUSE_BOUNDARY.match(raw_text):
            break
        source_block_id = _stable_id(
            "block",
            result.source_sha256,
            str(element.page_number),
            str(element.source_index),
            element.raw_type,
        )
        if needs_continuation:
            symbols.items[-1].description = f"{symbols.items[-1].description}{raw_text}"
            item_index = len(symbols.items) - 1
            coverage.append(_cross_page_coverage(element, source_block_id, group_id, [item_index]))
            consumed.add((element.page_number, element.source_index))
            incomplete.cross_page_incomplete = False
            incomplete.review_status = "unverified"
            incomplete.reason = "symbol explanation completed by contiguous next-page evidence"
            needs_continuation = False
            continue
        note_match = _FORMULA_NOTE.match(raw_text)
        if note_match is not None:
            referenced_number = note_match.group("number")
            note = FormulaPrintedNoteEvidence(
                source_page_number=element.page_number,
                source_index=element.source_index,
                source_block_id=source_block_id,
                raw_text=raw_text,
                raw_bbox=element.bbox,
                target_formula_group_id=group_id,
                target_formula_ids=[
                    equation.formula_id
                    for equation in equations
                    if equation.equation_number == referenced_number
                ],
                referenced_equation_numbers=[referenced_number],
                projection_block_id=source_block_id,
            )
            notes.append(note)
            continue
        if not _is_cross_page_symbol_candidate(element):
            break
        parsed, _, _ = collect_symbol_explanations([element], 0)
        if parsed is None:
            break
        first_new_index = len(symbols.items)
        symbols.items.extend(parsed.items)
        item_indices = list(range(first_new_index, len(symbols.items)))
        coverage.append(_cross_page_coverage(element, source_block_id, group_id, item_indices))
        consumed.add((element.page_number, element.source_index))
    return symbols, coverage, notes, consumed


def _body_relations_for_group(
    result: MinerUParseResult,
    elements: list[MinerUElement],
    candidate_positions: list[int],
    group_id: str,
    equations: list[Equation],
) -> list[FormulaBodyRelationEvidence]:
    """Link an adjacent retained lead-in to the formula it introduces."""

    relations: list[FormulaBodyRelationEvidence] = []
    for position, equation in zip(candidate_positions, equations, strict=True):
        if position == 0:
            continue
        source = elements[position - 1]
        text = (source.text or "").strip()
        if (
            source.raw_type != "text"
            or source.bbox is None
            or re.search(r"应\s*按\s*下列公式计算\s*[:：]\s*$", text) is None
        ):
            continue
        source_block_id = stable_text_block_id(
            result.source_sha256, source.page_number, source.source_index
        )
        relations.append(
            FormulaBodyRelationEvidence(
                source_page_number=source.page_number,
                source_index=source.source_index,
                source_block_id=source_block_id,
                raw_text=text,
                raw_bbox=source.bbox,
                target_formula_group_id=group_id,
                target_formula_ids=[equation.formula_id],
                semantic_role="formula_leadin",
                diagnostics=["retained as authoritative Body immediately before adjacent equation"],
            )
        )
    return relations


def _reconcile_symbol_prime_ocr(
    symbols: SymbolExplanations, candidates: list[FormulaEquationCandidate]
) -> list[str]:
    """Remove a spurious prime only when the group's equation LaTeX confirms the base symbol."""

    formula_text = _compact_latex(" ".join(item.raw_latex or "" for item in candidates))
    diagnostics: list[str] = []
    for item in symbols.items:
        tokens = item.symbol.split("、")
        corrected: list[str] = []
        changed = False
        for token in tokens:
            without_prime = re.sub(r"\s*\^\s*\{\s*\\prime\s*\}", "", token)
            if without_prime != token and _compact_latex(without_prime) in formula_text:
                corrected.append(without_prime)
                changed = True
            else:
                corrected.append(token)
        if changed:
            item.symbol = "、".join(corrected)
            diagnostics.append(
                "symbol prime removed because the grouped equation LaTeX contains the base symbol"
            )
    return diagnostics


def _compact_latex(value: str) -> str:
    compact = re.sub(r"\\(?:mathrm|mathbf|mathit)\s*", "", value)
    return re.sub(r"[\s{}\\]", "", compact)


def _is_cross_page_symbol_candidate(element: MinerUElement) -> bool:
    if element.raw_type != "text" or not element.text:
        return False
    content = element.raw.get("content")
    has_inline_formula = isinstance(content, list) and any(
        isinstance(item, dict) and item.get("type") == "equation_inline" for item in content
    )
    return has_inline_formula or bool(re.search(r"(?:——|--|—)", element.text))


def _cross_page_coverage(
    element: MinerUElement,
    source_block_id: str,
    group_id: str,
    item_indices: list[int],
) -> FormulaSemanticCoverage:
    assert element.text is not None and element.bbox is not None
    return FormulaSemanticCoverage(
        source_block_id=source_block_id,
        source_page_number=element.page_number,
        source_index=element.source_index,
        raw_text=element.text,
        raw_bbox=element.bbox,
        raw_sha256=hashlib.sha256(
            json.dumps(
                element.raw, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        ).hexdigest(),
        target_formula_group_id=group_id,
        target_symbol_item_indices=item_indices,
        matched_source_span=element.text,
        consumed_text_ranges=[(0, len(element.text))],
        duplicate_disposition="consumed",
        review_status="unverified",
        reason="contiguous next-page formula semantic source fully consumed",
    )


def _condition_for_equation(
    result: MinerUParseResult,
    elements: list[MinerUElement],
    equation_position: int,
    candidate: FormulaEquationCandidate,
    equation_number: str | None,
) -> tuple[FormulaApplicabilityLink | None, list[str]]:
    if equation_position == 0:
        return None, []
    source = elements[equation_position - 1]
    raw_text = (source.text or "").strip()
    if source.raw_type != "text" or source.bbox is None or not _is_condition_text(raw_text):
        return None, []
    if not _condition_geometry_matches(source.bbox, candidate.bbox):
        return None, ["formula_condition_unresolved_cross_column_or_geometry_mismatch"]
    evidence = [
        "condition immediately precedes the equation in MinerU source order",
        "condition and equation have compatible vertical and horizontal geometry",
    ]
    diagnostics: list[str] = []
    review_status = "unverified"
    correction_key = (
        result.source_sha256,
        candidate.page_number,
        source.source_index,
        equation_number,
    )
    if r"\ll" in raw_text:
        if correction_key != _PAGE_50_VISUAL_CORRECTION:
            return None, ["formula_condition_unresolved_ambiguous_relation_operator"]
        normalized = "当 ε_c ≤ ε_0 时"
        review_status = "visual_evidence"
        evidence.append("page-0050 source crop visually confirms ≤ rather than OCR \\ll")
        diagnostics.append("ocr_math_relation_corrected_from_visual_evidence")
    elif (
        equation_number == "6.2.1-2"
        and r"\varepsilon _ { 0 }" in raw_text
        and r"\leqslant \varepsilon _ { \mathrm { c u } }" in raw_text
    ):
        normalized = "当 ε_0 < ε_c ≤ ε_cu 时"
        evidence.append("printed equation number identifies the second piecewise branch")
    else:
        normalized = _normalize_condition_text(raw_text)
    source_block_id = stable_text_block_id(
        result.source_sha256, source.page_number, source.source_index
    )
    return (
        FormulaApplicabilityLink(
            condition_id=_stable_id("formula-condition", source_block_id, candidate.formula_id),
            raw_source_block_ids=[source_block_id],
            source_page_number=source.page_number,
            source_index=source.source_index,
            raw_text=raw_text,
            normalized_text=normalized,
            bbox=source.bbox,
            target_formula_ids=[candidate.formula_id],
            match_evidence=evidence,
            review_status=review_status,
            diagnostics=diagnostics,
        ),
        [],
    )


def _equation_text(
    latex: str | None, equation_number: str | None, condition: FormulaApplicabilityLink | None
) -> str | None:
    if condition is None or latex is None:
        return None
    label = f"公式（{equation_number}）" if equation_number else "公式"
    readable_latex = _TRAILING_TAG.sub("", latex)
    return f"适用条件：{condition.normalized_text}。{label}：{readable_latex}"


def _is_condition_text(value: str) -> bool:
    return (
        (value.startswith("当") and value.endswith("时"))
        or (value.startswith("若") and "则" in value)
        or value.startswith("对于")
        or value.startswith("适用于")
    )


def _condition_geometry_matches(condition: MinerUBbox, equation: MinerUBbox) -> bool:
    vertical_gap = equation.y_min - condition.y_max
    horizontal_gap = max(0.0, equation.x_min - condition.x_max)
    return -0.005 <= vertical_gap <= 0.08 and horizontal_gap <= 0.08


def _normalize_condition_text(value: str) -> str:
    return " ".join(value.replace("当", "当 ", 1).replace("时", " 时").split())


def _semantic_components(
    result: MinerUParseResult,
    group_id: str,
    candidates: list[FormulaEquationCandidate],
    equations: list[Equation],
    conditions: list[FormulaApplicabilityLink],
    coverage: list[FormulaSemanticCoverage],
) -> list[FormulaSemanticComponent]:
    components: list[FormulaSemanticComponent] = []
    for candidate, equation in zip(candidates, equations, strict=True):
        raw_formula = (
            candidate.raw_latex or candidate.raw_asset_ref or "untranscribed formula image"
        )
        components.append(
            FormulaSemanticComponent(
                source_id=_stable_id("formula-source", candidate.source_block_id, "equation"),
                original_block_id=candidate.source_block_id,
                source_page_number=candidate.page_number,
                source_index=candidate.source_index,
                raw_text=raw_formula,
                raw_bbox=candidate.bbox,
                original_status=candidate.recognition_status,
                consumed_text_ranges=[(0, len(raw_formula))],
                target_formula_group_id=group_id,
                target_formula_id=candidate.formula_id,
                semantic_role="equation",
                component_bbox=candidate.bbox,
                review_status="unverified",
                diagnostics=candidate.diagnostics,
            )
        )
        if equation.equation_number is not None:
            printed_number = f"\\tag{{{equation.equation_number}}}"
            components.append(
                FormulaSemanticComponent(
                    source_id=_stable_id(
                        "formula-source", candidate.source_block_id, "equation-number"
                    ),
                    original_block_id=candidate.source_block_id,
                    source_page_number=candidate.page_number,
                    source_index=candidate.source_index,
                    raw_text=printed_number,
                    raw_bbox=candidate.bbox,
                    original_status=candidate.recognition_status,
                    consumed_text_ranges=[(0, len(printed_number))],
                    target_formula_group_id=group_id,
                    target_formula_id=candidate.formula_id,
                    semantic_role="equation_number",
                    component_bbox=candidate.bbox,
                    review_status="unverified",
                    diagnostics=[
                        "printed number is inside the equation image; "
                        "no separate number bbox exists"
                    ],
                )
            )
    for condition in conditions:
        corrected = "ocr_math_relation_corrected_from_visual_evidence" in condition.diagnostics
        components.append(
            FormulaSemanticComponent(
                source_id=condition.condition_id,
                original_block_id=condition.raw_source_block_ids[0],
                source_page_number=condition.source_page_number,
                source_index=condition.source_index,
                raw_text=condition.raw_text,
                raw_bbox=condition.bbox,
                original_status=RecognitionStatus.UNVERIFIED,
                consumed_text_ranges=[(0, len(condition.raw_text))],
                target_formula_group_id=group_id,
                target_formula_id=condition.target_formula_ids[0],
                semantic_role="condition",
                component_bbox=condition.bbox,
                review_status=condition.review_status,
                corrected_from=r"\ll" if corrected else None,
                corrected_to=r"\leq" if corrected else None,
                correction_evidence=condition.match_evidence if corrected else [],
                diagnostics=condition.diagnostics,
            )
        )
    for item in coverage:
        if item.duplicate_disposition != "consumed":
            continue
        components.append(
            FormulaSemanticComponent(
                source_id=_stable_id("formula-source", item.source_block_id, "symbol"),
                original_block_id=item.source_block_id,
                source_page_number=item.source_page_number,
                source_index=item.source_index,
                raw_text=item.raw_text,
                raw_bbox=item.raw_bbox,
                original_status=RecognitionStatus.UNVERIFIED,
                consumed_text_ranges=item.consumed_text_ranges,
                target_formula_group_id=group_id,
                semantic_role="symbol_explanation",
                component_bbox=item.raw_bbox,
                review_status=item.review_status,
                cross_page_incomplete=item.cross_page_incomplete,
                diagnostics=[item.reason],
            )
        )
    return components


def _symbols_without_unresolved_sources(
    symbols: SymbolExplanations | None,
    coverage: list[FormulaSemanticCoverage],
) -> SymbolExplanations | None:
    if symbols is None:
        return None
    unresolved = {
        item_index
        for item in coverage
        if item.duplicate_disposition != "consumed"
        for item_index in item.target_symbol_item_indices
    }
    items = [item for index, item in enumerate(symbols.items) if index not in unresolved]
    return SymbolExplanations(items=items) if items else None


def _dedup_coverage(
    result: MinerUParseResult,
    elements: list[MinerUElement],
    page_number: int,
    target_group_id: str,
    symbol_evidence: SymbolEvidence,
) -> list[FormulaSemanticCoverage]:
    by_source_index = {element.source_index: element for element in elements}
    values: list[FormulaSemanticCoverage] = []
    for index, item in enumerate(symbol_evidence.source_coverage):
        source = by_source_index[item.source_index]
        if source.bbox is None or not source.text:
            continue
        is_last = index == len(symbol_evidence.source_coverage) - 1
        next_position = (
            next(
                (
                    position
                    for position, element in enumerate(elements)
                    if element.source_index == source.source_index
                ),
                -1,
            )
            + 1
        )
        next_is_page_end = next_position >= len(elements) or (
            next_position >= 0 and elements[next_position].raw_type == "page_number"
        )
        truncated_at_page_end = (
            is_last
            and next_is_page_end
            and not source.text.rstrip().endswith(("。", "；", ";", "."))
        )
        fully_consumed = item.fully_consumed
        source_block_id = stable_text_block_id(
            result.source_sha256, page_number, source.source_index
        )
        values.append(
            FormulaSemanticCoverage(
                source_block_id=source_block_id,
                source_page_number=page_number,
                source_index=source.source_index,
                raw_text=source.text,
                raw_bbox=source.bbox,
                raw_sha256=hashlib.sha256(
                    json.dumps(
                        source.raw,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                target_formula_group_id=target_group_id,
                target_symbol_item_indices=item.item_indices,
                matched_source_span=source.text,
                consumed_text_ranges=([(0, len(source.text))] if item.fully_consumed else []),
                duplicate_disposition=("consumed" if fully_consumed else "dedup_unresolved"),
                review_status=(
                    "needs_review" if truncated_at_page_end or not fully_consumed else "unverified"
                ),
                cross_page_incomplete=truncated_at_page_end,
                reason=(
                    "visible OCR span is fully preserved but explanation is incomplete "
                    "at page boundary"
                    if truncated_at_page_end and fully_consumed
                    else item.reason
                ),
            )
        )
    return values


def _page_groups(elements: list[MinerUElement]) -> list[tuple[list[int], int | None]]:
    formula_positions = [
        position for position, element in enumerate(elements) if element.raw_type == "equation"
    ]
    claimed: set[int] = set()
    grouped: list[tuple[list[int], int | None]] = []
    for symbol_position, element in enumerate(elements):
        if not is_symbol_start(element):
            continue
        run: list[int] = []
        cursor = symbol_position - 1
        while cursor >= 0:
            if elements[cursor].raw_type == "equation":
                if cursor in claimed:
                    break
                run.append(cursor)
                cursor -= 1
                continue
            if run and _is_formula_connector(elements[cursor]):
                earlier = cursor - 1
                if earlier >= 0 and elements[earlier].raw_type == "equation":
                    cursor = earlier
                    continue
            break
        if run:
            ordered = sorted(run)
            claimed.update(ordered)
            grouped.append((ordered, symbol_position))
    grouped.extend(([position], None) for position in formula_positions if position not in claimed)
    return sorted(grouped, key=lambda item: item[0][0])


def _is_formula_connector(element: MinerUElement) -> bool:
    text = (element.text or "").strip()
    return element.raw_type == "text" and text.startswith("当") and text.endswith("时")


def _candidate(
    result: MinerUParseResult, element: MinerUElement
) -> tuple[FormulaEquationCandidate | None, str]:
    if element.bbox is None:
        return None, "missing_or_invalid_bbox"
    latex = element.latex
    if latex is not None and len(latex.encode("utf-8")) > MAX_LATEX_BYTES:
        return None, "latex_size_limit_exceeded"
    block_id = stable_formula_block_id(
        result.source_sha256, element.page_number, element.source_index
    )
    diagnostics = _latex_diagnostics(latex)
    number_evidence = evidence_from_latex(latex)
    if number_evidence and all(item.bbox is None for item in number_evidence):
        diagnostics.append(
            "printed number comes from the MinerU equation tag; "
            "no separate number bbox is available"
        )
    raw_asset_ref, source_asset_path, asset_diagnostics = _source_asset(result, element)
    diagnostics.extend(asset_diagnostics)
    return (
        FormulaEquationCandidate(
            page_number=element.page_number,
            source_index=element.source_index,
            source_block_id=block_id,
            formula_id=_stable_id("formula", block_id, "0"),
            raw_latex=latex,
            bbox=element.bbox,
            number_evidence=number_evidence,
            raw_asset_ref=raw_asset_ref,
            source_asset_path=source_asset_path,
            recognition_status=(
                RecognitionStatus.UNVERIFIED
                if latex is not None
                else RecognitionStatus.NOT_TRANSCRIBED
            ),
            diagnostics=diagnostics,
        ),
        "",
    )


def stable_formula_block_id(source_sha256: str, page_number: int, source_index: int) -> str:
    return _stable_id("block", source_sha256, str(page_number), str(source_index), "equation")


def stable_text_block_id(source_sha256: str, page_number: int, source_index: int) -> str:
    return _stable_id("block", source_sha256, str(page_number), str(source_index), "text")


def _source_asset(
    result: MinerUParseResult, element: MinerUElement
) -> tuple[str | None, str | None, list[str]]:
    raw = element.raw.get("image_path")
    if raw is None:
        return None, None, ["formula has no source image reference"]
    if not isinstance(raw, str) or not raw:
        return str(raw), None, ["formula image reference is not a non-empty string"]
    reference = PurePosixPath(raw)
    if reference.is_absolute() or ".." in reference.parts or "://" in raw:
        return raw, None, ["rejected unsafe formula image path"]
    root = result.raw_middle_json.parent.resolve()
    candidate = (root / Path(*reference.parts)).resolve()
    if not candidate.is_relative_to(root):
        return raw, None, ["rejected formula image path outside raw bundle"]
    if not candidate.is_file():
        return raw, None, ["formula source image is missing"]
    if candidate.is_symlink():
        return raw, None, ["rejected formula image symlink"]
    return raw, str(candidate), []


def _latex_diagnostics(latex: str | None) -> list[str]:
    if latex is None:
        return ["formula image has no LaTeX transcription"]
    diagnostics: list[str] = []
    if latex.count("{") != latex.count("}"):
        diagnostics.append("unbalanced LaTeX braces retained without correction")
    if "O." in latex or "0O" in latex or "O0" in latex:
        diagnostics.append("possible O/0 OCR ambiguity retained without correction")
    if "l_" in latex or "1_" in latex:
        diagnostics.append("possible l/1 OCR ambiguity retained without correction")
    return diagnostics


def _union_bbox(values: list[MinerUBbox]) -> MinerUBbox:
    return MinerUBbox(
        x_min=min(item.x_min for item in values),
        y_min=min(item.y_min for item in values),
        x_max=max(item.x_max for item in values),
        y_max=max(item.y_max for item in values),
    )


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, '|'.join(parts)).hex}"
