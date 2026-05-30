import hashlib
from datetime import datetime, timezone
from typing import Union
from difflib import SequenceMatcher

from .models import (
    Column, Schema, SchemaDiff, SchemaChange, ChangeType, BreakingStatus,
    MigrationPlan, MigrationStep, IrreversibleMigration, ProvenanceRecord, DType,
    ColumnConstraints,
)

# dtype widening: going from key -> value is non-breaking (wider type accepts more values)
_WIDENS_TO = {
    DType.INT: {DType.FLOAT, DType.STRING},
    DType.FLOAT: {DType.STRING},
    DType.DATE: {DType.TIMESTAMP, DType.STRING},
    DType.BOOL: {DType.INT, DType.FLOAT, DType.STRING},
}


def _is_widening(old: DType, new: DType) -> bool:
    return new in _WIDENS_TO.get(old, set())


def _name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _find_renames(removed: list[Column], added: list[Column], threshold: float = 0.6) -> list[tuple[Column, Column]]:
    """
    Match removed columns to added columns by name similarity.
    Uses a greedy approach: pick the best match above threshold, then remove both.
    Justified: column renames are usually minor edits (e.g. user_id -> userId, created -> created_at).
    """
    pairs = []
    used_added = set()
    for r in removed:
        best_score = threshold
        best_match = None
        for a in added:
            if id(a) in used_added:
                continue
            score = _name_similarity(r.name, a.name)
            if score > best_score:
                best_score = score
                best_match = a
        if best_match:
            pairs.append((r, best_match))
            used_added.add(id(best_match))
    return pairs


def _constraint_tightened(old: ColumnConstraints | None, new: ColumnConstraints | None) -> bool:
    """Tightening: new constraints are more restrictive than old."""
    if new is None:
        return False
    if old is None:
        return True  # gaining constraints is tightening
    # min_value increased
    if new.min_value is not None and (old.min_value is None or new.min_value > old.min_value):
        return True
    # max_value decreased
    if new.max_value is not None and (old.max_value is None or new.max_value < old.max_value):
        return True
    # allowed_values became smaller
    if new.allowed_values is not None and (old.allowed_values is None or set(new.allowed_values) < set(old.allowed_values)):
        return True
    return False


def _constraint_loosened(old: ColumnConstraints | None, new: ColumnConstraints | None) -> bool:
    """Loosening: new constraints are less restrictive than old."""
    if old is None:
        return False
    if new is None:
        return True  # losing all constraints is loosening
    if old.min_value is not None and (new.min_value is None or new.min_value < old.min_value):
        return True
    if old.max_value is not None and (new.max_value is None or new.max_value > old.max_value):
        return True
    if old.allowed_values is not None and (new.allowed_values is None or set(new.allowed_values) > set(old.allowed_values)):
        return True
    return False


