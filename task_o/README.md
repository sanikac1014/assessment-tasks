# Task O — Schema-Migration and Provenance Diff Tool

Compares two versions of a tabular schema, classifies each change as breaking or non-breaking, generates a SQL migration plan, and emits a provenance record.

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```python
from schema_diff import Schema, Column, DType, diff_schema, plan_migration, reverse, provenance

old = Schema(name="users", columns=[
    Column(name="id", dtype=DType.INT, nullable=False),
    Column(name="email", dtype=DType.STRING, nullable=True),
])
new = Schema(name="users", columns=[
    Column(name="id", dtype=DType.INT, nullable=False),
    Column(name="email", dtype=DType.STRING, nullable=False),   # tightened
    Column(name="created_at", dtype=DType.TIMESTAMP),           # new column
])

diff = diff_schema(old, new)
plan = plan_migration(diff)
rev = reverse(plan)          # IrreversibleMigration if not reversible
prov = provenance(plan)
```

## Run Tests

```bash
pytest -v
```

---

## Breaking-Change Rules

| Change | Breaking? | Reason |
|---|---|---|
| Add nullable column | **Non-breaking** | Existing rows get NULL; downstream still works |
| Add NOT NULL column | **Breaking** | Existing rows would violate constraint |
| Remove column | **Breaking** | Downstream consumers reading that column break |
| Rename column | **Non-breaking** | Treated as non-breaking with documented rename |
| Widen type (int→float, int→string) | **Non-breaking** | All old values are valid in the new type |
| Narrow type (float→int, string→int) | **Breaking** | Existing values may not fit the new type |
| NOT NULL → nullable | **Non-breaking** | More permissive |
| Nullable → NOT NULL | **Breaking** | Existing NULLs would violate constraint |
| Loosen constraint (widen range, drop allowed_values) | **Non-breaking** | More values now accepted |
| Tighten constraint (narrow range, add allowed_values) | **Breaking** | Existing data may now be invalid |

## Rename Heuristic

Column renames are detected using Python's `difflib.SequenceMatcher` on the lower-cased names. A pair is classified as a rename if the similarity ratio exceeds 0.6. This catches common patterns like `user_id → userId`, `created → created_at`, and `email_addr → email_address`. Below the threshold, the change is treated as a remove + add. The threshold is justified by common rename patterns in practice — minor edits rather than wholesale replacements.

---

## Worked Example

## Provenance Hashing

The `ProvenanceRecord` hashes schema **content**, not schema names. Each schema's fingerprint is a SHA-256 of its full column definitions (`Schema.fingerprint()`), so two structurally different schemas that happen to share a name produce different `old_schema_hash` / `new_schema_hash` values. Two runs of `provenance(plan)` on the same diff always produce the same `provenance_hash`.

---

### Non-breaking migration
Add a nullable `notes` column:
```sql
ALTER TABLE users ADD COLUMN notes TEXT;
```
Provenance: `breaking_count=0`, `reversibility=reversible`

Reverse:
```sql
ALTER TABLE users DROP COLUMN notes;
```

### Breaking migration
Remove the `email` column:
```sql
ALTER TABLE users DROP COLUMN email;
```
Provenance: `breaking_count=1`, `reversibility=irreversible`

Reverse: returns `IrreversibleMigration` — no false promise made.
