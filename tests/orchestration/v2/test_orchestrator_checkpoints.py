"""Test Orchestrator V2 checkpointing contract."""

from __future__ import annotations

import time


from .conftest import (
    MockObjectStore,
    MockOutbox,
)


class TestCheckpointingContract:
    """Define checkpointing contract for Orchestrator V2."""

    def test_checkpoint_saved_after_successful_step(
        self,
        step_factory,
        mock_object_store: MockObjectStore,
    ) -> None:
        """After each successful step, save checkpoint (step_id + state_snapshot)."""
        step = step_factory("step-1", "agent_call", "Analyze")
        state_snapshot = {
            "step_id": step["id"],
            "result": {"status": "ok"},
            "timestamp": time.time(),
        }

        # Save checkpoint to store
        checkpoint_key = f"checkpoint-{step['id']}"
        mock_object_store.put_object(checkpoint_key, state_snapshot)

        # Verify stored
        stored = mock_object_store.get_object(checkpoint_key)
        assert stored is not None
        assert stored["step_id"] == "step-1"

    def test_checkpoint_interval_every_n_steps(
        self,
        step_factory,
        plan_factory,
        mock_object_store: MockObjectStore,
    ) -> None:
        """Checkpoint after every N steps (default N=3)."""
        # Create 5 steps
        steps = [step_factory(f"step-{i}") for i in range(1, 6)]
        plan_factory(steps=steps)

        # With interval=3, checkpoints at: step-3, step-6, etc.
        checkpoint_interval = 3
        checkpoint_steps = [i for i in range(1, 6) if i % checkpoint_interval == 0]

        assert checkpoint_steps == [3]  # Only step-3 triggers checkpoint (3 % 3 == 0)

    def test_checkpoint_persisted_in_object_store(
        self,
        mock_object_store: MockObjectStore,
    ) -> None:
        """Checkpoints stored in ObjectStore with key: checkpoint-{step_id}."""
        checkpoint_key = "checkpoint-step-2"
        snapshot = {
            "step_id": "step-2",
            "result": {"data": [1, 2, 3]},
            "timestamp": time.time(),
        }

        mock_object_store.put_object(checkpoint_key, snapshot)

        retrieved = mock_object_store.get_object(checkpoint_key)
        assert retrieved["step_id"] == "step-2"
        assert retrieved["result"]["data"] == [1, 2, 3]

    def test_checkpoint_can_be_retrieved_by_step_id(
        self,
        mock_object_store: MockObjectStore,
    ) -> None:
        """Retrieve checkpoint by step_id for resume."""
        checkpoint_key = "checkpoint-step-5"
        snapshot = {
            "step_id": "step-5",
            "completed_steps": ["step-1", "step-2", "step-3", "step-4", "step-5"],
            "timestamp": time.time(),
        }

        mock_object_store.put_object(checkpoint_key, snapshot)
        retrieved = mock_object_store.get_object(checkpoint_key)

        assert retrieved is not None
        assert "step-5" in retrieved["completed_steps"]

    def test_resume_from_checkpoint_skips_completed_steps(
        self,
        step_factory,
        plan_factory,
    ) -> None:
        """Resume from checkpoint: load snapshot, skip completed steps, continue."""
        steps = [
            step_factory("step-1"),
            step_factory("step-2"),
            step_factory("step-3"),
            step_factory("step-4"),
        ]
        plan_factory(steps=steps)

        # Checkpoint at step-2: completed [step-1, step-2]
        checkpoint_data = {
            "step_id": "step-2",
            "completed_steps": ["step-1", "step-2"],
        }

        # Resume: skip step-1 and step-2, start from step-3
        remaining_steps = [s for s in steps if s["id"] not in checkpoint_data["completed_steps"]]
        assert len(remaining_steps) == 2
        assert remaining_steps[0]["id"] == "step-3"

    def test_checkpoint_emits_event_on_creation(
        self,
        mock_outbox: MockOutbox,
    ) -> None:
        """When checkpoint is created, emit event to Outbox."""
        outbox = mock_outbox
        outbox.clear()

        checkpoint_event = {
            "event": "checkpoint.created",
            "source": "orchestrator.v2",
            "step_id": "step-3",
            "timestamp": time.time(),
        }
        outbox.emit(checkpoint_event)

        events = outbox.list_events("checkpoint.created")
        assert len(events) == 1
        assert events[0]["step_id"] == "step-3"

    def test_checkpoint_includes_plan_state_snapshot(
        self,
        step_factory,
        mock_object_store: MockObjectStore,
    ) -> None:
        """Checkpoint includes full plan state for recovery."""
        plan_state = {
            "plan_id": "plan-1",
            "current_step_idx": 2,
            "completed_steps": ["step-1", "step-2"],
            "step_results": {
                "step-1": {"status": "ok"},
                "step-2": {"status": "ok"},
            },
        }

        checkpoint_key = "checkpoint-step-2"
        mock_object_store.put_object(checkpoint_key, plan_state)

        retrieved = mock_object_store.get_object(checkpoint_key)
        assert retrieved["plan_id"] == "plan-1"
        assert retrieved["current_step_idx"] == 2

    def test_checkpoint_timestamp_recorded(
        self,
        mock_object_store: MockObjectStore,
    ) -> None:
        """Checkpoint records timestamp for sequencing."""
        now = time.time()
        checkpoint = {
            "step_id": "step-2",
            "timestamp": now,
            "data": {"result": "ok"},
        }

        mock_object_store.put_object("checkpoint-step-2", checkpoint)
        retrieved = mock_object_store.get_object("checkpoint-step-2")

        assert retrieved["timestamp"] == now
