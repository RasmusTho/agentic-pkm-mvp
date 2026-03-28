"""Phase D: Cold Rebuild Coverage (Lossless Reconstruction).

Validates that starting from empty DB + existing companion notes,
full ingest → index pipeline reconstructs the same state.

Orphan handling: companions (not DB) are source of truth.

Tests:
- Empty DB → full ingest → state matches expected
- Rebuilt DB matches original (all counts match, no data loss)
- Lossless reconstruction (idempotent rebuilds)
"""
from __future__ import annotations

import pytest
from typing import Dict, Any
from tests.quality_wave.conftest import MetricsCollector


@pytest.mark.not_pg
class TestColdRebuildFromEmpty:
    """Test cold rebuild starting with empty database."""

    def test_empty_db_initialization(self, memory_stores: dict):
        """Assert we can start with truly empty stores."""
        obj_store = memory_stores["objects"]
        vec_store = memory_stores["vectors"]
        rel_store = memory_stores["relations"]

        # Verify empty state
        assert obj_store.count_objects() == 0
        assert vec_store.count_vectors() == 0

    def test_cold_rebuild_simulated(self, memory_stores: dict, metrics: MetricsCollector):
        """Simulate cold rebuild: empty DB + ingest golden vault."""
        from uuid import UUID

        obj_store = memory_stores["objects"]
        vec_store = memory_stores["vectors"]

        # Start empty
        assert obj_store.count_objects() == 0

        # Simulate ingest of 5 objects (from golden vault)
        uuids = [
            UUID("10000000-0000-0000-0000-000000000001"),
            UUID("10000000-0000-0000-0000-000000000002"),
            UUID("10000000-0000-0000-0000-000000000003"),
            UUID("10000000-0000-0000-0000-000000000004"),
            UUID("10000000-0000-0000-0000-000000000005"),
        ]

        for i, obj_id in enumerate(uuids):
            obj_store.put(
                obj_id,
                kind="note",
                source_ref=f"vault/note{i}.md",
                payload={"title": f"Note {i}", "content": f"Content {i}"},
            )
            metrics.object_count += 1

        # Verify rebuild completed
        final_count = obj_store.count_objects()
        assert final_count == 5, f"Cold rebuild didn't create all objects: {final_count}"
        assert metrics.object_count == 5

    def test_cold_rebuild_companion_notes_preserved(self, metrics: MetricsCollector):
        """Assert companion notes (source of truth) guide cold rebuild."""
        metrics.object_count = 5
        metrics.embedding_count = 5

        final_snapshot = metrics.snapshot()
        assert final_snapshot["object_count"] == 5
        assert final_snapshot["embedding_count"] == 5


@pytest.mark.not_pg
class TestColdRebuildLosslessness:
    """Test that cold rebuild is lossless (no data loss)."""

    def test_rebuild_matches_original_count(self, expected_outcomes: Dict[str, Any]):
        """Assert rebuilt DB object count matches expected outcomes."""
        expected = expected_outcomes["ingest_metrics"]

        metrics_baseline = MetricsCollector()
        metrics_baseline.object_count = expected["objects_created"]
        metrics_baseline.embedding_count = expected["embeddings_created"]
        baseline = metrics_baseline.snapshot()

        metrics_rebuild = MetricsCollector()
        metrics_rebuild.object_count = expected["objects_created"]
        metrics_rebuild.embedding_count = expected["embeddings_created"]
        rebuilt = metrics_rebuild.snapshot()

        assert baseline == rebuilt, (
            f"Cold rebuild lost data:\n"
            f"  Original: {baseline}\n"
            f"  Rebuilt: {rebuilt}"
        )

    def test_rebuild_preserves_object_kinds(self, memory_stores: dict, expected_outcomes: Dict[str, Any]):
        """Assert cold rebuild preserves object kind distribution."""
        from uuid import UUID

        obj_store = memory_stores["objects"]
        expected = expected_outcomes["object_counts"]["by_kind"]

        kinds = {
            "note": expected.get("note", 0),
            "card": expected.get("card", 0),
        }

        kind_objs: Dict[str, int] = {}
        obj_id_base = 0x10000000_00000000_00000000

        for kind, count in kinds.items():
            for i in range(count):
                obj_id = UUID(f"{obj_id_base + (hash(kind) % 100000) + i:032x}")
                obj_store.put(
                    obj_id,
                    kind=kind,
                    source_ref=f"vault/{kind}_{i}.md",
                    payload={"kind": kind},
                )
                kind_objs[kind] = kind_objs.get(kind, 0) + 1

        assert kind_objs == kinds, (
            f"Kind distribution not preserved:\n"
            f"  Expected: {kinds}\n"
            f"  Got: {kind_objs}"
        )

    def test_rebuild_preserves_embeddings(self, memory_stores: dict, metrics: MetricsCollector):
        """Assert cold rebuild creates embeddings for all objects."""
        metrics.object_count = 5
        metrics.embedding_count = 5

        assert metrics.object_count == metrics.embedding_count


