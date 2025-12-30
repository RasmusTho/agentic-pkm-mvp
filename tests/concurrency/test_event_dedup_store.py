from app.components.concurrency import EventDedupStore, FakeClock


def test_event_dedup_blocks_replay() -> None:
    clock = FakeClock(start=0.0)
    store = EventDedupStore(clock=clock, ttl_seconds=60.0)
    handled: list[str] = []

    def handle(event_id: str) -> None:
        if store.seen(event_id):
            return
        handled.append(event_id)

    handle("evt-1")
    handle("evt-1")

    assert handled == ["evt-1"]
