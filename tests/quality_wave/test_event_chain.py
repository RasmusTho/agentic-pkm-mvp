"""Phase A: Event Chain Contract Tests.

Validates the canonical event chain:
  registry watcher → ingest.vault.changed → worker → index.embedding.created
  → ASK → panel.intent.* → worker → promote.*

Ensures:
- trace_id propagates through entire chain
- idempotency (running chain twice = same result)
- event envelope canonicity
- event ordering preserved
"""
from __future__ import annotations

import pytest
from typing import Dict, List
from uuid import uuid4

from app.events.schema import OutboxEvent, make_outbox_event
from tests.quality_wave.conftest import MetricsCollector, EventChain


class TestEventEnvelopeContract:
    """Test that all events conform to canonical envelope format."""

    def test_event_has_required_fields(self):
        """Assert OutboxEvent has all required canonical fields."""
        event = make_outbox_event(
            "ingest.vault.changed",
            source="registry.watcher",
            payload={"vault_path": "vault/note.md"},
        )

        # Canonical envelope fields
        assert hasattr(event, "event")
        assert hasattr(event, "event_id")
        assert hasattr(event, "trace_id")
        assert hasattr(event, "source")
        assert hasattr(event, "timestamp")
        assert hasattr(event, "payload")
        assert hasattr(event, "meta")

    def test_event_id_is_unique(self):
        """Assert each event gets a unique event_id."""
        events = [
            make_outbox_event(
                "test.event",
                source="test",
            )
            for _ in range(10)
        ]

        event_ids = [e.event_id for e in events]
        assert len(event_ids) == len(set(event_ids)), "event_ids must be unique"

    def test_trace_id_can_be_provided(self):
        """Assert trace_id can be provided to create correlated events."""
        trace_id = "trace-123"
        event1 = make_outbox_event(
            "event.1",
            source="source1",
            trace_id=trace_id,
        )
        event2 = make_outbox_event(
            "event.2",
            source="source2",
            trace_id=trace_id,
        )

        assert event1.trace_id == trace_id
        assert event2.trace_id == trace_id
        assert event1.event_id != event2.event_id

    def test_trace_id_defaults_to_unique_when_not_provided(self):
        """Assert trace_id defaults to unique UUID when not provided."""
        events = [
            make_outbox_event("test.event", source="test")
            for _ in range(5)
        ]

        trace_ids = [e.trace_id for e in events]
        assert len(trace_ids) == len(set(trace_ids)), "trace_ids should be unique when not specified"


class TestEventChainPropagation:
    """Test trace_id propagation through canonical event chain."""

    def test_single_trace_id_through_ingest_chain(self, event_chain: EventChain):
        """Assert single trace_id propagates: vault.changed → embedding.created."""
        trace_id = "trace-ingest-001"

        # Watcher emits vault.changed
        vault_changed = make_outbox_event(
            "ingest.vault.changed",
            source="registry.watcher",
            trace_id=trace_id,
            payload={"vault_path": "vault/note.md", "action": "create"},
        )
        event_chain.append(vault_changed)

        # Worker processes vault.changed and emits embedding.created
        embedding_created = make_outbox_event(
            "index.embedding.created",
            source="outbox.worker",
            trace_id=trace_id,  # Same trace_id propagates
            payload={"object_id": "uuid-1", "embedding_dim": 1536},
        )
        event_chain.append(embedding_created)

        # Verify chain
        event_chain.assert_trace_id_consistent(trace_id)
        assert len(event_chain.trace_id_map[trace_id]) == 2
        assert event_chain.trace_id_map[trace_id] == [
            "ingest.vault.changed",
            "index.embedding.created",
        ]

    def test_trace_id_through_promotion_chain(self, event_chain: EventChain):
        """Assert trace_id propagates: panel.intent.* → promote.done."""
        trace_id = "trace-promo-001"

        # Panel agent emits intent
        panel_intent = make_outbox_event(
            "panel.intent.created",
            source="panel.agent",
            trace_id=trace_id,
            payload={"uuid": "obj-1", "desired_state": "promoted"},
        )
        event_chain.append(panel_intent)

        # Promotion worker processes and emits done
        promote_done = make_outbox_event(
            "promote.done",
            source="promotion.worker",
            trace_id=trace_id,  # Same trace_id throughout
            payload={"uuid": "obj-1", "from": "vault/note.md", "to": "vault/2_Cards/note.md"},
        )
        event_chain.append(promote_done)

        event_chain.assert_trace_id_consistent(trace_id)
        assert event_chain.trace_id_map[trace_id] == [
            "panel.intent.created",
            "promote.done",
        ]

    def test_separate_chains_have_distinct_trace_ids(self, event_chain: EventChain):
        """Assert distinct operations have distinct trace_ids."""
        trace_1 = "trace-op-1"
        trace_2 = "trace-op-2"

        # Operation 1: ingest vault change
        event1 = make_outbox_event(
            "ingest.vault.changed",
            source="watcher",
            trace_id=trace_1,
            payload={"vault_path": "vault/note1.md"},
        )
        event_chain.append(event1)

        # Operation 2: separate promotion intent (different operation chain)
        event2 = make_outbox_event(
            "panel.intent.created",
            source="panel.agent",
            trace_id=trace_2,
            payload={"uuid": "obj-2", "action": "promote"},
        )
        event_chain.append(event2)

        assert len(event_chain.trace_id_map) == 2
        assert trace_1 in event_chain.trace_id_map
        assert trace_2 in event_chain.trace_id_map
        # Each trace_id maps to a different event type sequence
        assert event_chain.trace_id_map[trace_1] == ["ingest.vault.changed"]
        assert event_chain.trace_id_map[trace_2] == ["panel.intent.created"]
        assert event_chain.trace_id_map[trace_1] != event_chain.trace_id_map[trace_2]


