"""Clause-first assembly of public Document V2.4 into Chunk V1."""

from __future__ import annotations

from engineering_rag.contracts.chunks import (
    Chunk,
    ChunkBatch,
    ChunkContentType,
    ChunkingConfig,
)
from engineering_rag.contracts.documents import (
    BlockType,
    Clause,
    ClauseContentType,
    Document,
    PageBlock,
    PageType,
)

from .identity import CHUNKING_VERSION, config_digest, stable_id
from .metadata import (
    ChunkingInputError,
    clause_sort_key,
    context_header,
    decorative_orphan_block_ids,
    section_path,
    source_refs,
    validate_config,
)
from .models import TextPiece
from .renderers import render_formula, render_table
from .splitter import count_tokens, pack_text_pieces


class ClauseFirstChunker:
    """Dependency-free implementation of the public ChunkingService Protocol."""

    def chunk(self, document: Document, config: ChunkingConfig) -> ChunkBatch:
        document = Document.model_validate(document.model_dump(mode="json"))
        config = ChunkingConfig.model_validate(config.model_dump(mode="json"))
        validate_config(config)
        digest = config_digest(config)
        chunks: list[Chunk] = []
        emitted_tables: set[str] = set()
        emitted_formula_groups: set[str] = set()
        emitted_figures: set[str] = set()
        for is_explanation, clauses in (
            (False, document.clauses.normative),
            (True, document.clauses.explanations),
        ):
            for clause in sorted(clauses, key=lambda item: clause_sort_key(document, item)):
                chunks.extend(
                    self._clause_chunks(
                        document,
                        clause,
                        config,
                        digest,
                        is_explanation=is_explanation,
                        emitted_tables=emitted_tables,
                        emitted_formula_groups=emitted_formula_groups,
                        emitted_figures=emitted_figures,
                    )
                )
        claimed = {
            block_id
            for clause in document.clauses.normative + document.clauses.explanations
            for block_id in clause.source_block_ids
        }
        chunks.extend(self._orphan_chunks(document, config, digest, claimed))
        return ChunkBatch(
            document_id=document.document_id,
            chunks=chunks,
            chunking_version=CHUNKING_VERSION,
            strategy_id=config.strategy_id,
        )

    def _clause_chunks(
        self,
        document: Document,
        clause: Clause,
        config: ChunkingConfig,
        digest: str,
        *,
        is_explanation: bool,
        emitted_tables: set[str],
        emitted_formula_groups: set[str],
        emitted_figures: set[str],
    ) -> list[Chunk]:
        path = section_path(document, clause.section_id)
        header = context_header(
            document,
            path,
            clause_number=clause.clause_number,
            is_explanation=is_explanation,
        )
        group = "explanation" if is_explanation else "normative"
        logical_id = stable_id(
            "logical-chunk",
            document.document_id,
            group,
            clause.clause_id,
            config.strategy_id,
            digest,
            CHUNKING_VERSION,
        )
        blocks = _block_registry(document)
        text_pieces: list[TextPiece] = []
        for unit in sorted(clause.clause_content.content_units, key=lambda item: item.order):
            if unit.content_type not in {ClauseContentType.BODY, ClauseContentType.LIST_ITEM}:
                continue
            for block_id in unit.source_block_ids:
                block = _required_block(blocks, block_id)
                text = block.ocr.text if block.ocr else None
                if block.block_type != BlockType.BODY or not text:
                    raise ChunkingInputError(
                        f"clause text unit {clause.clause_id} lacks Body text: {block_id}"
                    )
                text_pieces.append(TextPiece(text.strip(), (block_id,)))
        if not clause.clause_content.content_units and clause.clause_content.plain_text:
            # V2.4 permits a cached rendering without reference units. It is a
            # provenance-preserving fallback, never the preferred assembly path.
            text_pieces.append(
                TextPiece(
                    clause.clause_content.plain_text.strip(),
                    tuple(clause.source_block_ids),
                )
            )
        content_budget = max(1, config.max_tokens - count_tokens(header))
        packed = pack_text_pieces(text_pieces, content_budget)
        main_chunks = [
            _make_chunk(
                document,
                config,
                logical_id=logical_id,
                ordinal=index,
                identity_label="clause",
                content=piece.text,
                content_type=ChunkContentType.CLAUSE,
                source_block_ids=list(piece.source_block_ids),
                context=header,
                path=path,
                clause=clause,
                is_explanation=is_explanation,
            )
            for index, piece in enumerate(packed)
        ]
        parent_id = main_chunks[0].chunk_id if main_chunks else None
        atomic_chunks = self._atomic_chunks(
            document,
            clause,
            config,
            logical_id=logical_id,
            parent_id=parent_id,
            context=header,
            path=path,
            is_explanation=is_explanation,
            emitted_tables=emitted_tables,
            emitted_formula_groups=emitted_formula_groups,
            emitted_figures=emitted_figures,
        )
        return [*main_chunks, *atomic_chunks]

    def _atomic_chunks(
        self,
        document: Document,
        clause: Clause,
        config: ChunkingConfig,
        *,
        logical_id: str,
        parent_id: str | None,
        context: str,
        path: list[str],
        is_explanation: bool,
        emitted_tables: set[str],
        emitted_formula_groups: set[str],
        emitted_figures: set[str],
    ) -> list[Chunk]:
        blocks = _block_registry(document)
        tables = {table.table_id: table for table in document.tables}
        chunks: list[Chunk] = []
        ordinal = 0
        for unit in sorted(clause.clause_content.content_units, key=lambda item: item.order):
            if unit.content_type == ClauseContentType.TABLE:
                table_id = unit.table_id
                table = tables.get(table_id or "")
                if table_id is None or table is None:
                    raise ChunkingInputError(f"clause {clause.clause_id} references unknown table")
                if table_id in emitted_tables:
                    raise ChunkingInputError(f"table is referenced by multiple clauses: {table_id}")
                emitted_tables.add(table_id)
                chunks.append(
                    _make_chunk(
                        document,
                        config,
                        logical_id=logical_id,
                        ordinal=ordinal,
                        identity_label=f"table:{table_id}",
                        content=render_table(table),
                        content_type=ChunkContentType.TABLE,
                        source_block_ids=list(table.source_block_ids),
                        context=context,
                        path=path,
                        clause=clause,
                        is_explanation=is_explanation,
                        parent_chunk_id=parent_id,
                        table_id=table_id,
                    )
                )
                ordinal += 1
            elif unit.content_type == ClauseContentType.FORMULA:
                requested = set(unit.formula_ids)
                emitted_ids: set[str] = set()
                for block_id in unit.source_block_ids:
                    block = _required_block(blocks, block_id)
                    group = block.ocr.formula_group if block.ocr else None
                    if block.formula_group_id is None or group is None:
                        raise ChunkingInputError(f"formula unit lacks FormulaGroup: {block_id}")
                    group_formula_ids = [equation.formula_id for equation in group.equations]
                    if not requested.intersection(group_formula_ids):
                        continue
                    if block.formula_group_id in emitted_formula_groups:
                        emitted_ids.update(requested.intersection(group_formula_ids))
                        continue
                    emitted_formula_groups.add(block.formula_group_id)
                    emitted_ids.update(requested.intersection(group_formula_ids))
                    chunks.append(
                        _make_chunk(
                            document,
                            config,
                            logical_id=logical_id,
                            ordinal=ordinal,
                            identity_label=f"formula:{block.formula_group_id}",
                            content=render_formula(block.formula_group_id, group),
                            content_type=ChunkContentType.FORMULA,
                            source_block_ids=[block_id],
                            context=context,
                            path=path,
                            clause=clause,
                            is_explanation=is_explanation,
                            parent_chunk_id=parent_id,
                            formula_ids=group_formula_ids,
                        )
                    )
                    ordinal += 1
                if emitted_ids != requested:
                    missing = sorted(requested - emitted_ids)
                    raise ChunkingInputError(
                        f"formula unit {clause.clause_id} cannot resolve IDs: {missing}"
                    )
            elif unit.content_type == ClauseContentType.IMAGE:
                for block_id in unit.source_block_ids:
                    block = _required_block(blocks, block_id)
                    caption = block.ocr.text if block.ocr else None
                    if block.asset is None:
                        raise ChunkingInputError(f"image unit lacks asset: {block_id}")
                    figure_id = block.asset.artifact_id
                    if figure_id in emitted_figures:
                        raise ChunkingInputError(
                            f"figure is referenced by multiple clauses: {figure_id}"
                        )
                    emitted_figures.add(figure_id)
                    if not caption:
                        continue
                    chunks.append(
                        _make_chunk(
                            document,
                            config,
                            logical_id=logical_id,
                            ordinal=ordinal,
                            identity_label=f"figure:{figure_id}",
                            content=caption,
                            content_type=ChunkContentType.FIGURE,
                            source_block_ids=[block_id],
                            context=context,
                            path=path,
                            clause=clause,
                            is_explanation=is_explanation,
                            parent_chunk_id=parent_id,
                            figure_id=figure_id,
                            related_asset_ids=[figure_id],
                        )
                    )
                    ordinal += 1
        return chunks

    def _orphan_chunks(
        self,
        document: Document,
        config: ChunkingConfig,
        digest: str,
        claimed: set[str],
    ) -> list[Chunk]:
        decorative = decorative_orphan_block_ids(document)
        chunks: list[Chunk] = []
        for page in sorted(document.pages, key=lambda item: item.page_number):
            if page.page_type not in {PageType.BODY, PageType.EXPLANATION_BODY}:
                continue
            is_explanation = page.page_type == PageType.EXPLANATION_BODY
            header = context_header(
                document,
                [],
                clause_number=None,
                is_explanation=is_explanation,
            )
            budget = max(1, config.max_tokens - count_tokens(header))
            for block in sorted(page.blocks, key=lambda item: item.reading_order):
                text = block.ocr.text if block.ocr else None
                if (
                    block.block_type != BlockType.BODY
                    or block.block_id in claimed
                    or block.block_id in decorative
                    or not text
                ):
                    continue
                logical_id = stable_id(
                    "logical-chunk",
                    document.document_id,
                    "orphan",
                    block.block_id,
                    config.strategy_id,
                    digest,
                    CHUNKING_VERSION,
                )
                pieces = pack_text_pieces([TextPiece(text.strip(), (block.block_id,))], budget)
                chunks.extend(
                    _make_chunk(
                        document,
                        config,
                        logical_id=logical_id,
                        ordinal=index,
                        identity_label="paragraph",
                        content=piece.text,
                        content_type=ChunkContentType.PARAGRAPH,
                        source_block_ids=list(piece.source_block_ids),
                        context=header,
                        path=[],
                        clause=None,
                        is_explanation=is_explanation,
                    )
                    for index, piece in enumerate(pieces)
                )
        return chunks


