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

    Enqueue and drain are interleaved so backpressure engages and releases
    naturally rather than blocking all 1000 items at the start.  Refill rates
    are set low enough (20–40/s) that the per-source rate ceiling is genuinely
    binding and the timestamp check can fail if the bucket misbehaves.

    Four hard properties verified with real assertions:
    (a) no source exceeds its rate budget — independent timestamp check over a
        sliding window, separate from the TokenBucket that enforced it
    (b) no item is ever processed twice
    (c) every accepted item ends up processed or dead-lettered (nothing vanishes)
    (d) backpressure engages during enqueue and releases as items drain
    """
    SOURCES = {
        "src_a": RateBudget(capacity=5.0, refill_rate=30.0),
        "src_b": RateBudget(capacity=3.0, refill_rate=20.0),
        "src_c": RateBudget(capacity=8.0, refill_rate=40.0),
        "src_d": RateBudget(capacity=2.0, refill_rate=20.0),
        "src_e": RateBudget(capacity=4.0, refill_rate=25.0),
    }
    # in-flight ceiling large enough that all five sources can enqueue in early
    # rounds (before the queue fills), but small enough that backpressure still
    # engages once the queue accumulates depth across rounds.
    q = make_queue(max_in_flight=200, max_retries=2, dedup_window=10_000)
    for sid, budget in SOURCES.items():
        q.register_source(sid, budget)

    # Pre-generate items so indices track which items are still pending
    all_items = {
        sid: [item(f"{sid}-payload-{i}") for i in range(200)]
        for sid in SOURCES
    }
    item_idx = {sid: 0 for sid in SOURCES}   # next item to attempt per source

    dispatch_log: Dict[str, List[float]] = defaultdict(list)
    processed_ids: list[str] = []
    accepted_ids: set[str] = set()
    total_skipped_budget = 0
    total_backpressured = 0

    def tracking_consumer(source_id, itm):
        dispatch_log[source_id].append(time.monotonic())
        processed_ids.append(itm.derive_key())
        return True

    ENQUEUE_BATCH = 15   # items to attempt per source per round

    for _ in range(300):
        # ── enqueue phase ──────────────────────────────────────────────────
        # Only advance item_idx on ACCEPTED — backpressured items are retried
        # next round once drain has freed space.
        for sid in SOURCES:
            enqueued_this_round = 0
            while item_idx[sid] < 200 and enqueued_this_round < ENQUEUE_BATCH:
                r = q.enqueue(sid, all_items[sid][item_idx[sid]])
                if r.status == EnqueueStatus.ACCEPTED:
                    accepted_ids.add(r.item_id)
                    item_idx[sid] += 1
                    enqueued_this_round += 1
                elif r.status == EnqueueStatus.BACKPRESSURE_APPLIED:
                    total_backpressured += 1
                    break   # wait for drain to free in-flight space
                else:
                    item_idx[sid] += 1  # skip duplicate (shouldn't happen here)

        # ── drain phase ────────────────────────────────────────────────────
        rep = q.drain(tracking_consumer, max_items=ENQUEUE_BATCH * len(SOURCES))
        total_skipped_budget += rep.skipped_budget

        all_accepted = all(item_idx[sid] >= 200 for sid in SOURCES)
        if all_accepted and q.total_queued() == 0:
            break

        # 80 ms sleep gives each source 1.6–3.2 new tokens at the configured rates,
        # keeping the token ceiling genuinely binding over each drain round.
        time.sleep(0.08)

    # (d) BACKPRESSURE: must have fired at least once during the enqueue rounds
    assert total_backpressured > 0, (
        "Backpressure never triggered — raise max_in_flight or lower ENQUEUE_BATCH"
    )

    # (b) NO ITEM PROCESSED TWICE
    assert len(processed_ids) == len(set(processed_ids)), (
        f"Duplicate processing: {len(processed_ids)} dispatches, "
        f"{len(set(processed_ids))} unique"
    )

    # (c) NOTHING VANISHES
    assert q.total_queued() == 0, (
        f"{q.total_queued()} items remain in queue after all rounds"
    )
    dead_ids = {dl.item_id for dl in q.dead_letters()}
    unaccounted = accepted_ids - (set(processed_ids) | dead_ids)
    assert not unaccounted, (
        f"{len(unaccounted)} accepted items are neither processed nor dead-lettered"
    )

    # All five sources must have contributed a meaningful share of dispatches
    for sid in SOURCES:
        assert len(dispatch_log[sid]) >= 50, (
            f"Source {sid} only dispatched {len(dispatch_log[sid])} items — "
            "not a meaningful share; harness may not be stressing all sources"
        )

    # Token-budget throttling actually fired
    assert total_skipped_budget > 0, (
        "Token buckets never throttled — refill rates too high to bind the ceiling"
    )

    # (a) RATE BUDGET — independent timestamp check.
    # In any WINDOW-second interval, each source must not exceed
    # capacity + refill_rate * WINDOW dispatches.  This is derived from the
    # recorded wall-clock timestamps, not from the TokenBucket itself.
    WINDOW = 0.3  # seconds — tight enough that a misbehaving bucket would be caught
    for sid, budget in SOURCES.items():
        times = sorted(dispatch_log[sid])
        max_in_window = budget.capacity + budget.refill_rate * WINDOW + 1  # +1 rounding
        for i, t0 in enumerate(times):
            n_in_window = sum(1 for t in times[i:] if t <= t0 + WINDOW)
            assert n_in_window <= max_in_window, (
                f"Source {sid} rate violation: {n_in_window} dispatches in "
                f"{WINDOW}s window (capacity={budget.capacity}, "
                f"rate={budget.refill_rate}/s, ceiling={max_in_window:.1f})"
            )
