"""Conservative Section/Clause assembly into frozen Document V2.4."""

from __future__ import annotations

import re
from collections.abc import Iterable
from uuid import NAMESPACE_URL, uuid5

from engineering_rag.contracts.documents import (
    PLAIN_TEXT_RENDERER_VERSION,
    BlockType,
    Clause,
    ClauseContent,
    ClauseContentType,
    ClauseContentUnit,
    ClauseGroups,
    ContentGroup,
    Document,
    LogicalTable,
    Page,
    PageBlock,
    PageType,
    RecognitionStatus,
    Section,
    SectionType,
    derive_clause_plain_text,
)

from .models import (
    PendingSemanticRelation,
    SemanticAssemblyResult,
    SemanticLineage,
    SemanticPendingLinks,
    SemanticSourceEvidence,
)
from .page_zone_classifier import classify_pages

SEMANTIC_ASSEMBLER_VERSION = "1.5.1"
_CLAUSE = re.compile(r"^\s*(?P<number>\d+\.\d+\.\d+)(?![-.\d])\s*")
_SECTION = re.compile(r"^\s*(?P<number>\d+\.\d+)\s+(?P<title>.+?)\s*$")
_CHAPTER = re.compile(r"^\s*(?P<number>\d+)\s*(?P<title>[\u4e00-\u9fff].+?)\s*$")
_LIST_ITEM = re.compile(r"^\s*(?P<label>(?:\d+[）)]?|[（(]\d+[）)]))\s*")
_PAGE_NUMBER = re.compile(r"^\s*\d{1,4}\s*$")


def assemble_semantics(
    document: Document,
    *,
    source_indexes: dict[str, int] | None = None,
    incomplete_block_ids: set[str] | None = None,
    known_explanation_cover_page: int | None = None,
) -> SemanticAssemblyResult:
    """Build conservative semantic views without changing the frozen public contract."""

    source_indexes = source_indexes or {}
    incomplete_block_ids = incomplete_block_ids or set()
    working = document.model_copy(deep=True)
    working.processing = working.processing.model_copy(
        update={"parser_version": SEMANTIC_ASSEMBLER_VERSION}
    )
    working.pages, page_reasons = classify_pages(
        working.pages, known_explanation_cover_page=known_explanation_cover_page
    )
    records: list[SemanticSourceEvidence] = []
    pending: list[PendingSemanticRelation] = []
    sections, section_blocks = _build_sections(working, records, pending, source_indexes)
    working.sections = sections
    clauses = _build_clauses(
        working,
        section_blocks=section_blocks,
        records=records,
        pending=pending,
        source_indexes=source_indexes,
        incomplete_block_ids=incomplete_block_ids,
    )
    working.clauses = _link_explanations(clauses, pending)
    working = Document.model_validate(working.model_dump(mode="json"))
    working = _populate_plain_text(working, incomplete_block_ids)
    round_tripped = Document.model_validate_json(working.model_dump_json())
    diagnostics = [f"page_{number}:{reason}" for number, reason in sorted(page_reasons.items())]
    lineage = SemanticLineage(
        algorithm_version=SEMANTIC_ASSEMBLER_VERSION,
        source_pdf_sha256=working.source_file.sha256 or "0" * 64,
        source_records=records,
        diagnostics=diagnostics,
    )
    links = SemanticPendingLinks(
        algorithm_version=SEMANTIC_ASSEMBLER_VERSION,
        relations=pending,
    )
    return SemanticAssemblyResult(
        document=round_tripped,
        lineage=lineage,
        pending_links=links,
        statistics={
            "pages": len(round_tripped.pages),
            "sections": len(round_tripped.sections),
            "normative_clauses": len(round_tripped.clauses.normative),
            "explanation_clauses": len(round_tripped.clauses.explanations),
            "pending_relations": len(pending),
        },
    )


