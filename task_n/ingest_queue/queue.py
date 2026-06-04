import time
from collections import deque, OrderedDict
from typing import Callable, Optional

from .models import (
    EnqueueResult,
    EnqueueStatus,
    IngestItem,
    DeadLetter,
    DrainReport,
    RateBudget,
)

# Consumer is any callable that takes (source_id, item) and returns True on success.
Consumer = Callable[[str, IngestItem], bool]


class TokenBucket:
    def __init__(self, capacity: float, refill_rate: float):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._tokens = capacity
        self._last_refill = time.monotonic()

    def _refill(self):
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_rate)
        self._last_refill = now

    def consume(self, tokens: float = 1.0) -> bool:
        self._refill()
        if self._tokens >= tokens:
            self._tokens -= tokens
            return True
        return False

    def available(self) -> float:
        self._refill()
        return self._tokens


class IngestQueue:
    def __init__(
        self,
        max_in_flight: int = 500,
        max_retries: int = 3,
        dedup_window: int = 10000,
    ):
        self._max_in_flight = max_in_flight
        self._max_retries = max_retries
        self._dedup_window = dedup_window

        self._sources: dict[str, RateBudget] = {}
        self._buckets: dict[str, TokenBucket] = {}
        self._queues: dict[str, deque] = {}          # source_id -> deque of (item_id, item, attempt)
        self._seen_keys: dict[str, OrderedDict] = {} # source_id -> ordered set of idempotency keys (FIFO eviction)
        self._in_flight: int = 0
        self._dead_letters: list[DeadLetter] = []

    def register_source(self, source_id: str, rate_budget: RateBudget) -> None:
        self._sources[source_id] = rate_budget
        self._buckets[source_id] = TokenBucket(rate_budget.capacity, rate_budget.refill_rate)
        self._queues[source_id] = deque()
        self._seen_keys[source_id] = OrderedDict()

    def enqueue(self, source_id: str, item: IngestItem) -> EnqueueResult:
        if source_id not in self._sources:
            raise ValueError(f"Unknown source: {source_id}")

        key = item.derive_key()

        # idempotency check
        if key in self._seen_keys[source_id]:
            return EnqueueResult(status=EnqueueStatus.DUPLICATE_IGNORED, source_id=source_id)

        # backpressure check
        total_queued = sum(len(q) for q in self._queues.values())
        if self._in_flight + total_queued >= self._max_in_flight:
            return EnqueueResult(status=EnqueueStatus.BACKPRESSURE_APPLIED, source_id=source_id)

        # record the key with bounded FIFO eviction (evict one oldest, not the whole set)
        od = self._seen_keys[source_id]
        if len(od) >= self._dedup_window:
            od.popitem(last=False)  # evict oldest
        od[key] = None

        item_id = key
        self._queues[source_id].append((item_id, item, 0))
        return EnqueueResult(status=EnqueueStatus.ACCEPTED, item_id=item_id, source_id=source_id)

    def drain(self, consumer: Consumer, max_items: int) -> DrainReport:
        processed = 0
        failed = 0
        skipped_budget = 0

        dispatched = 0
        source_ids = list(self._queues.keys())

        while dispatched < max_items:
            made_progress = False
            for source_id in source_ids:
                if dispatched >= max_items:
                    break
                q = self._queues[source_id]
                if not q:
                    continue
                if not self._buckets[source_id].consume():
                    skipped_budget += 1
                    continue

                item_id, item, attempt = q.popleft()
                self._in_flight += 1
                made_progress = True
                dispatched += 1

                try:
                    success = consumer(source_id, item)
                except Exception as exc:
                    success = False
                    reason = str(exc)
                else:
                    reason = "consumer returned False"

                self._in_flight -= 1

                if success:
                    processed += 1
                else:
                    attempt += 1
                    if attempt >= self._max_retries:
                        self._dead_letters.append(DeadLetter(
                            source_id=source_id,
                            item_id=item_id,
                            payload=item.payload,
                            failure_reason=reason,
                            attempt_history=[f"attempt {i+1}" for i in range(attempt)],
                            failed_at=time.time(),
                        ))
                        failed += 1
                    else:
                        # requeue for retry
                        q.appendleft((item_id, item, attempt))

            if not made_progress:
                break

        return DrainReport(processed=processed, failed=failed, skipped_budget=skipped_budget)

    def dead_letters(self) -> list[DeadLetter]:
        return list(self._dead_letters)

    def queue_depth(self, source_id: str) -> int:
        return len(self._queues.get(source_id, []))

    def total_queued(self) -> int:
        return sum(len(q) for q in self._queues.values())