def diff_schema(old: Schema, new: Schema) -> SchemaDiff:
    old_map = old.column_map()
    new_map = new.column_map()

    old_names = set(old_map)
    new_names = set(new_map)

    removed_names = old_names - new_names
    added_names = new_names - old_names
    common_names = old_names & new_names

    removed_cols = [old_map[n] for n in removed_names]
    added_cols = [new_map[n] for n in added_names]

    changes: list[SchemaChange] = []

    # detect renames before treating leftovers as pure add/remove
    renames = _find_renames(removed_cols, added_cols)
    renamed_old = {r.name for r, _ in renames}
    renamed_new = {a.name for _, a in renames}

    for old_col, new_col in renames:
        changes.append(SchemaChange(
            change_type=ChangeType.COLUMN_RENAMED,
            breaking=BreakingStatus.NON_BREAKING,
            column_name=old_col.name,
            old_value=old_col.name,
            new_value=new_col.name,
            description=f"Column renamed from '{old_col.name}' to '{new_col.name}'",
        ))

    # pure removals (not explained by a rename)
    for col in removed_cols:
        if col.name in renamed_old:
            continue
        changes.append(SchemaChange(
            change_type=ChangeType.COLUMN_REMOVED,
            breaking=BreakingStatus.BREAKING,
            column_name=col.name,
            old_value=col.name,
            new_value=None,
            description=f"Column '{col.name}' removed",
        ))

    # pure additions
    for col in added_cols:
        if col.name in renamed_new:
            continue
        breaking = BreakingStatus.NON_BREAKING if col.nullable else BreakingStatus.BREAKING
        changes.append(SchemaChange(
            change_type=ChangeType.COLUMN_ADDED,
            breaking=breaking,
            column_name=col.name,
            old_value=None,
            new_value=col.name,
            description=f"Column '{col.name}' added ({'nullable' if col.nullable else 'NOT NULL — breaking'})",
        ))

    # modifications to existing columns
    for name in common_names:
        oc = old_map[name]
        nc = new_map[name]

        if oc.dtype != nc.dtype:
            widening = _is_widening(oc.dtype, nc.dtype)
            changes.append(SchemaChange(
                change_type=ChangeType.TYPE_CHANGED,
                breaking=BreakingStatus.NON_BREAKING if widening else BreakingStatus.BREAKING,
                column_name=name,
                old_value=oc.dtype.value,
                new_value=nc.dtype.value,
                description=f"Column '{name}' type changed {oc.dtype.value} → {nc.dtype.value} ({'widening' if widening else 'narrowing — breaking'})",
            ))

        if oc.nullable != nc.nullable:
            # nullable=True → False is breaking (data may have NULLs)
            breaking = BreakingStatus.BREAKING if (oc.nullable and not nc.nullable) else BreakingStatus.NON_BREAKING
            changes.append(SchemaChange(
                change_type=ChangeType.NULLABLE_CHANGED,
                breaking=breaking,
                column_name=name,
                old_value=oc.nullable,
                new_value=nc.nullable,
                description=f"Column '{name}' nullable changed {oc.nullable} → {nc.nullable}",
            ))

        if _constraint_tightened(oc.constraints, nc.constraints):
            changes.append(SchemaChange(
                change_type=ChangeType.CONSTRAINT_TIGHTENED,
                breaking=BreakingStatus.BREAKING,
                column_name=name,
                old_value=oc.constraints.model_dump() if oc.constraints else None,
                new_value=nc.constraints.model_dump() if nc.constraints else None,
                description=f"Column '{name}' constraints tightened (breaking)",
            ))
        elif _constraint_loosened(oc.constraints, nc.constraints):
            changes.append(SchemaChange(
                change_type=ChangeType.CONSTRAINT_LOOSENED,
                breaking=BreakingStatus.NON_BREAKING,
                column_name=name,
                old_value=oc.constraints.model_dump() if oc.constraints else None,
                new_value=nc.constraints.model_dump() if nc.constraints else None,
                description=f"Column '{name}' constraints loosened (non-breaking)",
            ))

    breaking_count = sum(1 for c in changes if c.breaking == BreakingStatus.BREAKING)
    non_breaking_count = len(changes) - breaking_count

    return SchemaDiff(
        old_schema_name=old.name,
        new_schema_name=new.name,
        changes=changes,
        breaking_count=breaking_count,
        non_breaking_count=non_breaking_count,
    )


def plan_migration(diff: SchemaDiff) -> MigrationPlan:
    steps = []
    is_reversible = True
    table = diff.new_schema_name

    for change in diff.changes:
        if change.change_type == ChangeType.COLUMN_ADDED:
            null_clause = "" if change.new_value and True else " NOT NULL"
            steps.append(MigrationStep(
                description=change.description,
                sql=f"ALTER TABLE {table} ADD COLUMN {change.new_value} TEXT;",
                reversible=True,
            ))
        elif change.change_type == ChangeType.COLUMN_REMOVED:
            steps.append(MigrationStep(
                description=change.description,
                sql=f"ALTER TABLE {table} DROP COLUMN {change.column_name};",
                reversible=False,
            ))
            is_reversible = False
        elif change.change_type == ChangeType.COLUMN_RENAMED:
            steps.append(MigrationStep(
                description=change.description,
                sql=f"ALTER TABLE {table} RENAME COLUMN {change.old_value} TO {change.new_value};",
                reversible=True,
            ))
        elif change.change_type == ChangeType.TYPE_CHANGED:
            narrowing = change.breaking == BreakingStatus.BREAKING
            steps.append(MigrationStep(
                description=change.description,
                sql=f"ALTER TABLE {table} ALTER COLUMN {change.column_name} TYPE {change.new_value};",
                reversible=not narrowing,
            ))
            if narrowing:
                is_reversible = False
        elif change.change_type == ChangeType.NULLABLE_CHANGED:
            if change.new_value is False:
                steps.append(MigrationStep(
                    description=change.description,
                    sql=f"ALTER TABLE {table} ALTER COLUMN {change.column_name} SET NOT NULL;",
                    reversible=False,
                ))
                is_reversible = False
            else:
                steps.append(MigrationStep(
                    description=change.description,
                    sql=f"ALTER TABLE {table} ALTER COLUMN {change.column_name} DROP NOT NULL;",
                    reversible=True,
                ))
        elif change.change_type in (ChangeType.CONSTRAINT_TIGHTENED, ChangeType.CONSTRAINT_LOOSENED):
            steps.append(MigrationStep(
                description=change.description,
                sql=f"-- Constraint change on {change.column_name}: manual migration required",
                reversible=change.change_type == ChangeType.CONSTRAINT_LOOSENED,
            ))
            if change.change_type == ChangeType.CONSTRAINT_TIGHTENED:
                is_reversible = False

    return MigrationPlan(steps=steps, is_reversible=is_reversible, diff=diff)


