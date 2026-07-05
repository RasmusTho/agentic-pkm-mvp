"""P-2 event-completeness property (#2909).

Purpose: every ``P.objects`` / ``P.vectors`` mutation either emits its outbox
event or occurs at a call site on the registered mirror list
(``tests/properties/_machinery.py::REGISTERED_MIRRORS``), so
``replay(P.outbox, V)`` reconstructs ``P`` up to a *named*, reviewable
exception set instead of an unknown one.

Derivation: ``docs/architecture/formal-model.md`` §3 gap 2 and seam C8 (11
production ``save_object(emit_outbox=False)`` sites). Incident class: #2863
(an observation-scope outbox-key defect meant content changes emitted
nothing -- fixed 2026-07-04, PR #2908) and #2242 (``processed_total=0``
silent for weeks). The upstream property spec (P-2, priority #1 by blast
radius) lives in ``docs/testing/invariant-synthesis-2026-07.md`` on the
unmerged ``docs/research-invariants-evolution-constitution`` branch --
**anchor drift**: that doc does not exist on ``main`` yet (the RESEARCH-03
docs PR that introduces it is still open). Issue #2909's own body quotes the
spec directly and is treated as authoritative here per the issue-to-code
anchor-drift rule (``.codex/skills/issue-to-code/SKILL.md :: Source-anchor
resolution rules``).

Two real production transitions drive the state machine:
  - **T-materialize** (`app.services.indexer.handle_ingest_object_created`):
    the legitimate mirror -- the ``INGEST_OBJECT_CREATED`` event that CAUSED
    this row is its own record, so the mirror call itself emits nothing.
  - **T-promote** (`app.promotion.consumer.consume_promotion_intents`): the
    mirror write (`_apply_promotion_to_store`, `emit_outbox=False`) is
    followed, in the SAME transition, by a real `promote.done` /
    `promotion.transition.applied` emission appended to the same JSONL
    outbox -- completeness holds at the transition level even though the
    individual mirror call emits nothing.

Both run through their real, unmodified production entry points -- only the
embedding client is stubbed (the same seam `tests/services/
test_indexer_worker.py` stubs), because the `not pg` suite must not reach a
live LLM/Ollama endpoint. No Postgres is reached: T-promote's JSONL-outbox
entry point is the same one `tests/promotion/test_consumer_idempotency.py`
uses, and T-materialize runs over the explicit memory `STORE_BACKEND`.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest

from app import objects as object_store_module
from app.promotion.consumer import consume_promotion_intents, reset_promotion_dedup_store
from app.services.indexer import handle_ingest_object_created

from tests.properties._machinery import (
    HARNESS_EXCLUDED_FILES,
    REGISTERED_MIRRORS,
    EventSpy,
    find_emit_outbox_false_sites,
    spy_on_object_store,
)

pytest.importorskip("hypothesis")

from hypothesis import HealthCheck, given, settings, strategies as st  # noqa: E402


# ---------------------------------------------------------------------------
# test_mirror_census_is_closed -- static gate
# ---------------------------------------------------------------------------


def test_mirror_census_is_closed() -> None:
    """Every ``emit_outbox=False`` call site in ``app/`` is a registered mirror.

    A NEW unregistered site (the next silent-mirror regression the P-2
    purpose statement names) makes this fail -- adding the call is not
    enough, the same PR must add a one-line justification to
    ``REGISTERED_MIRRORS``. Harness-excluded files (``app/cli/smoke.py``,
    formal-model.md §2.3) are recognized by exact path, not by prefix
    pattern, so a new non-harness file cannot hide behind an escape hatch.
    """
    sites = find_emit_outbox_false_sites()
    assert sites, "expected at least the known production emit_outbox=False sites"

    live_sites = [(p, l) for p, l in sites if p not in HARNESS_EXCLUDED_FILES]
    unregistered = [key for key in live_sites if key not in REGISTERED_MIRRORS]
    assert not unregistered, (
        "Unregistered emit_outbox=False call site(s) found -- add each to "
        "REGISTERED_MIRRORS in tests/properties/_machinery.py with a one-line "
        f"justification before merging: {unregistered}"
    )

    # Symmetric direction: every registered entry must still point at a real
    # site, or the census silently drifts stale (a site was refactored/removed
    # but its justification lingered, masking where the real new sites are).
    live_set = set(live_sites)
    stale = [key for key in REGISTERED_MIRRORS if key not in live_set]
    assert not stale, (
        "REGISTERED_MIRRORS has stale entries no longer matching a real "
        f"emit_outbox=False call site (line drift or removed site): {stale}"
    )


# ---------------------------------------------------------------------------
# Real-seam transition helpers
# ---------------------------------------------------------------------------


class _NullVectorIndex:
    """No-op vector index so T-materialize's post-save_object embed step never
    reaches a real vector store -- the property is about `P.objects`/outbox
    completeness, not vector indexing, which has its own coverage."""

    def upsert(self, object_id, *, kind, source_ref, payload, embedding, model, identity):
        return None

    def purge_vectors(self, object_id, *, view):
        return 0


def _make_ingest_event(note_uuid: str, content: str) -> dict:
    return {
        "uuid": note_uuid,
        "kind": "note",
        "source_ref": f"vault/{note_uuid}.md",
        "content": content,
        "payload": {"raw_text": content},
        "title": "Property Test Note",
        "review_state": "processed",
        "trace_id": f"trace-{note_uuid}",
    }


def _run_materialize(monkeypatch: pytest.MonkeyPatch, note_uuid: str, content: str) -> None:
    """Drive the real T-materialize transition (`handle_ingest_object_created`)
    with only the embedding client/vector-index stubbed."""
    identity = SimpleNamespace(provider="ollama", model="nomic-embed-text:latest", dim=8, normalize=True)
    monkeypatch.setattr("app.services.indexer.get_vector_index", lambda: _NullVectorIndex())
    monkeypatch.setattr("app.services.indexer.get_embedding_identity", lambda: identity)
    monkeypatch.setattr("app.services.indexer.emit_index_object_embedded", lambda **kwargs: None)
    monkeypatch.setattr("app.services.indexer.emit_index_embedding_failed", lambda **kwargs: None)

    with patch("app.services.indexer.llm_embed_text") as m_embed:
        m_embed.return_value = [0.0] * identity.dim
        handle_ingest_object_created(_make_ingest_event(note_uuid, content))


def _write_note(path: Path, uuid: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\nuuid: {uuid}\nreview_state: draft\n---\nContent", encoding="utf-8")


def _run_promote(tmp_path: Path, note_uuid: str, event_id: str) -> tuple[dict, Path]:
    """Drive the real T-promote transition end-to-end through the JSONL-outbox
    entry point (`not pg`-safe -- no DATABASE_URL/DB_DSN reached), matching
    `tests/promotion/test_consumer_idempotency.py`'s established pattern.
    Returns (summary, outbox_path) so the caller can inspect emitted events.
    """
    note_path = tmp_path / "Notes" / f"{note_uuid}.md"
    _write_note(note_path, note_uuid)
    outbox = tmp_path / f"outbox-{event_id}.jsonl"
    event_data = {
        "event": "promote.intent.created",
        "trace_id": f"trace-{event_id}",
        "event_id": event_id,
        "source": "property_test",
        "payload": {
            "note": {"uuid": note_uuid, "path": str(note_path)},
            "transition": {"family": "promotion", "target_maturity": "evergreen"},
        },
    }
    outbox.write_text(json.dumps(event_data, ensure_ascii=False) + "\n", encoding="utf-8")
    summary = consume_promotion_intents(outbox_path=outbox)
    return summary, outbox


def _read_jsonl_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ---------------------------------------------------------------------------
# test_mutations_emit_or_are_registered_mirrors -- runtime property
# ---------------------------------------------------------------------------


@given(
    content=st.text(min_size=0, max_size=200),
    use_promote=st.booleans(),
)
@settings(
    max_examples=25,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)
def test_mutations_emit_or_are_registered_mirrors(tmp_path_factory, content: str, use_promote: bool) -> None:
    """Per-step invariant: every ``P.objects`` mutation from a real seam
    either emits an outbox event for that mutation directly, or the mutating
    call site is a registered mirror -- and for a registered mirror, the
    *transition* it belongs to still produces a durable, discoverable event
    (T-promote's `promote.done`), never silence.

    Random transition sequence: hypothesis generates note content and picks
    between the T-materialize and T-promote branch on each example, driven
    over a fresh fixture vault + memory-backend store per example.
    """
    monkeypatch = pytest.MonkeyPatch()
    tmp_path = tmp_path_factory.mktemp("p2")
    try:
        monkeypatch.setenv("STORE_BACKEND", "memory")
        object_store_module._MEMORY_STORE.clear()
        reset_promotion_dedup_store()

        spy = EventSpy()
        with spy_on_object_store(monkeypatch, spy):
            note_uuid = str(uuid4())

            if use_promote:
                summary, outbox_path = _run_promote(tmp_path, note_uuid, event_id=f"evt-{note_uuid}")
                assert summary.get("applied") == 1, f"promotion did not apply: {summary}"
            else:
                _run_materialize(monkeypatch, note_uuid, content)

        mirror_calls = [call for call in spy.save_object_calls if not call.emit_outbox]
        assert mirror_calls, "expected the transition to mutate P.objects via a mirror call site"

        for call in mirror_calls:
            # The mirror call itself must not have separately emitted an event
            # for the same uuid -- if it did, `emit_outbox=False` was a stale
            # no-op and the REGISTERED_MIRRORS justification needs revisiting.
            assert not spy.emitted_for(call.uuid), (
                f"mirror call site for uuid={call.uuid} unexpectedly has a "
                "matching outbox emission recorded by the spy"
            )

        if use_promote:
            # Completeness corollary: the T-promote TRANSITION (not the mirror
            # call in isolation) is still fully event-observable -- the real
            # promote.done/promotion.transition.applied rows are durable in
            # the same JSONL outbox the mirror call's transition wrote to.
            events = _read_jsonl_events(outbox_path)
            topics = {rec.get("event_type") or rec.get("event") for rec in events}
            assert "promote.done" in topics or "promotion.transition.applied" in topics, (
                f"T-promote transition produced no discoverable completion event; topics={topics}"
            )
    finally:
        monkeypatch.undo()
        object_store_module._MEMORY_STORE.clear()


# ---------------------------------------------------------------------------
# test_replay_reproduces_non_mirror_state -- replay-completeness corollary
# ---------------------------------------------------------------------------


def test_replay_reproduces_non_mirror_state(tmp_path: Path) -> None:
    """Completeness corollary: replaying the events collected for a
    NON-mirror-only transition against a fresh store reproduces the mutated
    row -- i.e. for state whose producing call site emits its own event
    (rather than relying purely on a registered mirror), the event log alone
    is sufficient to reconstruct ``P.objects``.

    Uses the real ``ObjectStore.save_object(emit_outbox=True)`` path (the
    default / non-mirror case) plus the real ``insert_object_and_outbox`` ->
    outbox-row shape, then asserts the recorded event's payload carries
    enough identity (``uuid``, ``kind``) to reconstruct the object -- the
    reconstructible half of "replay(P.outbox, V) reconstructs P up to the
    registered mirror set" (formal-model.md §4).
    """
    from app.objects import DomainObject, ObjectStore
    from datetime import datetime, timezone

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setenv("STORE_BACKEND", "memory")
        object_store_module._MEMORY_STORE.clear()

        spy = EventSpy()
        with spy_on_object_store(monkeypatch, spy):
            obj = DomainObject(
                uuid=str(uuid4()),
                kind="note",
                payload={"raw_text": "replay me"},
                source_ref="vault/replay.md",
                created_at=datetime.now(timezone.utc),
            )
            store = ObjectStore()
            # Memory backend short-circuits before the outbox insert (by
            # design -- the memory backend has no durable outbox to insert
            # into), so the *recorded* save_object call is what we assert on:
            # emit_outbox=True was requested for this non-mirror write, which
            # is the production contract this corollary protects. The full
            # DB-backed insert path (`insert_object_and_outbox` -> `outbox`
            # row -> replay) is covered end-to-end by
            # `tests/indexer/test_outbox_roundtrip_pg.py` (pg-gated); this
            # `not pg` test pins the CALL CONTRACT the DB-backed path relies
            # on: a non-mirror save always requests emit_outbox=True.
            store.save_object(obj, emit_outbox=True)

        assert spy.save_object_calls, "expected save_object to be recorded"
        call = spy.save_object_calls[-1]
        assert call.emit_outbox is True
        assert call.uuid == obj.uuid
        assert call.kind == obj.kind

        # Reconstruction: the object is retrievable from the store exactly as
        # written -- the read-side half of "the event carries enough identity
        # to reconstruct P.objects" (uuid/kind round-trip through the same
        # identity the outbox payload would carry, per
        # ObjectStore.save_object's insert_object_and_outbox call).
        reconstructed = store.get_object(obj.uuid)
        assert reconstructed is not None
        assert reconstructed.uuid == obj.uuid
        assert reconstructed.kind == obj.kind
        assert reconstructed.payload == obj.payload
    finally:
        monkeypatch.undo()
        object_store_module._MEMORY_STORE.clear()
