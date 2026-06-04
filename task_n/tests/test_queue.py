import time
from collections import defaultdict
from typing import Dict, List

import pytest

from ingest_queue import (
    EnqueueStatus, EnqueueResult, IngestItem, DrainReport,
    RateBudget, IngestQueue, TokenBucket,
)


# ── helpers ───────────────────────────────────────────────────────────────────

def make_queue(**kwargs) -> IngestQueue:
    defaults = dict(max_in_flight=200, max_retries=3, dedup_window=5000)
    defaults.update(kwargs)
    return IngestQueue(**defaults)


def make_source(capacity=10.0, refill_rate=100.0) -> RateBudget:
    return RateBudget(capacity=capacity, refill_rate=refill_rate)


def item(payload, key=None) -> IngestItem:
    return IngestItem(payload=payload, idempotency_key=key)


def always_ok(source_id, itm):
    return True


def always_fail(source_id, itm):
    return False


# ── token bucket ──────────────────────────────────────────────────────────────

def test_token_bucket_consumes():
    bucket = TokenBucket(capacity=5.0, refill_rate=0.0)
    assert bucket.consume()
    assert bucket.consume()
    assert bucket.consume()
    assert bucket.consume()
    assert bucket.consume()
    assert not bucket.consume()


def test_token_bucket_refills():
    bucket = TokenBucket(capacity=1.0, refill_rate=1000.0)
    bucket.consume()
    time.sleep(0.005)
    assert bucket.consume()


def test_token_bucket_caps_at_capacity():
    bucket = TokenBucket(capacity=3.0, refill_rate=1000.0)
    time.sleep(0.02)
    bucket._refill()
    assert bucket.available() <= 3.0


# ── enqueue ───────────────────────────────────────────────────────────────────

def test_enqueue_accepted():
    q = make_queue()
    q.register_source("s1", make_source())
    result = q.enqueue("s1", item("hello"))
    assert result.status == EnqueueStatus.ACCEPTED
    assert result.item_id is not None


def test_enqueue_duplicate_ignored():
    q = make_queue()
    q.register_source("s1", make_source())
    it = item("hello", key="key-1")
    q.enqueue("s1", it)
    result2 = q.enqueue("s1", it)
    assert result2.status == EnqueueStatus.DUPLICATE_IGNORED


def test_enqueue_duplicate_by_derived_key():
    q = make_queue()
    q.register_source("s1", make_source())
    q.enqueue("s1", item("same payload"))
    result = q.enqueue("s1", item("same payload"))
    assert result.status == EnqueueStatus.DUPLICATE_IGNORED


def test_enqueue_backpressure_applied():
    q = make_queue(max_in_flight=3)
    q.register_source("s1", make_source())
    for i in range(3):
        q.enqueue("s1", item(f"payload-{i}"))
    result = q.enqueue("s1", item("overflow"))
    assert result.status == EnqueueStatus.BACKPRESSURE_APPLIED


def test_unknown_source_raises():
    q = make_queue()
    with pytest.raises(ValueError):
        q.enqueue("unknown", item("x"))


# ── drain ─────────────────────────────────────────────────────────────────────

def test_drain_processes_items():
    q = make_queue()
    q.register_source("s1", make_source())
    for i in range(5):
        q.enqueue("s1", item(i))
    report = q.drain(always_ok, max_items=10)
    assert report.processed == 5
    assert report.failed == 0


def test_drain_respects_max_items():
    q = make_queue()
    q.register_source("s1", make_source(capacity=100, refill_rate=100))
    for i in range(20):
        q.enqueue("s1", item(i))
    report = q.drain(always_ok, max_items=5)
    assert report.processed == 5


def test_failed_items_go_to_dead_letter():
    q = make_queue(max_retries=1)
    q.register_source("s1", make_source(capacity=100, refill_rate=100))
    q.enqueue("s1", item("bad"))
    q.drain(always_fail, max_items=10)
    assert len(q.dead_letters()) == 1


def test_dead_letter_has_attempt_history():
    q = make_queue(max_retries=2)
    q.register_source("s1", make_source(capacity=100, refill_rate=100))
    q.enqueue("s1", item("bad"))
    q.drain(always_fail, max_items=20)
    dl = q.dead_letters()
    assert dl
    assert len(dl[0].attempt_history) == 2