def _build_sections(
    document: Document,
    records: list[SemanticSourceEvidence],
    pending: list[PendingSemanticRelation],
    source_indexes: dict[str, int],
) -> tuple[list[Section], set[str]]:
    sections: list[Section] = []
    by_group_number: dict[tuple[ContentGroup, str], Section] = {}
    consumed_blocks: set[str] = set()
    for page in sorted(document.pages, key=lambda item: item.page_number):
        group = _page_group(page.page_type)
        if group is None:
            continue
        for block in sorted(page.blocks, key=lambda item: item.reading_order):
            if block.block_type != BlockType.TITLE or block.ocr is None or not block.ocr.text:
                continue
            match = _section_heading(block.ocr.text)
            if match is None:
                records.append(
                    _record(
                        document,
                        page,
                        block,
                        source_indexes,
                        kind="unmodeled_title",
                        label=block.ocr.text,
                        group=group,
                        decision="retained_in_page_view",
                        reason="title_is_not_a_reliable_chapter_or_section_heading",
                    )
                )
                continue
            number, title, level = match
            key = (group, number)
            if key in by_group_number:
                consumed_blocks.add(block.block_id)
                continue
            parent: Section | None = None
            if level == 2:
                parent = by_group_number.get((group, number.split(".", 1)[0]))
                if parent is None:
                    pending.append(
                        PendingSemanticRelation(
                            relation_type="section_parent",
                            source_id=block.block_id,
                            physical_pages=[page.page_number],
                            reason="numbered_section_has_no_confirmed_chapter_in_loaded_pages",
                            evidence_block_ids=[block.block_id],
                        )
                    )
                    continue
            path = [number] if parent is None else [*parent.structure_path, number]
            section = Section(
                section_id=_stable_id(
                    "section", document.document_id, group.value, number, block.block_id
                ),
                number=number,
                title=title,
                section_type=(
                    SectionType.EXPLANATION
                    if group == ContentGroup.EXPLANATION
                    else SectionType.CHAPTER
                    if level == 1
                    else SectionType.SECTION
                ),
                content_group=group,
                parent_section_id=parent.section_id if parent else None,
                structure_path=path,
            )
            sections.append(section)
            by_group_number[key] = section
            consumed_blocks.add(block.block_id)
            records.append(
                _record(
                    document,
                    page,
                    block,
                    source_indexes,
                    kind="section_heading",
                    label=number,
                    group=group,
                    decision="consumed_as_section",
                    reason="numbered_title_block_with_valid_hierarchy",
                    consumed_by=[section.section_id],
                )
            )
    return sections, consumed_blocks


