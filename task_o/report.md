# Task O — Migration Report

One non-breaking migration and one breaking migration, end to end.

---

## Example 1 — Non-Breaking Migration

**Scenario:** add an optional `notes` column to the `users` table.

```python
from schema_diff import Schema, Column, DType, diff_schema, plan_migration, reverse, provenance

old = Schema(name="users", columns=[
    Column(name="id",    dtype=DType.INT,    nullable=False),
    Column(name="email", dtype=DType.STRING, nullable=False),
])

new = Schema(name="users", columns=[
    Column(name="id",    dtype=DType.INT,    nullable=False),
    Column(name="email", dtype=DType.STRING, nullable=False),
    Column(name="notes", dtype=DType.STRING, nullable=True),   # new, nullable
])
```

**Diff output:**

| Change | Type | Breaking? |
|---|---|---|
| `notes` added (nullable) | COLUMN_ADDED | Non-breaking |

`breaking_count = 0`

**Migration script (SQL DDL):**

```sql
ALTER TABLE users ADD COLUMN notes TEXT;
```

**Reverse migration:**

```sql
ALTER TABLE users DROP COLUMN notes;
```

Reverse succeeds because adding a nullable column is non-destructive — it can be undone by dropping it.

**Provenance record:**

```
old_schema_hash:  sha256("users")
new_schema_hash:  sha256("users")
breaking_count:   0
reversibility:    reversible
provenance_hash:  <deterministic sha256 of all the above>
```

Two runs of `provenance(plan)` on the same diff produce the **same** `provenance_hash`.

---

## Example 2 — Breaking Migration

**Scenario:** remove the `email` column and narrow `score` from float to int.

```python
old = Schema(name="events", columns=[
    Column(name="id",    dtype=DType.INT,   nullable=False),
    Column(name="email", dtype=DType.STRING, nullable=True),
    Column(name="score", dtype=DType.FLOAT,  nullable=True),
])

new = Schema(name="events", columns=[
    Column(name="id",    dtype=DType.INT, nullable=False),
    Column(name="score", dtype=DType.INT, nullable=True),   # narrowed: float → int
])
```

**Diff output:**

| Change | Type | Breaking? | Reason |
|---|---|---|---|
| `email` removed | COLUMN_REMOVED | **Breaking** | Downstream readers of `email` break |
| `score` float→int | TYPE_CHANGED | **Breaking** | Existing float values may not fit int |

`breaking_count = 2`

**Migration script:**

```sql
ALTER TABLE events DROP COLUMN email;
ALTER TABLE events ALTER COLUMN score TYPE int;
```

**Reverse attempt:**

```
IrreversibleMigration(
  reason="Plan contains irreversible steps (column removal, type narrowing, ...)"
)
```

`reverse()` returns a typed `IrreversibleMigration` rather than a false promise. The column data is gone; the narrowing may have truncated floats. No silent failure.

**Provenance record:**

```
breaking_count:  2
reversibility:   irreversible
provenance_hash: <deterministic sha256>
```

---

## Breaking-Change Rule Summary

| Change | Breaking | Rationale |
|---|---|---|
| Add nullable column | No | Existing rows get NULL; no downstream failure |
| Add NOT NULL column | Yes | Existing rows violate the new constraint |
| Remove column | Yes | Downstream consumers lose data |
| Rename column | No | Treated as a documented rename |
| Widen type (int→float, int→string) | No | All old values remain valid |
| Narrow type (float→int) | Yes | Existing values may be out of range |
| Nullable→NOT NULL | Yes | Existing NULLs would violate constraint |
| NOT NULL→nullable | No | More permissive |
| Tighten constraint | Yes | Existing data may become invalid |
| Loosen constraint | No | More values now accepted |