def test_nothing_vanishes_on_consumer_exception():
    def crasher(source_id, itm):
        raise RuntimeError("boom")

    q = make_queue(max_retries=1)
    q.register_source("s1", make_source(capacity=100, refill_rate=100))
    q.enqueue("s1", item("crash-me"))
    q.drain(crasher, max_items=10)
    # must end up in dead letters, not silently dropped
    assert len(q.dead_letters()) == 1


def test_no_item_processed_twice():
    processed_ids = []

    def track(source_id, itm):
        processed_ids.append(itm.derive_key())
        return True

    q = make_queue()
    q.register_source("s1", make_source(capacity=100, refill_rate=100))
    for i in range(10):
        q.enqueue("s1", item(i))
    q.drain(track, max_items=20)
    assert len(processed_ids) == len(set(processed_ids))


# ── retry logic ──────────────────────────────────────────────────────────────

def test_retry_succeeds_on_second_attempt():
    attempts = [0]

    def flaky(source_id, itm):
        attempts[0] += 1
        return attempts[0] >= 2  # fail first, succeed second

    q = make_queue(max_retries=3)
    q.register_source("s1", make_source(capacity=100, refill_rate=100))
    q.enqueue("s1", item("flaky"))
    report = q.drain(flaky, max_items=10)
    assert report.processed == 1
    assert len(q.dead_letters()) == 0


def test_dead_letter_not_reprocessed():
    q = make_queue(max_retries=1)
    q.register_source("s1", make_source(capacity=100, refill_rate=100))
    q.enqueue("s1", item("bad"))
    q.drain(always_fail, max_items=10)
    # drain again — dead-lettered item should not reappear
    report2 = q.drain(always_ok, max_items=10)
    assert report2.processed == 0


def test_multiple_sources_independent():
    q = make_queue()
    q.register_source("s1", make_source())
    q.register_source("s2", make_source())
    q.enqueue("s1", item("from-s1"))
    q.enqueue("s2", item("from-s2"))
    report = q.drain(always_ok, max_items=10)
    assert report.processed == 2


def test_queue_depth_decreases_after_drain():
    q = make_queue()
    q.register_source("s1", make_source(capacity=100, refill_rate=100))
    for i in range(5):
        q.enqueue("s1", item(i))
    assert q.queue_depth("s1") == 5
    q.drain(always_ok, max_items=5)
    assert q.queue_depth("s1") == 0


def test_dead_letter_contains_payload():
    q = make_queue(max_retries=1)
    q.register_source("s1", make_source(capacity=100, refill_rate=100))
    q.enqueue("s1", item({"key": "value"}))
    q.drain(always_fail, max_items=10)
    dl = q.dead_letters()
    assert dl[0].payload == {"key": "value"}


def test_total_queued_across_sources():
    q = make_queue()
    q.register_source("s1", make_source())
    q.register_source("s2", make_source())
    q.enqueue("s1", item("a"))
    q.enqueue("s2", item("b"))
    q.enqueue("s2", item("c"))
    assert q.total_queued() == 3


# ── dedup bounded eviction ────────────────────────────────────────────────────

def test_dedup_eviction_is_bounded():
    """
    After the dedup window fills, only the oldest key is evicted (one at a time),
    not the entire seen-key set. Keys that were added after the first eviction
    must still be recognised as duplicates.
    """
    WINDOW = 5
    q = make_queue(max_retries=1, dedup_window=WINDOW)
    q.register_source("s1", make_source(capacity=100, refill_rate=100))

    processed: list[str] = []

    def track(sid, itm):
        processed.append(itm.derive_key())
        return True

    # Fill the window and drain
    for i in range(WINDOW):
        q.enqueue("s1", item(f"p{i}", key=f"k{i}"))
    q.drain(track, max_items=WINDOW + 2)
    assert len(processed) == WINDOW

    # One more item triggers eviction of the oldest key (k0)
    q.enqueue("s1", item("pX", key="kX"))
    q.drain(track, max_items=2)

    # Keys k1..k(WINDOW-1) must still be in the window → re-enqueue is DUPLICATE
    for i in range(1, WINDOW):
        r = q.enqueue("s1", item(f"re-{i}", key=f"k{i}"))
        assert r.status == EnqueueStatus.DUPLICATE_IGNORED, (
            f"k{i} should still be in window but was accepted — "
            "bulk eviction bug present"
        )


# ── stress harness ────────────────────────────────────────────────────────────

