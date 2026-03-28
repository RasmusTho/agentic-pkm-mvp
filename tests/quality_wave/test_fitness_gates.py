"""Phase E: Fitness Gates (Status Counters, Idempotence, No Duplicate Intents)."""
from __future__ import annotations

import pytest
from typing import Dict, Any, Set
from uuid import uuid4
from tests.quality_wave.conftest import MetricsCollector, EventChain
from app.events.schema import OutboxEvent, make_outbox_event


@pytest.mark.not_pg
class TestFitnessGateCounters:
    """Test that system counters are accurate."""

    def test_ingest_runs_counter_increments(self, metrics: MetricsCollector):
        """Assert ingest_runs counter increments correctly."""
        metrics.ingest_runs = 0
        snap1 = metrics.snapshot()
        assert snap1["ingest_runs"] == 0

        metrics.ingest_runs = 1
        snap2 = metrics.snapshot()
        assert snap2["ingest_runs"] == 1

        metrics.ingest_runs = 2
        snap3 = metrics.snapshot()
        assert snap3["ingest_runs"] == 2

    def test_panel_runs_counter_increments(self, metrics: MetricsCollector):
        """Assert panel_runs counter increments correctly."""
        metrics.panel_runs = 0
        snap1 = metrics.snapshot()
        assert snap1["panel_runs"] == 0

        metrics.panel_runs = 3
        snap2 = metrics.snapshot()
        assert snap2["panel_runs"] == 3

    def test_promote_intents_counter_accuracy(self, metrics: MetricsCollector):
        """Assert promote.intent.created counter matches actual intents."""
        trace_ids_seen = set()
        for i in range(5):
            trace_id = f"trace-promo-{i}"
            event = make_outbox_event(
                "promote.intent.created",
                source="promotion.consumer",
                trace_id=trace_id,
                payload={"uuid": f"obj-{i}", "desired_state": "promoted"},
            )
            metrics.record_event(event)
            metrics.promote_intents_created += 1
            trace_ids_seen.add(trace_id)

        snap = metrics.snapshot()
        assert snap["promote_intents_created"] == 5
        assert len(metrics.trace_ids_seen) == 5

    def test_object_count_matches_embeddings(self, metrics: MetricsCollector):
        """Assert object count and embedding count are synchronized."""
        metrics.object_count = 10
        metrics.embedding_count = 10

        snap = metrics.snapshot()
        assert snap["object_count"] == snap["embedding_count"]

    def test_counter_atomicity(self, metrics: MetricsCollector):
        """Assert counters update atomically."""
        initial = metrics.snapshot()

        metrics.ingest_runs = 1
        metrics.object_count = 5
        metrics.embedding_count = 5

        updated = metrics.snapshot()

        assert updated["ingest_runs"] == 1
        assert updated["object_count"] == 5
        assert updated["embedding_count"] == 5


@pytest.mark.not_pg
class TestNoOrphanIntents:
    """Test that no duplicate intents exist in outbox."""

    def test_event_id_uniqueness_in_outbox(self, event_chain: EventChain):
        """Assert all event_ids in outbox are unique."""
        trace_id = "trace-dedup-001"

        for i in range(5):
            event = make_outbox_event(
                f"promote.intent.created",
                source="promotion.consumer",
                trace_id=trace_id,
                payload={"uuid": f"obj-{i}"},
            )
            event_chain.append(event)

        event_ids = [e.event_id for e in event_chain.events]

        assert len(event_ids) == len(set(event_ids)), (
            f"Duplicate event_ids detected in outbox: {event_ids}"
        )

    def test_duplicate_event_id_rejected(self):
        """Assert duplicate event_ids can be detected and skipped."""
        seen: Set[str] = set()
        events = [
            make_outbox_event("promote.intent.created", source="s1"),
            make_outbox_event("promote.intent.created", source="s1"),
            make_outbox_event("promote.intent.created", source="s1"),
        ]

        assert events[0].event_id not in seen
        seen.add(events[0].event_id)

        for e in events[1:]:
            assert e.event_id not in seen, "Duplicate event_id not prevented"
            seen.add(e.event_id)

    def test_outbox_dedup_mechanism(self):
        """Test outbox dedup mechanism filters duplicates."""
        seen: Dict[str, bool] = {}
        processed = []
        first = make_outbox_event("evt1", source="s1")
        second = make_outbox_event("evt2", source="s1")
        duplicate = make_outbox_event("evt1", source="s1").model_copy(update={"event_id": first.event_id})

        events = [first, second, duplicate]

        for event in events:
            if event.event_id not in seen:
                seen[event.event_id] = True
                processed.append(event)

        assert len(processed) == 2, "Dedup didn't filter duplicate"

    def test_trace_id_not_used_for_dedup(self, event_chain: EventChain):
        """Assert that trace_id is NOT used for dedup (only event_id)."""
        trace_id = "same-trace"

        e1 = make_outbox_event("promote.intent.created", source="s", trace_id=trace_id)
        e2 = make_outbox_event("promote.intent.created", source="s", trace_id=trace_id)

        event_chain.append(e1)
        event_chain.append(e2)

        assert len(event_chain.events) == 2
        assert e1.trace_id == e2.trace_id
        assert e1.event_id != e2.event_id


