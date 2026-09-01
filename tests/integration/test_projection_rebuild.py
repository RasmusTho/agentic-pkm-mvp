from __future__ import annotations

from uuid import UUID

import pytest

from app.components.embeddings import EmbeddingIdentity
from app.rebuildability import (
    DurableProjectionWork,
    ProjectionRelation,
    ProjectionReplayQueue,
    ProductProjectionReplayRefusal,
    ProductProjectionTargets,
    RetainedProjectionSource,
    load_durable_projection_work,
    rebuild_product_projections,
)
from app.stores.memory import MemoryObjectStore, MemoryRelationIndex, MemoryVectorIndex

pytestmark = pytest.mark.not_pg

IDENTITY = EmbeddingIdentity(provider="test", model="test-model", dim=3, normalize=False)
SOURCE_A = "Notes/a.md"
SOURCE_B = "Notes/b.md"
OBJECT_A = UUID("00000000-0000-0000-0000-0000000000a1")
OBJECT_B = UUID("00000000-0000-0000-0000-0000000000b2")


class _Cursor:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def execute(self, query: str, params: tuple[str, ...]) -> None:
        assert "from outbox" in query
        assert params == ("quarantined",)

    def fetchall(self) -> list[dict]:
        return self.rows

    def close(self) -> None:
        return None


class _Connection:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def cursor(self) -> _Cursor:
        return _Cursor(self.rows)


def _sources(tmp_path) -> list[RetainedProjectionSource]:
    notes = tmp_path / "Notes"
    notes.mkdir()
    (notes / "a.md").write_text(
        f"---\nuuid: {OBJECT_A}\n---\n\nCanonical alpha meaning.\n", encoding="utf-8"
    )
    (notes / "b.md").write_text(
        f"---\nuuid: {OBJECT_B}\n---\n\nCanonical beta meaning.\n", encoding="utf-8"
    )
    return [
        RetainedProjectionSource.from_retained_file(
            vault_root=tmp_path,
            object_id=OBJECT_A,
            source_identity=SOURCE_A,
            payload={"title": "Alpha", "kind": "note", "machine_cache": {"rank": 4}},
            embedding=[1.0, 0.0, 0.0],
            embedding_identity=IDENTITY,
            relations=(
                ProjectionRelation(
                    src_id=OBJECT_A,
                    dst_id=OBJECT_B,
                    relation_type="related_to",
                    payload={"weight": 1.0},
                ),
            ),
        ),
        RetainedProjectionSource.from_retained_file(
            vault_root=tmp_path,
            object_id=OBJECT_B,
            source_identity=SOURCE_B,
            payload={"title": "Beta", "kind": "note"},
            embedding=[0.0, 1.0, 0.0],
            embedding_identity=IDENTITY,
            memberships=(("tag", "continuity", {"machine_order": 99}),),
        ),
    ]


def _work(sources: list[RetainedProjectionSource]) -> DurableProjectionWork:
    event = {
        "event": "index.embedding.requested",
        "event_id": "evt-embedding-a",
        "trace_id": "trace-a",
        "source": "test-outbox-producer",
        "timestamp": "2026-09-01T00:00:00Z",
        "payload": {
            "object_id": str(OBJECT_A),
            "source_identity": SOURCE_A,
            "replay": sources[0].replay.as_dict(),
        },
    }
    return load_durable_projection_work(
        _Connection(
            [
                {
                    "id": "db-row-a",
                    "topic": "index.embedding.requested",
                    "payload": event,
                }
            ]
        )
    )[0]


def _targets() -> ProductProjectionTargets:
    return ProductProjectionTargets(
        objects=MemoryObjectStore(),
        vectors=MemoryVectorIndex(),
        relations=MemoryRelationIndex(),
        queue=ProjectionReplayQueue(),
    )


def test_object_vector_and_relation_projections_converge_from_retained_sources(tmp_path) -> None:
    sources = _sources(tmp_path)
    work = _work(sources)
    targets = _targets()

    summary = rebuild_product_projections(sources, [work], targets)

    assert summary.sources == 2
    assert summary.object_rows == summary.vector_rows == 2
    assert summary.relation_rows == summary.membership_rows == 1
    assert summary.queued_work == 1
    object_row = targets.objects.get(OBJECT_A)
    assert object_row is not None
    assert object_row["payload"]["replay"] == sources[0].replay.as_dict()
    assert [row["object_id"] for row in targets.vectors.all_rows()] == [OBJECT_A, OBJECT_B]
    assert targets.relations.neighbors(OBJECT_A, rel="related_to") == [OBJECT_B]
    assert [item.value for item in targets.relations.memberships(OBJECT_B)] == ["continuity"]
    assert targets.queue.pending["evt-embedding-a"].source_kind == "db_outbox"


def test_projection_replay_is_idempotent(tmp_path) -> None:
    sources = _sources(tmp_path)
    work = _work(sources)
    targets = _targets()

    first = rebuild_product_projections(sources, [work], targets)
    first_objects = {
        row["object_id"]: row["payload"] for row in targets.objects.list_objects(limit=None)
    }
    first_vectors = [
        (row["object_id"], row["payload"], row["embedding"])
        for row in targets.vectors.all_rows()
    ]
    second = rebuild_product_projections(sources, [work], targets)
    second_objects = {
        row["object_id"]: row["payload"] for row in targets.objects.list_objects(limit=None)
    }
    second_vectors = [
        (row["object_id"], row["payload"], row["embedding"])
        for row in targets.vectors.all_rows()
    ]

    assert first.queued_work == 1
    assert second.queued_work == 0
    assert second.duplicate_work == 1
    assert first_objects == second_objects
    assert first_vectors == second_vectors
    assert len(targets.queue.pending) == 1
    assert targets.relations.neighbors(OBJECT_A, rel="related_to") == [OBJECT_B]


def test_queue_rebuild_rejects_diagnostic_and_unknown_effect_sources(tmp_path) -> None:
    sources = _sources(tmp_path)
    targets = _targets()
    with pytest.raises(ProductProjectionReplayRefusal):
        DurableProjectionWork(
            event_id="audit-1",
            event="index.embedding.requested",
            source_identity=SOURCE_A,
            replay=sources[0].replay,
            source_kind="jsonl_audit",
        )
    unknown_event = {
        "event": "external.effect.execute",
        "event_id": "unknown-1",
        "trace_id": "trace-unknown",
        "source": "test-outbox-producer",
        "timestamp": "2026-09-01T00:00:00Z",
        "payload": {
            "source_identity": SOURCE_A,
            "replay": sources[0].replay.as_dict(),
        },
    }
    unknown_work = load_durable_projection_work(
        _Connection(
            [
                {
                    "id": "db-row-unknown",
                    "topic": "external.effect.execute",
                    "payload": unknown_event,
                }
            ]
        )
    )[0]
    with pytest.raises(ProductProjectionReplayRefusal):
        rebuild_product_projections(sources, [unknown_work], targets)
    with pytest.raises(ProductProjectionReplayRefusal):
        RetainedProjectionSource(
            object_id=OBJECT_A,
            source_identity=SOURCE_A,
            text="fabricated",
            payload={},
            embedding=[1.0, 0.0, 0.0],
            embedding_identity=IDENTITY,
        )
    assert targets.objects.count_objects() == 0
    assert targets.vectors.count_vectors() == 0
    assert targets.queue.pending == {}
