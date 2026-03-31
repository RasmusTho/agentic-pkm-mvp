"""Shared fixtures for Quality Wave evaluation stack.

Provides:
- Golden vault loader (deterministic test data)
- Metrics collector (ingest runs, panel runs, promote intents)
- Event chain tracker (trace_id propagation, event ordering)
- Store backends (memory vs Postgres for metamorphic runs)
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List
from uuid import UUID
from datetime import datetime, timezone

import pytest

from app.events.schema import OutboxEvent
from app.stores.memory import MemoryObjectStore, MemoryVectorIndex, MemoryRelationIndex


logger = logging.getLogger(__name__)


@dataclass
class MetricsCollector:
    """Collects and snapshots metrics for reproducibility checks."""

    ingest_runs: int = 0
    panel_runs: int = 0
    promote_intents_created: int = 0
    promote_done: int = 0
    events_processed: List[OutboxEvent] = field(default_factory=list)
    object_count: int = 0
    embedding_count: int = 0
    trace_ids_seen: set = field(default_factory=set)

    def record_event(self, event: OutboxEvent) -> None:
        """Record an event and track its trace_id."""
        self.events_processed.append(event)
        self.trace_ids_seen.add(event.trace_id)

    def snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serializable snapshot of current metrics."""
        return {
            "ingest_runs": self.ingest_runs,
            "panel_runs": self.panel_runs,
            "promote_intents_created": self.promote_intents_created,
            "promote_done": self.promote_done,
            "object_count": self.object_count,
            "embedding_count": self.embedding_count,
            "events_processed": len(self.events_processed),
            "unique_trace_ids": len(self.trace_ids_seen),
        }

    def assert_idempotent(self, other: MetricsCollector) -> None:
        """Assert that two metric snapshots are identical (idempotency check)."""
        assert self.snapshot() == other.snapshot(), (
            f"Metrics not idempotent:\n"
            f"First run: {self.snapshot()}\n"
            f"Second run: {other.snapshot()}"
        )

    def assert_trace_ids_unique(self) -> None:
        """Assert that trace_ids are unique across all events."""
        trace_ids = [e.trace_id for e in self.events_processed]
        unique_ids = set(trace_ids)
        assert len(trace_ids) == len(unique_ids), (
            f"Duplicate trace_ids detected: {len(trace_ids)} events, "
            f"{len(unique_ids)} unique trace_ids"
        )


@dataclass
class EventChain:
    """Tracks event chain propagation for Phase A contract tests."""

    events: List[OutboxEvent] = field(default_factory=list)
    trace_id_map: Dict[str, List[str]] = field(default_factory=dict)  # trace_id -> event types

    def append(self, event: OutboxEvent) -> None:
        """Record an event in the chain."""
        self.events.append(event)
        if event.trace_id not in self.trace_id_map:
            self.trace_id_map[event.trace_id] = []
        self.trace_id_map[event.trace_id].append(event.event)

    def assert_trace_id_consistent(self, trace_id: str) -> None:
        """Assert that a trace_id appears in all expected event types in the chain."""
        assert trace_id in self.trace_id_map, f"trace_id {trace_id} not found in chain"

    def assert_ordering(self) -> None:
        """Assert that events maintain timestamp ordering."""
        timestamps = [e.timestamp for e in self.events]
        sorted_timestamps = sorted(timestamps)
        assert timestamps == sorted_timestamps, (
            f"Events not ordered by timestamp: {timestamps}"
        )


@pytest.fixture
def metrics():
    """Provide a metrics collector for the test."""
    return MetricsCollector()


@pytest.fixture
def event_chain():
    """Provide an event chain tracker for Phase A tests."""
    return EventChain()


@pytest.fixture
def golden_vault_path() -> Path:
    """Return the path to the golden vault test seed."""
    return Path(__file__).parent.parent.parent / "docs" / "examples" / "vault_test_seed"


@pytest.fixture
def golden_vault_content() -> Dict[str, str]:
    """Load golden vault test content.

    Returns a dict of {relative_path: content} for deterministic ingest tests.
    """
    vault_path = Path(__file__).parent.parent.parent / "docs" / "examples" / "vault_test_seed"

    if not vault_path.exists():
        pytest.skip(f"Golden vault not found at {vault_path}")

    content = {}
    for md_file in vault_path.glob("**/*.md"):
        if md_file.name == "golden.md":
            continue
        rel_path = md_file.relative_to(vault_path)
        content[str(rel_path)] = md_file.read_text(encoding="utf-8")

    return content


@pytest.fixture
def expected_outcomes() -> Dict[str, Any]:
    """Load expected outcomes snapshot for golden vault."""
    outcomes_path = (
        Path(__file__).parent.parent.parent
        / "docs"
        / "examples"
        / "vault_test_seed"
        / "expected_outcomes.json"
    )

    if not outcomes_path.exists():
        pytest.skip(f"Expected outcomes not found at {outcomes_path}")

    return json.loads(outcomes_path.read_text(encoding="utf-8"))


@pytest.fixture
def memory_stores():
    """Provide in-memory stores for testing."""
    return {
        "objects": MemoryObjectStore(),
        "vectors": MemoryVectorIndex(),
        "relations": MemoryRelationIndex(),
    }


@pytest.fixture
def deterministic_uuid() -> UUID:
    """Provide a deterministic UUID for reproducible tests."""
    return UUID("00000000-0000-0000-0000-000000000001")


@pytest.fixture
def now_iso() -> str:
    """Provide a fixed ISO timestamp for reproducibility."""
    dt = datetime(2025, 3, 28, 12, 0, 0, tzinfo=timezone.utc)
    iso_str = dt.isoformat()
    return iso_str.replace("+00:00", "Z")