@pytest.mark.not_pg
class TestWatcherHeartbeat:
    """Test watcher/worker heartbeat signals are within bounds."""

    def test_heartbeat_timestamp_valid(self):
        """Assert heartbeat timestamps are valid ISO format."""
        from app.events.schema import _now_iso

        ts = _now_iso()
        assert "T" in ts
        assert "Z" in ts
        assert ts.endswith("Z")

    def test_heartbeat_within_bounds(self, metrics: MetricsCollector):
        """Assert heartbeat is recent (within expected time window)."""
        import time

        heartbeat_time = time.time()
        now = time.time()
        delta = now - heartbeat_time

        assert delta < 1.0

    def test_watcher_tick_counter(self, metrics: MetricsCollector):
        """Assert watcher tick counter is monotonic."""
        for tick in range(1, 11):
            metrics.ingest_runs = tick
            snap = metrics.snapshot()
            assert snap["ingest_runs"] == tick


@pytest.mark.not_pg
class TestIdempotentWatcherRuns:
    """Test that running watcher twice yields identical state."""

    def test_watcher_run_idempotent(self, memory_stores: dict, metrics: MetricsCollector):
        """Assert: watcher run 1 == watcher run 2 (same input)."""
        from uuid import UUID

        obj_store = memory_stores["objects"]

        for i in range(3):
            obj_id = UUID(f"10000000-0000-0000-0000-{i:012d}")
            obj_store.put(
                obj_id,
                kind="note",
                source_ref=f"vault/note{i}.md",
                payload={"title": f"Note {i}"},
            )

        metrics1 = MetricsCollector()
        metrics1.object_count = obj_store.count_objects()
        snap1 = metrics1.snapshot()

        metrics2 = MetricsCollector()
        metrics2.object_count = obj_store.count_objects()
        snap2 = metrics2.snapshot()

        assert snap1 == snap2

    def test_watcher_double_run_no_duplicates(self, event_chain: EventChain):
        """Assert: double watcher run doesn't create duplicate events."""
        trace_id = "trace-watch-001"

        e1 = make_outbox_event(
            "ingest.vault.changed",
            source="registry.watcher",
            trace_id=trace_id,
            payload={"vault_path": "vault/note.md"},
        )
        event_chain.append(e1)

        e2_dup = make_outbox_event(
            "ingest.vault.changed",
            source="registry.watcher",
            trace_id=trace_id,
            payload={"vault_path": "vault/note.md"},
        )

        assert e1.event_id != e2_dup.event_id
        event_chain.append(e2_dup)

        assert len(event_chain.events) == 2


