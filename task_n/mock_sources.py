"""
Mock sources and consumers for testing and stress-harness use.

A Source is any iterator that yields IngestItems.
A Consumer is any callable (source_id: str, item: IngestItem) -> bool.
"""
from collections.abc import Iterator
from ingest_queue import IngestItem


class SequentialSource:
    """Yields n items with sequential payloads."""
    def __init__(self, source_id: str, n: int):
        self.source_id = source_id
        self.n = n

    def items(self) -> Iterator[IngestItem]:
        for i in range(self.n):
            yield IngestItem(payload=f"{self.source_id}-item-{i}")


class RepeatingSource:
    """Yields the same item repeatedly — useful for testing duplicate handling."""
    def __init__(self, source_id: str, payload: str, n: int):
        self.source_id = source_id
        self.payload = payload
        self.n = n

    def items(self) -> Iterator[IngestItem]:
        for _ in range(self.n):
            yield IngestItem(payload=self.payload)


class OkConsumer:
    """Always returns True (success). Records every item it processes."""
    def __init__(self):
        self.received: list[tuple[str, IngestItem]] = []

    def __call__(self, source_id: str, item: IngestItem) -> bool:
        self.received.append((source_id, item))
        return True


class FailConsumer:
    """Always returns False (failure). Used to drive items into dead-letter."""
    def __call__(self, source_id: str, item: IngestItem) -> bool:
        return False


class FlakyConsumer:
    """Fails the first `fail_count` calls per item, then succeeds."""
    def __init__(self, fail_count: int = 1):
        self.fail_count = fail_count
        self._attempts: dict[str, int] = {}
        self.received: list[tuple[str, IngestItem]] = []

    def __call__(self, source_id: str, item: IngestItem) -> bool:
        key = item.derive_key()
        self._attempts[key] = self._attempts.get(key, 0) + 1
        if self._attempts[key] <= self.fail_count:
            return False
        self.received.append((source_id, item))
        return True


class SaturatingConsumer:
    """
    Accepts up to `ceiling` items then signals saturation by raising RuntimeError.
    Used to test that backpressure eventually releases once load drops.
    """
    def __init__(self, ceiling: int):
        self.ceiling = ceiling
        self.received: list[tuple[str, IngestItem]] = []

    def __call__(self, source_id: str, item: IngestItem) -> bool:
        if len(self.received) >= self.ceiling:
            raise RuntimeError("consumer saturated")
        self.received.append((source_id, item))
        return True
