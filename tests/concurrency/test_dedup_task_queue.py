from app.components.concurrency import DedupTaskQueue, FakeClock


def test_dedup_task_queue_prevents_double_acquire() -> None:
    clock = FakeClock(start=100.0)
    queue = DedupTaskQueue(clock=clock, ttl_seconds=10.0)

    assert queue.try_acquire("note:1") is True
    assert queue.try_acquire("note:1") is False

    clock.advance(11.0)
    assert queue.try_acquire("note:1") is True