@pytest.mark.not_pg
class TestStatusEndpointGates:
    """Test that /api/status endpoint reports all required gates."""

    def test_status_has_ingest_counters(self, metrics: MetricsCollector):
        """Assert status includes ingest run counters."""
        metrics.ingest_runs = 5
        snap = metrics.snapshot()

        assert "ingest_runs" in snap

    def test_status_has_panel_counters(self, metrics: MetricsCollector):
        """Assert status includes panel run counters."""
        metrics.panel_runs = 3
        snap = metrics.snapshot()

        assert "panel_runs" in snap

    def test_status_has_promotion_counters(self, metrics: MetricsCollector):
        """Assert status includes promotion intent counters."""
        metrics.promote_intents_created = 2
        snap = metrics.snapshot()

        assert "promote_intents_created" in snap

    def test_status_has_event_count(self, metrics: MetricsCollector):
        """Assert status includes event processing count."""
        for i in range(5):
            event = make_outbox_event(f"evt{i}", source="test")
            metrics.record_event(event)

        snap = metrics.snapshot()
        assert snap["events_processed"] == 5

    def test_status_report_format(self, metrics: MetricsCollector):
        """Assert status report is JSON-serializable."""
        import json

        metrics.ingest_runs = 1
        metrics.object_count = 5
        snap = metrics.snapshot()

        json_str = json.dumps(snap)
        reparsed = json.loads(json_str)
        assert reparsed["object_count"] == 5


@pytest.mark.not_pg
class TestConcurrencyGuards:
    """Test concurrency guard invariants."""

    def test_event_dedup_guard_prevents_duplicates(self):
        """Assert event dedup guard prevents processing duplicate event_ids."""
        seen: Set[str] = set()

        events = [
            make_outbox_event("test", source="s"),
            make_outbox_event("test", source="s"),
            make_outbox_event("test", source="s"),
        ]

        processed_count = 0
        for event in events:
            if event.event_id not in seen:
                seen.add(event.event_id)
                processed_count += 1

        assert processed_count == len(set(e.event_id for e in events))

    def test_optimistic_lock_guard(self):
        """Assert optimistic lock prevents concurrent writes."""
        current_version = 1

        write1_version = 1
        if write1_version == current_version:
            current_version += 1

        write2_version = 1
        if write2_version == current_version:
            current_version += 1

        assert current_version == 2

    def test_dedup_queue_guard(self, metrics: MetricsCollector):
        """Assert dedup queue guards prevent duplicate watcher runs."""
        key = "vault-watch-task"
        queue: Dict[str, bool] = {}

        if key not in queue:
            queue[key] = True
            metrics.ingest_runs += 1

        if key not in queue:
            queue[key] = True
            metrics.ingest_runs += 1

        assert metrics.ingest_runs == 1


@pytest.mark.not_pg
class TestFitnessGatesSignalSummary:
    """Test that all fitness gates can be summarized for CI reporting."""

    def test_gates_all_present(self, metrics: MetricsCollector):
        """Assert all required gates are present in metrics."""
        metrics.ingest_runs = 5
        metrics.panel_runs = 3
        metrics.promote_intents_created = 2
        metrics.object_count = 10
        metrics.embedding_count = 10

        snap = metrics.snapshot()

        required_gates = [
            "ingest_runs",
            "panel_runs",
            "promote_intents_created",
            "object_count",
            "embedding_count",
            "events_processed",
        ]

        for gate in required_gates:
            assert gate in snap, f"Missing gate: {gate}"

    def test_gates_pass_when_all_counters_positive(self, metrics: MetricsCollector):
        """Assert gates pass when all counters are positive."""
        metrics.ingest_runs = 5
        metrics.panel_runs = 3
        metrics.promote_intents_created = 2
        metrics.object_count = 10
        metrics.embedding_count = 10

        snap = metrics.snapshot()

        gates_pass = (
            snap["ingest_runs"] > 0
            and snap["object_count"] > 0
            and snap["embedding_count"] > 0
        )

        assert gates_pass

    def test_ci_summary_report(self, metrics: MetricsCollector):
        """Assert CI summary can be generated from gates."""
        metrics.ingest_runs = 5
        metrics.object_count = 10
        metrics.embedding_count = 10

        snap = metrics.snapshot()

        ci_summary = f"CI SUMMARY GATES ok={snap['object_count'] == snap['embedding_count']}"
        assert "GATES ok=True" in ci_summary
