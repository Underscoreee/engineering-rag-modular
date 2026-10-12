"""Safe private migration for formula block aliases created during semantic grouping."""

from __future__ import annotations

from engineering_rag.contracts.documents import ClauseContentType, ClauseGroups

from .models import FormulaGroupLineage


class FormulaReferenceMigrationError(ValueError):
    """Raised when grouping would change the meaning of an existing content reference."""


def migrate_formula_clause_references(
    clauses: ClauseGroups,
    *,
    lineage: list[FormulaGroupLineage],
    consumed_body_block_ids: set[str],
) -> ClauseGroups:
    """Map formula Block aliases and reject consumed Body references without safe semantics."""

    aliases = {item.old_block_id: item.new_block_id for item in lineage}
    migrated = clauses.model_copy(deep=True)
    for clause in [*migrated.normative, *migrated.explanations]:
        if consumed_body_block_ids.intersection(clause.source_block_ids):
            raise FormulaReferenceMigrationError(
                f"{clause.clause_id} references a consumed condition or explanation Body"
            )
        clause.source_block_ids = _replace_ids(clause.source_block_ids, aliases)
        for unit in clause.clause_content.content_units:
            if consumed_body_block_ids.intersection(unit.source_block_ids):
                raise FormulaReferenceMigrationError(
                    f"{clause.clause_id} content unit {unit.order} references a consumed Body"
                )
            referenced_aliases = aliases.keys() & set(unit.source_block_ids)
            if referenced_aliases and unit.content_type != ClauseContentType.FORMULA:
                raise FormulaReferenceMigrationError(
                    f"{clause.clause_id} content unit {unit.order} uses a formula Block "
                    f"as {unit.content_type.value}"
                )
            unit.source_block_ids = _replace_ids(unit.source_block_ids, aliases)
    return ClauseGroups.model_validate(migrated.model_dump(mode="json"))


def _replace_ids(values: list[str], aliases: dict[str, str]) -> list[str]:
    replaced: list[str] = []
    for value in values:
        target = aliases.get(value, value)
        if target not in replaced:
            replaced.append(target)
    return replaced
