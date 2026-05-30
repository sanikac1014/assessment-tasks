import hashlib
import time
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, field_validator


class EnqueueStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    DUPLICATE_IGNORED = "DUPLICATE_IGNORED"
    BACKPRESSURE_APPLIED = "BACKPRESSURE_APPLIED"


class EnqueueResult(BaseModel):
    status: EnqueueStatus
    item_id: Optional[str] = None
    source_id: str


class IngestItem(BaseModel):
    payload: Any
    idempotency_key: Optional[str] = None

    def derive_key(self) -> str:
        if self.idempotency_key:
            return self.idempotency_key
        raw = str(self.payload).encode()
        return hashlib.sha256(raw).hexdigest()


class DeadLetter(BaseModel):
    source_id: str
    item_id: str
    payload: Any
    failure_reason: str
    attempt_history: list[str]
    failed_at: float


class DrainReport(BaseModel):
    processed: int
    failed: int
    skipped_budget: int


class RateBudget(BaseModel):
    capacity: float       # token bucket max capacity
    refill_rate: float    # tokens per second