def _build_clauses(
    document: Document,
    *,
    section_blocks: set[str],
    records: list[SemanticSourceEvidence],
    pending: list[PendingSemanticRelation],
    source_indexes: dict[str, int],
    incomplete_block_ids: set[str],
) -> ClauseGroups:
    normative: list[Clause] = []
    explanations: list[Clause] = []
    table_registry = {table.table_id: table for table in document.tables}
    block_pages = {
        block.block_id: page.page_number for page in document.pages for block in page.blocks
    }
    open_clause: _ClauseDraft | None = None
    previous_page: int | None = None
    previous_group: ContentGroup | None = None
    used_table_ids: set[str] = set()
    for page in sorted(document.pages, key=lambda item: item.page_number):
        group = _page_group(page.page_type)
        if group is None:
            if open_clause is not None:
                open_clause.incomplete_end = True
                _finish_clause(open_clause, normative, explanations)
                open_clause = None
            if page.page_type == PageType.UNKNOWN:
                _queue_unclassified_page(
                    document,
                    page,
                    records=records,
                    pending=pending,
                    source_indexes=source_indexes,
                )
            previous_page = page.page_number
            previous_group = None
            continue
        if (
            previous_page is not None
            and (page.page_number != previous_page + 1 or group != previous_group)
            and open_clause is not None
        ):
            open_clause.incomplete_end = True
            _finish_clause(open_clause, normative, explanations)
            open_clause = None
        for block in sorted(page.blocks, key=lambda item: item.reading_order):
            if block.block_id in section_blocks:
                if open_clause is not None:
                    _finish_clause(open_clause, normative, explanations)
                    open_clause = None
                continue
            text = block.ocr.text if block.ocr else None
            if _is_page_footer(page, block, text):
                records.append(
                    _record(
                        document,
                        page,
                        block,
                        source_indexes,
                        kind="printed_page_label",
                        label=text,
                        group=group,
                        decision="excluded_from_clause",
                        reason="numeric_only_block_in_page_footer_zone",
                    )
                )
                continue
            clause_match = _CLAUSE.match(text or "") if block.block_type == BlockType.BODY else None
            if clause_match:
                if open_clause is not None:
                    _finish_clause(open_clause, normative, explanations)
                number = clause_match.group("number")
                section = _section_for_clause(document.sections, group, number)
                if section is None:
                    pending.append(
                        PendingSemanticRelation(
                            relation_type="clause_section",
                            source_id=block.block_id,
                            physical_pages=[page.page_number],
                            reason="clause_has_no_confirmed_section_in_loaded_pages",
                            evidence_block_ids=[block.block_id],
                        )
                    )
                    records.append(
                        _record(
                            document,
                            page,
                            block,
                            source_indexes,
                            kind="clause_candidate",
                            label=number,
                            group=group,
                            decision="pending",
                            reason="clause_has_no_confirmed_section_in_loaded_pages",
                        )
                    )
                    open_clause = None
                    continue
                open_clause = _ClauseDraft(
                    document, group, number, section.section_id, block.block_id
                )
            if open_clause is None:
                if block.block_type in {BlockType.BODY, BlockType.TABLE, BlockType.FORMULA}:
                    pending.append(
                        PendingSemanticRelation(
                            relation_type="orphan_content",
                            source_id=block.block_id,
                            physical_pages=[page.page_number],
                            reason="no_reliable_preceding_clause_start_in_loaded_contiguous_pages",
                            evidence_block_ids=[block.block_id],
                        )
                    )
                    records.append(
                        _record(
                            document,
                            page,
                            block,
                            source_indexes,
                            kind="orphan_content",
                            label=text,
                            group=group,
                            decision="pending",
                            reason="no_reliable_preceding_clause_start_in_loaded_pages",
                        )
                    )
                continue
            unit = _unit_for_block(
                block,
                table_registry,
                used_table_ids,
                is_clause_start=clause_match is not None,
            )
            if unit is None:
                if block.block_type == BlockType.TABLE and block.block_id in open_clause.source_ids:
                    records.append(
                        _record(
                            document,
                            page,
                            block,
                            source_indexes,
                            kind="clause_table_fragment",
                            label=open_clause.number,
                            group=group,
                            decision="consumed_as_clause_content",
                            reason="referenced_by_existing_cross_page_logical_table_unit",
                            consumed_by=[open_clause.clause_id],
                        )
                    )
                    continue
                records.append(
                    _record(
                        document,
                        page,
                        block,
                        source_indexes,
                        kind="unconsumed_block",
                        label=text,
                        group=group,
                        decision="retained_in_page_view",
                        reason="block_cannot_be_referenced_without_inventing_contract_payload",
                    )
                )
                continue
            open_clause.add(unit, block_pages)
            if block.block_id in incomplete_block_ids:
                open_clause.incomplete_source = True
            records.append(
                _record(
                    document,
                    page,
                    block,
                    source_indexes,
                    kind=f"clause_{unit.content_type.value}",
                    label=open_clause.number,
                    group=group,
                    decision="consumed_as_clause_content",
                    reason="ordered_block_between_confirmed_clause_boundaries",
                    consumed_by=[open_clause.clause_id],
                )
            )
        previous_page = page.page_number
        previous_group = group
    if open_clause is not None:
        open_clause.incomplete_end = True
        _finish_clause(open_clause, normative, explanations)
    return ClauseGroups(normative=normative, explanations=explanations)


class _ClauseDraft:
    def __init__(
        self,
        document: Document,
        group: ContentGroup,
        number: str,
        section_id: str,
        source_anchor_block_id: str,
    ):
        self.group = group
        self.number = number
        self.section_id = section_id
        self.clause_id = _stable_id(
            "clause", document.document_id, group.value, number, source_anchor_block_id
        )
        self.units: list[ClauseContentUnit] = []
        self.source_ids: list[str] = []
        self.pages: list[int] = []
        self.incomplete_source = False
        self.incomplete_end = False

    def add(self, unit: ClauseContentUnit, block_pages: dict[str, int]) -> None:
        unit = unit.model_copy(update={"order": len(self.units)})
        self.units.append(unit)
        for block_id in unit.source_block_ids:
            if block_id not in self.source_ids:
                self.source_ids.append(block_id)
            page = block_pages[block_id]
            if page not in self.pages:
                self.pages.append(page)

    def build(self) -> Clause:
        warning = None
        if self.incomplete_source or self.incomplete_end:
            warning = "partial source boundary; plain_text cache intentionally omitted"
        return Clause(
            clause_id=self.clause_id,
            clause_number=self.number,
            section_id=self.section_id,
            clause_content=ClauseContent(
                content_units=self.units,
                transcription_status=RecognitionStatus.UNVERIFIED,
                review_warning=warning,
            ),
            page_start=min(self.pages),
            page_end=max(self.pages),
            source_block_ids=self.source_ids,
            is_mandatory=None,
            mandatory_evidence=[],
        )