def reverse(plan: MigrationPlan) -> Union[MigrationPlan, IrreversibleMigration]:
    if not plan.is_reversible:
        return IrreversibleMigration(
            reason="Plan contains irreversible steps (column removal, type narrowing, or NOT NULL constraint)",
            plan=plan,
        )

    reversed_steps = []
    table = plan.diff.old_schema_name

    for change in reversed(plan.diff.changes):
        if change.change_type == ChangeType.COLUMN_ADDED:
            reversed_steps.append(MigrationStep(
                description=f"Reverse: remove added column '{change.new_value}'",
                sql=f"ALTER TABLE {table} DROP COLUMN {change.new_value};",
                reversible=True,
            ))
        elif change.change_type == ChangeType.COLUMN_RENAMED:
            reversed_steps.append(MigrationStep(
                description=f"Reverse: rename '{change.new_value}' back to '{change.old_value}'",
                sql=f"ALTER TABLE {table} RENAME COLUMN {change.new_value} TO {change.old_value};",
                reversible=True,
            ))
        elif change.change_type == ChangeType.TYPE_CHANGED:
            reversed_steps.append(MigrationStep(
                description=f"Reverse: revert type of '{change.column_name}' to {change.old_value}",
                sql=f"ALTER TABLE {table} ALTER COLUMN {change.column_name} TYPE {change.old_value};",
                reversible=True,
            ))
        elif change.change_type == ChangeType.NULLABLE_CHANGED:
            if change.old_value is True:
                sql = f"ALTER TABLE {table} ALTER COLUMN {change.column_name} DROP NOT NULL;"
            else:
                sql = f"ALTER TABLE {table} ALTER COLUMN {change.column_name} SET NOT NULL;"
            reversed_steps.append(MigrationStep(description=f"Reverse: revert nullable on '{change.column_name}'", sql=sql, reversible=True))
        elif change.change_type == ChangeType.CONSTRAINT_LOOSENED:
            reversed_steps.append(MigrationStep(
                description=f"Reverse: re-tighten constraint on '{change.column_name}'",
                sql=f"-- Re-apply constraint on {change.column_name}",
                reversible=True,
            ))

    reverse_diff = SchemaDiff(
        old_schema_name=plan.diff.new_schema_name,
        new_schema_name=plan.diff.old_schema_name,
        changes=[],
        breaking_count=0,
        non_breaking_count=0,
    )
    return MigrationPlan(steps=reversed_steps, is_reversible=True, diff=reverse_diff)


def provenance(plan: MigrationPlan) -> ProvenanceRecord:
    old_hash = hashlib.sha256(plan.diff.old_schema_name.encode()).hexdigest()
    new_hash = hashlib.sha256(plan.diff.new_schema_name.encode()).hexdigest()
    ts = "2026-01-01T00:00:00Z"  # fixed so same diff always produces same hash

    body = (
        old_hash
        + new_hash
        + "".join(c.model_dump_json() for c in plan.diff.changes)
        + str(plan.diff.breaking_count)
        + str(plan.is_reversible)
        + ts
    )
    prov_hash = hashlib.sha256(body.encode()).hexdigest()

    return ProvenanceRecord(
        old_schema_hash=old_hash,
        new_schema_hash=new_hash,
        changes=plan.diff.changes,
        breaking_count=plan.diff.breaking_count,
        reversibility="reversible" if plan.is_reversible else "irreversible",
        timestamp=ts,
        provenance_hash=prov_hash,
    )