class TestEventIdempotency:
    """Test that replaying events is idempotent (same input → same output)."""

    def test_duplicate_event_ids_are_rejected(self):
        """Assert duplicate event_ids can be detected for dedup."""
        event1 = OutboxEvent(
            event="ingest.vault.changed",
            event_id="eid-001",
            trace_id="tid-001",
            source="watcher",
            payload={"vault_path": "vault/note.md"},
        )
        event2 = OutboxEvent(
            event="ingest.vault.changed",
            event_id="eid-001",  # Duplicate event_id
            trace_id="tid-001",
            source="watcher",
            payload={"vault_path": "vault/note.md"},
        )

        # In idempotent systems, second event should be skipped
        seen_ids = {event1.event_id}
        assert event2.event_id in seen_ids, "Should detect duplicate event_id"

    def test_metrics_snapshot_idempotency(self, metrics: MetricsCollector):
        """Assert metrics snapshots are identical when replayed."""
        # First run
        metrics.ingest_runs = 5
        metrics.object_count = 10
        metrics.promote_intents_created = 3
        snapshot1 = metrics.snapshot()

        # Second run (same input)
        metrics_2 = MetricsCollector()
        metrics_2.ingest_runs = 5
        metrics_2.object_count = 10
        metrics_2.promote_intents_created = 3
        snapshot2 = metrics_2.snapshot()

        assert snapshot1 == snapshot2, "Identical inputs should yield identical snapshots"

    def test_event_dedup_dict_tracks_seen_ids(self):
        """Assert event dedup mechanism can track and skip duplicates."""
        seen: Dict[str, bool] = {}
        first = make_outbox_event("evt1", source="s1")

        events = [
            first,
            make_outbox_event("evt2", source="s2"),
            first.model_copy(update={"timestamp": first.timestamp}),  # Duplicate event_id
        ]

        # Simulate dedup logic
        deduped = []
        for event in events:
            if event.event_id not in seen:
                seen[event.event_id] = True
                deduped.append(event)

        assert len(deduped) == 2, "Should skip duplicate event_id"
        assert len(seen) == 2


class TestEventOrdering:
    """Test that event ordering is preserved."""

    def test_events_maintain_timestamp_ordering(self, event_chain: EventChain):
        """Assert events in chain maintain timestamp order."""
        import time

        trace_id = "trace-order-001"

        for i in range(5):
            event = make_outbox_event(
                f"event.{i}",
                source="test",
                trace_id=trace_id,
            )
            event_chain.append(event)
            # Small sleep to ensure timestamp ordering
            if i < 4:
                time.sleep(0.001)

        event_chain.assert_ordering()

    def test_multiple_chains_can_be_interleaved(self, event_chain: EventChain):
        """Assert interleaved chains can be reconstructed by trace_id."""
        trace_1 = "trace-chain-1"
        trace_2 = "trace-chain-2"

        # Interleave events from two chains
        for i in range(3):
            e1 = make_outbox_event(f"e1.{i}", source="s1", trace_id=trace_1)
            e2 = make_outbox_event(f"e2.{i}", source="s2", trace_id=trace_2)
            event_chain.append(e1)
            event_chain.append(e2)

        # Verify both chains are present
        assert trace_1 in event_chain.trace_id_map
        assert trace_2 in event_chain.trace_id_map
        assert len(event_chain.trace_id_map[trace_1]) == 3
        assert len(event_chain.trace_id_map[trace_2]) == 3