def _finish_clause(
    draft: _ClauseDraft, normative: list[Clause], explanations: list[Clause]
) -> None:
    if not draft.units:
        return
    target = normative if draft.group == ContentGroup.NORMATIVE else explanations
    target.append(draft.build())


def _unit_for_block(
    block: PageBlock,
    tables: dict[str, LogicalTable],
    used_table_ids: set[str],
    *,
    is_clause_start: bool,
) -> ClauseContentUnit | None:
    if block.block_type == BlockType.BODY:
        text = block.ocr.text if block.ocr else None
        item = None if is_clause_start else _LIST_ITEM.match(text or "")
        return ClauseContentUnit(
            order=0,
            content_type=(ClauseContentType.LIST_ITEM if item else ClauseContentType.BODY),
            source_block_ids=[block.block_id],
            list_item_label=item.group("label") if item else None,
        )
    if block.block_type == BlockType.TABLE and block.table_id is not None:
        if block.table_id in used_table_ids:
            return None
        table = tables.get(block.table_id)
        if table is None:
            return None
        used_table_ids.add(block.table_id)
        return ClauseContentUnit(
            order=0,
            content_type=ClauseContentType.TABLE,
            source_block_ids=list(table.source_block_ids),
            table_id=block.table_id,
        )
    if block.block_type == BlockType.FORMULA:
        group = block.ocr.formula_group if block.ocr else None
        if group is None:
            return None
        return ClauseContentUnit(
            order=0,
            content_type=ClauseContentType.FORMULA,
            source_block_ids=[block.block_id],
            formula_ids=[equation.formula_id for equation in group.equations],
        )
    if block.block_type == BlockType.IMAGE and block.asset is not None:
        return ClauseContentUnit(
            order=0,
            content_type=ClauseContentType.IMAGE,
            source_block_ids=[block.block_id],
            asset_id=block.asset.artifact_id,
        )
    return None


def _link_explanations(
    clauses: ClauseGroups, pending: list[PendingSemanticRelation]
) -> ClauseGroups:
    normative: dict[str, list[Clause]] = {}
    for clause in clauses.normative:
        normative.setdefault(clause.clause_number, []).append(clause)
    explanations: list[Clause] = []
    for clause in clauses.explanations:
        matches = normative.get(clause.clause_number, [])
        if len(matches) == 1:
            explanations.append(
                clause.model_copy(update={"explains_clause_id": matches[0].clause_id})
            )
        else:
            pending.append(
                PendingSemanticRelation(
                    relation_type="explanation_to_normative",
                    source_id=clause.clause_id,
                    candidate_target_ids=[item.clause_id for item in matches],
                    physical_pages=list(range(clause.page_start, clause.page_end + 1)),
                    reason=(
                        "normative_clause_not_loaded"
                        if not matches
                        else "multiple_normative_matches"
                    ),
                    evidence_block_ids=clause.source_block_ids,
                )
            )
            explanations.append(clause)
    return ClauseGroups(normative=clauses.normative, explanations=explanations)


def _populate_plain_text(document: Document, incomplete_block_ids: set[str]) -> Document:
    candidate = document.model_copy(deep=True)
    for group_name in ("normative", "explanations"):
        clauses: list[Clause] = getattr(candidate.clauses, group_name)
        for index, clause in enumerate(clauses):
            if (
                clause.clause_content.review_warning
                or set(clause.source_block_ids) & incomplete_block_ids
            ):
                continue
            rendered = derive_clause_plain_text(candidate, clause)
            if rendered is None:
                continue
            text, digest = rendered
            content = clause.clause_content.model_copy(
                update={
                    "plain_text": text,
                    "plain_text_renderer_version": PLAIN_TEXT_RENDERER_VERSION,
                    "plain_text_source_digest": digest,
                }
            )
            clauses[index] = clause.model_copy(update={"clause_content": content})
    return Document.model_validate(candidate.model_dump(mode="json"))


def _section_heading(text: str) -> tuple[str, str, int] | None:
    if "\\" in text or "_{" in text.replace(" ", ""):
        return None
    section = _SECTION.match(text)
    if section:
        return section.group("number"), section.group("title"), 2
    chapter = _CHAPTER.match(text)
    if chapter:
        return chapter.group("number"), chapter.group("title"), 1
    return None


