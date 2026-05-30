import pytest
from schema_diff import (
    Column, Schema, DType, ColumnConstraints,
    SchemaDiff, ChangeType, BreakingStatus,
    MigrationPlan, IrreversibleMigration, ProvenanceRecord,
    diff_schema, plan_migration, reverse, provenance,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def col(name, dtype=DType.STRING, nullable=True, constraints=None):
    return Column(name=name, dtype=dtype, nullable=nullable, constraints=constraints)


def schema(name, columns):
    return Schema(name=name, columns=columns)


def change_types(diff: SchemaDiff) -> set:
    return {c.change_type for c in diff.changes}


def breaking_changes(diff: SchemaDiff):
    return [c for c in diff.changes if c.breaking == BreakingStatus.BREAKING]


def non_breaking_changes(diff: SchemaDiff):
    return [c for c in diff.changes if c.breaking == BreakingStatus.NON_BREAKING]


# ── column added ──────────────────────────────────────────────────────────────

def test_nullable_column_added_is_non_breaking():
    old = schema("t", [col("id", DType.INT)])
    new = schema("t", [col("id", DType.INT), col("notes", DType.STRING, nullable=True)])
    diff = diff_schema(old, new)
    c = next(c for c in diff.changes if c.change_type == ChangeType.COLUMN_ADDED)
    assert c.breaking == BreakingStatus.NON_BREAKING


def test_non_nullable_column_added_is_breaking():
    old = schema("t", [col("id", DType.INT)])
    new = schema("t", [col("id", DType.INT), col("required_field", DType.STRING, nullable=False)])
    diff = diff_schema(old, new)
    c = next(c for c in diff.changes if c.change_type == ChangeType.COLUMN_ADDED)
    assert c.breaking == BreakingStatus.BREAKING


# ── column removed ────────────────────────────────────────────────────────────

def test_column_removed_is_breaking():
    old = schema("t", [col("id", DType.INT), col("extra", DType.STRING)])
    new = schema("t", [col("id", DType.INT)])
    diff = diff_schema(old, new)
    c = next(c for c in diff.changes if c.change_type == ChangeType.COLUMN_REMOVED)
    assert c.breaking == BreakingStatus.BREAKING


# ── column renamed ────────────────────────────────────────────────────────────

def test_column_rename_detected():
    old = schema("t", [col("user_id", DType.INT)])
    new = schema("t", [col("userId", DType.INT)])
    diff = diff_schema(old, new)
    assert ChangeType.COLUMN_RENAMED in change_types(diff)


def test_rename_is_non_breaking():
    old = schema("t", [col("created", DType.TIMESTAMP)])
    new = schema("t", [col("created_at", DType.TIMESTAMP)])
    diff = diff_schema(old, new)
    renames = [c for c in diff.changes if c.change_type == ChangeType.COLUMN_RENAMED]
    assert renames
    assert renames[0].breaking == BreakingStatus.NON_BREAKING


def test_dissimilar_names_not_renamed():
    old = schema("t", [col("alpha", DType.INT)])
    new = schema("t", [col("zeta", DType.INT)])
    diff = diff_schema(old, new)
    # too different to be a rename — should show as remove + add
    assert ChangeType.COLUMN_REMOVED in change_types(diff)
    assert ChangeType.COLUMN_ADDED in change_types(diff)
    assert ChangeType.COLUMN_RENAMED not in change_types(diff)


# ── type changes ──────────────────────────────────────────────────────────────

def test_type_widening_is_non_breaking():
    old = schema("t", [col("score", DType.INT)])
    new = schema("t", [col("score", DType.FLOAT)])
    diff = diff_schema(old, new)
    c = next(c for c in diff.changes if c.change_type == ChangeType.TYPE_CHANGED)
    assert c.breaking == BreakingStatus.NON_BREAKING


def test_type_narrowing_is_breaking():
    old = schema("t", [col("score", DType.FLOAT)])
    new = schema("t", [col("score", DType.INT)])
    diff = diff_schema(old, new)
    c = next(c for c in diff.changes if c.change_type == ChangeType.TYPE_CHANGED)
    assert c.breaking == BreakingStatus.BREAKING


# ── nullable changes ──────────────────────────────────────────────────────────

def test_nullable_to_not_null_is_breaking():
    old = schema("t", [col("email", DType.STRING, nullable=True)])
    new = schema("t", [col("email", DType.STRING, nullable=False)])
    diff = diff_schema(old, new)
    c = next(c for c in diff.changes if c.change_type == ChangeType.NULLABLE_CHANGED)
    assert c.breaking == BreakingStatus.BREAKING


def test_not_null_to_nullable_is_non_breaking():
    old = schema("t", [col("email", DType.STRING, nullable=False)])
    new = schema("t", [col("email", DType.STRING, nullable=True)])
    diff = diff_schema(old, new)
    c = next(c for c in diff.changes if c.change_type == ChangeType.NULLABLE_CHANGED)
    assert c.breaking == BreakingStatus.NON_BREAKING


# ── constraint changes ────────────────────────────────────────────────────────

def test_constraint_tightening_is_breaking():
    old = schema("t", [col("age", DType.INT, constraints=ColumnConstraints(min_value=0))])
    new = schema("t", [col("age", DType.INT, constraints=ColumnConstraints(min_value=18))])
    diff = diff_schema(old, new)
    c = next(c for c in diff.changes if c.change_type == ChangeType.CONSTRAINT_TIGHTENED)
    assert c.breaking == BreakingStatus.BREAKING


def test_constraint_loosening_is_non_breaking():
    old = schema("t", [col("age", DType.INT, constraints=ColumnConstraints(min_value=18))])
    new = schema("t", [col("age", DType.INT, constraints=ColumnConstraints(min_value=0))])
    diff = diff_schema(old, new)
    c = next(c for c in diff.changes if c.change_type == ChangeType.CONSTRAINT_LOOSENED)
    assert c.breaking == BreakingStatus.NON_BREAKING


# ── reversibility ─────────────────────────────────────────────────────────────

def test_non_destructive_migration_is_reversible():
    old = schema("t", [col("id", DType.INT)])
    new = schema("t", [col("id", DType.INT), col("notes", DType.STRING)])
    diff = diff_schema(old, new)
    plan = plan_migration(diff)
    assert plan.is_reversible


def test_destructive_migration_is_irreversible():
    old = schema("t", [col("id", DType.INT), col("to_drop", DType.STRING)])
    new = schema("t", [col("id", DType.INT)])
    diff = diff_schema(old, new)
    plan = plan_migration(diff)
    assert not plan.is_reversible


def test_reverse_irreversible_returns_typed_error():
    old = schema("t", [col("id", DType.INT), col("gone", DType.STRING)])
    new = schema("t", [col("id", DType.INT)])
    diff = diff_schema(old, new)
    plan = plan_migration(diff)
    result = reverse(plan)
    assert isinstance(result, IrreversibleMigration)


def test_reverse_of_reversible_plan_is_migration_plan():
    old = schema("t", [col("id", DType.INT)])
    new = schema("t", [col("id", DType.INT), col("tag", DType.STRING)])
    diff = diff_schema(old, new)
    plan = plan_migration(diff)
    rev = reverse(plan)
    assert isinstance(rev, MigrationPlan)


# ── provenance ────────────────────────────────────────────────────────────────

def test_provenance_hash_stable():
    old = schema("t", [col("id", DType.INT)])
    new = schema("t", [col("id", DType.INT), col("tag", DType.STRING)])
    diff = diff_schema(old, new)
    plan = plan_migration(diff)
    p1 = provenance(plan)
    p2 = provenance(plan)
    assert p1.provenance_hash == p2.provenance_hash


def test_provenance_records_breaking_count():
    old = schema("t", [col("id", DType.INT), col("gone", DType.STRING)])
    new = schema("t", [col("id", DType.INT)])
    diff = diff_schema(old, new)
    plan = plan_migration(diff)
    p = provenance(plan)
    assert p.breaking_count == diff.breaking_count


def test_provenance_reflects_irreversible():
    old = schema("t", [col("id", DType.INT), col("gone", DType.STRING)])
    new = schema("t", [col("id", DType.INT)])
    diff = diff_schema(old, new)
    plan = plan_migration(diff)
    p = provenance(plan)
    assert p.reversibility == "irreversible"


# ── migration plan sql ────────────────────────────────────────────────────────

def test_migration_plan_has_sql_steps():
    old = schema("t", [col("id", DType.INT)])
    new = schema("t", [col("id", DType.INT), col("tag", DType.STRING)])
    diff = diff_schema(old, new)
    plan = plan_migration(diff)
    assert plan.steps
    assert all(s.sql for s in plan.steps)


def test_no_changes_produces_empty_diff():
    s = schema("t", [col("id", DType.INT), col("name", DType.STRING)])
    diff = diff_schema(s, s)
    assert diff.changes == []
    assert diff.breaking_count == 0


def test_breaking_count_matches_changes():
    old = schema("t", [col("id", DType.INT), col("to_drop", DType.STRING)])
    new = schema("t", [col("id", DType.FLOAT)])  # remove + widen
    diff = diff_schema(old, new)
    manual_breaking = sum(1 for c in diff.changes if c.breaking == BreakingStatus.BREAKING)
    assert diff.breaking_count == manual_breaking
