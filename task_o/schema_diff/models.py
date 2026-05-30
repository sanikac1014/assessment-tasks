import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel


class DType(str, Enum):
    INT = "int"
    FLOAT = "float"
    STRING = "string"
    BOOL = "bool"
    DATE = "date"
    TIMESTAMP = "timestamp"
    BYTES = "bytes"


class ColumnConstraints(BaseModel):
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allowed_values: Optional[list[Any]] = None


class Column(BaseModel):
    name: str
    dtype: DType
    nullable: bool = True
    constraints: Optional[ColumnConstraints] = None


class Schema(BaseModel):
    name: str
    columns: list[Column]

    def column_map(self) -> dict[str, Column]:
        return {c.name: c for c in self.columns}

    def fingerprint(self) -> str:
        data = self.model_dump_json(exclude_none=False)
        return hashlib.sha256(data.encode()).hexdigest()


class ChangeType(str, Enum):
    COLUMN_ADDED = "COLUMN_ADDED"
    COLUMN_REMOVED = "COLUMN_REMOVED"
    COLUMN_RENAMED = "COLUMN_RENAMED"
    TYPE_CHANGED = "TYPE_CHANGED"
    NULLABLE_CHANGED = "NULLABLE_CHANGED"
    CONSTRAINT_TIGHTENED = "CONSTRAINT_TIGHTENED"
    CONSTRAINT_LOOSENED = "CONSTRAINT_LOOSENED"


class BreakingStatus(str, Enum):
    BREAKING = "BREAKING"
    NON_BREAKING = "NON_BREAKING"


class SchemaChange(BaseModel):
    change_type: ChangeType
    breaking: BreakingStatus
    column_name: str
    old_value: Optional[Any] = None
    new_value: Optional[Any] = None
    description: str


class SchemaDiff(BaseModel):
    old_schema_name: str
    new_schema_name: str
    changes: list[SchemaChange]
    breaking_count: int
    non_breaking_count: int


class MigrationStep(BaseModel):
    description: str
    sql: str
    reversible: bool


class MigrationPlan(BaseModel):
    steps: list[MigrationStep]
    is_reversible: bool
    diff: SchemaDiff


class IrreversibleMigration(BaseModel):
    reason: str
    plan: MigrationPlan


class ProvenanceRecord(BaseModel):
    old_schema_hash: str
    new_schema_hash: str
    changes: list[SchemaChange]
    breaking_count: int
    reversibility: str
    timestamp: str
    provenance_hash: str
