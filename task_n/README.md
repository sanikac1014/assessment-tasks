# Task N — Rate-Limited Multi-Source Ingestion Queue

Ingests items from multiple registered data sources into a single pipeline under per-source token-bucket rate budgets. Features: idempotent re-ingestion, backpressure, and dead-letter handling.

## Install

```bash
pip install -e ".[dev]"
```

## Usage

```python
from ingest_queue import IngestQueue, IngestItem, RateBudget

q = IngestQueue(max_in_flight=500, max_retries=3)
q.register_source("api_feed", RateBudget(capacity=10.0, refill_rate=5.0))

result = q.enqueue("api_feed", IngestItem(payload={"event": "click"}))
print(result.status)  # ACCEPTED | DUPLICATE_IGNORED | BACKPRESSURE_APPLIED

def my_consumer(source_id, item):
    print(f"Processing {item.payload} from {source_id}")
    return True

report = q.drain(my_consumer, max_items=100)
print(report.processed, report.failed)

dead = q.dead_letters()
```

## Run Tests

```bash
pytest -v
```

## How It Works

**Token bucket**: each source gets `capacity` tokens refilled at `refill_rate` per second. `drain()` only dispatches an item if the source has tokens available.

**Idempotency**: each item derives a key from its `idempotency_key` field or a SHA-256 of the payload. Re-enqueuing the same key within the dedup window is a no-op (`DUPLICATE_IGNORED`). The window uses bounded FIFO eviction — when the window is full, only the single oldest key is dropped (one at a time), preventing the bulk-eviction bug where the entire seen-key set would be wiped and all prior items become re-processable.

**Backpressure**: when total queued + in-flight items hits `max_in_flight`, `enqueue()` returns `BACKPRESSURE_APPLIED` instead of growing unbounded.

**Dead letters**: items that fail more than `max_retries` times are stored in the dead-letter list with their full attempt history, never silently discarded.