def _make_chunk(
    document: Document,
    config: ChunkingConfig,
    *,
    logical_id: str,
    ordinal: int,
    identity_label: str,
    content: str,
    content_type: ChunkContentType,
    source_block_ids: list[str],
    context: str,
    path: list[str],
    clause: Clause | None,
    is_explanation: bool,
    parent_chunk_id: str | None = None,
    table_id: str | None = None,
    figure_id: str | None = None,
    formula_ids: list[str] | None = None,
    related_asset_ids: list[str] | None = None,
) -> Chunk:
    refs = source_refs(document, source_block_ids)
    embedding_text = f"{context}\n\n{content}" if context else content
    token_count = count_tokens(embedding_text)
    chunk_id = stable_id(
        "chunk",
        logical_id,
        identity_label,
        str(ordinal),
        *source_block_ids,
    )
    return Chunk(
        chunk_id=chunk_id,
        logical_chunk_id=logical_id,
        document_id=document.document_id,
        content=content,
        context_header=context,
        embedding_text=embedding_text,
        token_count=token_count,
        content_type=content_type,
        page_start=min(ref.page_number for ref in refs),
        page_end=max(ref.page_number for ref in refs),
        source_refs=refs,
        source_block_ids=source_block_ids,
        standard=document.standard,
        section_path=path,
        section_id=clause.section_id if clause else None,
        clause_id=clause.clause_id if clause else None,
        clause_number=clause.clause_number if clause else None,
        is_explanation=is_explanation,
        is_mandatory=clause.is_mandatory if clause else None,
        parent_chunk_id=parent_chunk_id,
        table_id=table_id,
        figure_id=figure_id,
        formula_ids=formula_ids or [],
        related_asset_ids=related_asset_ids or [],
        chunking_version=CHUNKING_VERSION,
        exceeds_max_tokens=token_count > config.max_tokens,
    )


def _block_registry(document: Document) -> dict[str, PageBlock]:
    return {block.block_id: block for page in document.pages for block in page.blocks}


def _required_block(blocks: dict[str, PageBlock], block_id: str) -> PageBlock:
    block = blocks.get(block_id)
    if block is None:
        raise ChunkingInputError(f"unknown source block: {block_id}")
    return block