def _section_for_clause(
    sections: Iterable[Section], group: ContentGroup, number: str
) -> Section | None:
    prefixes = [".".join(number.split(".")[:length]) for length in (2, 1)]
    matches = [
        section
        for prefix in prefixes
        for section in sections
        if section.content_group == group and section.number == prefix
    ]
    return matches[0] if matches else None


def _page_group(page_type: PageType) -> ContentGroup | None:
    if page_type == PageType.BODY:
        return ContentGroup.NORMATIVE
    if page_type == PageType.EXPLANATION_BODY:
        return ContentGroup.EXPLANATION
    return None


def _is_page_footer(page: Page, block: PageBlock, text: str | None) -> bool:
    return bool(text and _PAGE_NUMBER.fullmatch(text) and block.bbox.y_min >= page.height * 0.82)


def _queue_unclassified_page(
    document: Document,
    page: Page,
    *,
    records: list[SemanticSourceEvidence],
    pending: list[PendingSemanticRelation],
    source_indexes: dict[str, int],
) -> None:
    """Keep one auditable retry relation for substantive content on an unknown page."""

    evidence_blocks: list[PageBlock] = []
    for block in sorted(page.blocks, key=lambda item: item.reading_order):
        text = block.ocr.text if block.ocr else None
        if _is_page_footer(page, block, text):
            records.append(
                _record(
                    document,
                    page,
                    block,
                    source_indexes,
                    kind="printed_page_label",
                    label=text,
                    group=None,
                    decision="excluded_from_semantic_retry",
                    reason="numeric_only_block_in_page_footer_zone",
                )
            )
            continue
        if not _is_substantive_candidate(block, text):
            continue
        evidence_blocks.append(block)
        records.append(
            _record(
                document,
                page,
                block,
                source_indexes,
                kind="unclassified_content",
                label=text,
                group=None,
                decision="pending",
                reason="page_zone_is_unknown_without_verified_normative_or_explanation_context",
            )
        )
    if not evidence_blocks:
        return
    block_ids = [block.block_id for block in evidence_blocks]
    pending.append(
        PendingSemanticRelation(
            relation_type="unclassified_content",
            source_id=_stable_id(
                "pending-unclassified-page",
                document.document_id,
                str(page.page_number),
                *block_ids,
            ),
            physical_pages=[page.page_number],
            reason="page_type_ambiguous; content retained for replay with adjacent-page evidence",
            evidence_block_ids=block_ids,
            source_bboxes={
                block.block_id: block.bbox.model_dump(mode="json") for block in evidence_blocks
            },
            blocking_conditions=[
                "no_verified_normative_zone_evidence",
                "no_verified_explanation_zone_evidence",
                "no_reliable_preceding_clause_boundary",
            ],
        )
    )


def _is_substantive_candidate(block: PageBlock, text: str | None) -> bool:
    if block.block_type in {BlockType.TITLE, BlockType.BODY}:
        return bool(text and text.strip())
    if block.block_type == BlockType.TABLE:
        return block.table_id is not None
    if block.block_type == BlockType.FORMULA:
        return block.formula_group_id is not None
    return block.block_type == BlockType.IMAGE and block.asset is not None


def _record(
    document: Document,
    page: Page,
    block: PageBlock,
    source_indexes: dict[str, int],
    *,
    kind: str,
    label: str | None,
    group: ContentGroup | None,
    decision: str,
    reason: str,
    consumed_by: list[str] | None = None,
) -> SemanticSourceEvidence:
    return SemanticSourceEvidence(
        source_pdf_sha256=document.source_file.sha256 or "0" * 64,
        physical_page=page.page_number,
        source_block_id=block.block_id,
        source_index=source_indexes.get(block.block_id),
        source_bbox=block.bbox.model_dump(mode="json"),
        raw_text=block.ocr.text if block.ocr else None,
        candidate_kind=kind,
        candidate_label=label,
        content_group=group.value if group is not None else None,
        decision=decision,
        decision_reason=reason,
        consumed_by=consumed_by or [],
    )


def _stable_id(prefix: str, *parts: str) -> str:
    return f"{prefix}-{uuid5(NAMESPACE_URL, '|'.join(parts)).hex}"