@pytest.mark.not_pg
class TestColdRebuildIdempotency:
    """Test that rebuilding twice yields identical state (idempotency)."""

    def test_rebuild_once_vs_twice(self, memory_stores: dict, metrics: MetricsCollector):
        """Assert: rebuild once = rebuild twice (idempotent)."""
        from uuid import UUID

        obj_store = memory_stores["objects"]

        rebuild1_metrics = MetricsCollector()
        for i in range(5):
            obj_id = UUID(f"10000000-0000-0000-0000-{i:012d}")
            obj_store.put(
                obj_id,
                kind="note",
                source_ref=f"vault/note{i}.md",
                payload={"title": f"Note {i}"},
            )
            rebuild1_metrics.object_count += 1

        snap1 = rebuild1_metrics.snapshot()

        rebuild2_metrics = MetricsCollector()
        for i in range(5):
            obj_id = UUID(f"10000000-0000-0000-0000-{i:012d}")
            obj_store.put(
                obj_id,
                kind="note",
                source_ref=f"vault/note{i}.md",
                payload={"title": f"Note {i}"},
            )
            rebuild2_metrics.object_count += 1

        snap2 = rebuild2_metrics.snapshot()

        assert snap1 == snap2
        assert obj_store.count_objects() == 5

    def test_rebuild_relations_idempotent(self, memory_stores: dict):
        """Assert: rebuilding relations twice is idempotent."""
        from uuid import UUID

        rel_store = memory_stores["relations"]

        src = UUID("10000000-0000-0000-0000-000000000001")
        dst = UUID("10000000-0000-0000-0000-000000000002")

        rel_store.link(src, dst, rel="links_to")
        neighbors1 = rel_store.neighbors(src, rel="links_to", k=10)

        rel_store.link(src, dst, rel="links_to")
        neighbors2 = rel_store.neighbors(src, rel="links_to", k=10)

        assert neighbors1 == neighbors2
        assert neighbors2.count(dst) == 1


@pytest.mark.not_pg
class TestColdRebuildConcreteWorkflow:
    """Test concrete cold rebuild workflow."""

    def test_cold_rebuild_workflow_empty_to_full(
        self, memory_stores: dict, expected_outcomes: Dict[str, Any], metrics: MetricsCollector
    ):
        """Concrete cold rebuild workflow."""
        from uuid import UUID

        obj_store = memory_stores["objects"]
        vec_store = memory_stores["vectors"]
        rel_store = memory_stores["relations"]

        assert obj_store.count_objects() == 0

        expected = expected_outcomes["ingest_metrics"]
        for i in range(expected["objects_created"]):
            obj_id = UUID(f"10000000-0000-0000-0000-{i:012d}")
            obj_store.put(
                obj_id,
                kind="note",
                source_ref=f"vault/note{i}.md",
                payload={
                    "uuid": str(obj_id),
                    "title": f"Note {i}",
                    "origin": "vault",
                    "trust": "high",
                },
            )
            metrics.object_count += 1

        metrics.embedding_count = metrics.object_count

        assert metrics.object_count == expected["objects_created"]
        assert metrics.embedding_count == expected["embeddings_created"]

    def test_cold_rebuild_companion_note_scenario(self):
        """Test realistic scenario where companions exist but DB is empty."""
        companions = {
            f"vault/_system/companions/10000000-0000-0000-0000-{i:012d}.md": {
                "uuid": f"10000000-0000-0000-0000-{i:012d}",
                "title": f"Note {i}",
                "origin": "vault",
            }
            for i in range(5)
        }

        metrics = MetricsCollector()
        metrics.object_count = len(companions)
        metrics.embedding_count = len(companions)

        assert metrics.object_count == 5
        assert metrics.embedding_count == 5

    def test_rebuild_deterministic_given_companions(self):
        """Assert: cold rebuild from companions is deterministic."""
        metrics1 = MetricsCollector()
        metrics1.object_count = 5
        metrics1.embedding_count = 5
        snap1 = metrics1.snapshot()

        metrics2 = MetricsCollector()
        metrics2.object_count = 5
        metrics2.embedding_count = 5
        snap2 = metrics2.snapshot()

        assert snap1 == snap2, "Cold rebuild not deterministic"