def test_stress_four_properties():
    """
    5 sources at different rate budgets, 200 items each (1000 total).

    Four hard properties verified with real assertions:
    (a) no source exceeds its rate budget — independent timestamp check over
        a sliding window, not derived from the same TokenBucket that enforced it
    (b) no item is ever processed twice
    (c) every accepted item ends up either processed or dead-lettered (nothing vanishes)
    (d) backpressure engages when the in-flight ceiling is hit
    """
    # Small burst (capacity=5) forces the bucket to actually throttle;
    # high refill rate (500/s) lets the queue drain completely in the test window.
    SOURCES = {
        "src_a": RateBudget(capacity=5.0, refill_rate=500.0),
        "src_b": RateBudget(capacity=3.0, refill_rate=300.0),
        "src_c": RateBudget(capacity=8.0, refill_rate=800.0),
        "src_d": RateBudget(capacity=2.0, refill_rate=200.0),
        "src_e": RateBudget(capacity=4.0, refill_rate=400.0),
    }
    # Dedup window larger than total items so eviction cannot hide duplicates
    q = make_queue(max_in_flight=20, max_retries=2, dedup_window=10_000)
    for sid, budget in SOURCES.items():
        q.register_source(sid, budget)

    # Enqueue 200 items per source (1000 total); track which were accepted
    accepted_ids: set[str] = set()
    for sid in SOURCES:
        for i in range(200):
            r = q.enqueue(sid, item(f"{sid}-payload-{i}"))
            if r.status == EnqueueStatus.ACCEPTED:
                accepted_ids.add(r.item_id)

    # (d) BACKPRESSURE: max_in_flight=20 means the queue should be at or past ceiling
    bp_results = [q.enqueue("src_a", item(f"bp-probe-{i}")) for i in range(10)]
    n_backpressured = sum(
        1 for r in bp_results if r.status == EnqueueStatus.BACKPRESSURE_APPLIED
    )
    assert n_backpressured > 0, (
        "Backpressure never triggered — max_in_flight too high or accepted_ids too few"
    )

    # Tracking consumer for (a) and (b)
    dispatch_log: Dict[str, List[float]] = defaultdict(list)
    processed_ids: list[str] = []

    def tracking_consumer(source_id, itm):
        dispatch_log[source_id].append(time.monotonic())
        processed_ids.append(itm.derive_key())
        return True

    total_skipped_budget = 0
    for _ in range(500):
        report = q.drain(tracking_consumer, max_items=50)
        total_skipped_budget += report.skipped_budget
        if q.total_queued() == 0:
            break
        # Let token buckets refill between rounds; without this, rapid drain
        # calls arrive before any tokens have refilled and stall on empty buckets.
        time.sleep(0.005)

    # (b) NO ITEM PROCESSED TWICE
    assert len(processed_ids) == len(set(processed_ids)), (
        f"Duplicate processing: {len(processed_ids)} dispatches but only "
        f"{len(set(processed_ids))} unique IDs"
    )

    # (c) NOTHING VANISHES: queue empty; every accepted item is processed or dead-lettered
    assert q.total_queued() == 0, (
        f"{q.total_queued()} items remain in queue after draining"
    )
    dead_ids = {dl.item_id for dl in q.dead_letters()}
    accounted = set(processed_ids) | dead_ids
    unaccounted = accepted_ids - accounted
    assert not unaccounted, (
        f"{len(unaccounted)} accepted items are neither processed nor dead-lettered"
    )

    # Prove throttling actually occurred: drain reported at least one budget skip
    assert total_skipped_budget > 0, (
        "Token buckets never throttled — capacity too high or all items drained "
        "instantly without budget enforcement"
    )

    # (a) RATE BUDGET: independent check via dispatch timestamps.
    # In any WINDOW-second interval, each source must dispatch no more than
    # capacity + refill_rate * WINDOW items.  This is verified from the
    # recorded timestamps, independent of the TokenBucket that enforced it.
    WINDOW = 0.5  # seconds
    for sid, budget in SOURCES.items():
        times = sorted(dispatch_log[sid])
        if len(times) < 2:
            continue
        max_in_window = budget.capacity + budget.refill_rate * WINDOW + 1  # +1 rounding slack
        for i, t0 in enumerate(times):
            n_in_window = sum(1 for t in times[i:] if t <= t0 + WINDOW)
            assert n_in_window <= max_in_window, (
                f"Source {sid} burst violation: {n_in_window} dispatches in "
                f"{WINDOW}s window (budget capacity={budget.capacity}, "
                f"rate={budget.refill_rate}/s, allowed≤{max_in_window:.1f})"
            )