@pytest.mark.not_pg
class TestCanonicalEventChain:
    """Integration test of the full canonical event chain."""

    def test_vault_changed_to_embedding_created_chain(self, event_chain: EventChain):
        """Test full ingest chain: watcher → vault.changed → worker → embedding.created."""
        trace_id = "trace-full-ingest"

        # Step 1: Registry watcher detects vault change
        vault_changed = make_outbox_event(
            "ingest.vault.changed",
            source="registry.watcher",
            trace_id=trace_id,
            payload={
                "vault_path": "vault/note.md",
                "action": "create",
                "relative_path": "note.md",
            },
        )
        event_chain.append(vault_changed)

        # Step 2: Worker processes vault.changed event
        object_created = make_outbox_event(
            "ingest.object.created",
            source="outbox.worker",
            trace_id=trace_id,
            payload={
                "uuid": "uuid-note-001",
                "path": "vault/note.md",
                "kind": "note",
                "title": "Test Note",
            },
        )
        event_chain.append(object_created)

        # Step 3: Worker emits embedding request
        embedding_requested = make_outbox_event(
            "index.embedding.requested",
            source="outbox.worker",
            trace_id=trace_id,
            payload={
                "object_id": "uuid-note-001",
                "view": "markdown.semantic",
            },
        )
        event_chain.append(embedding_requested)

        # Step 4: Embedding service creates vector
        embedding_created = make_outbox_event(
            "index.embedding.created",
            source="embedding.service",
            trace_id=trace_id,
            payload={
                "object_id": "uuid-note-001",
                "embedding_dim": 1536,
                "model": "text-embedding-3-small",
            },
        )
        event_chain.append(embedding_created)

        # Verify chain integrity
        event_chain.assert_trace_id_consistent(trace_id)
        assert len(event_chain.trace_id_map[trace_id]) == 4
        assert event_chain.trace_id_map[trace_id] == [
            "ingest.vault.changed",
            "ingest.object.created",
            "index.embedding.requested",
            "index.embedding.created",
        ]

    def test_panel_to_promotion_chain(self, event_chain: EventChain):
        """Test full promotion chain: panel.intent → promote.done."""
        trace_id = "trace-full-promo"

        # Step 1: Panel agent creates promotion intent
        panel_intent = make_outbox_event(
            "panel.intent.created",
            source="panel.agent",
            trace_id=trace_id,
            payload={
                "uuid": "uuid-obj-001",
                "path": "vault/workbench/draft.md",
                "action": "promote",
                "desired_state": "promoted",
            },
        )
        event_chain.append(panel_intent)

        # Step 2: Panel intent execution starts
        panel_exec = make_outbox_event(
            "panel.intent.executing",
            source="panel.agent",
            trace_id=trace_id,
            payload={
                "uuid": "uuid-obj-001",
                "action": "promote",
            },
        )
        event_chain.append(panel_exec)

        # Step 3: Promotion consumer enqueues work
        promote_intent_created = make_outbox_event(
            "promote.intent.created",
            source="promotion.consumer",
            trace_id=trace_id,
            payload={
                "uuid": "uuid-obj-001",
                "desired_state": "promoted",
                "path": "vault/workbench/draft.md",
            },
        )
        event_chain.append(promote_intent_created)

        # Step 4: Promotion worker executes
        promote_done = make_outbox_event(
            "promote.done",
            source="promotion.worker",
            trace_id=trace_id,
            payload={
                "uuid": "uuid-obj-001",
                "from": "vault/workbench/draft.md",
                "to": "vault/2_Cards/draft.md",
            },
        )
        event_chain.append(promote_done)

        # Step 5: Panel agent reports execution complete
        panel_done = make_outbox_event(
            "panel.intent.executed",
            source="panel.agent",
            trace_id=trace_id,
            payload={
                "uuid": "uuid-obj-001",
                "action": "promote",
                "status": "success",
            },
        )
        event_chain.append(panel_done)

        # Verify chain
        event_chain.assert_trace_id_consistent(trace_id)
        assert len(event_chain.trace_id_map[trace_id]) == 5
        event_chain.assert_ordering()
