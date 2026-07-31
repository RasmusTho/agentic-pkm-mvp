"""Episode Resolution Engine capability end-to-end fixture-day test.

Parent AC2 (docs/EPISODE_RESOLUTION_ENGINE/README.md :: Capability acceptance criteria); lands
with ERE-06 (#3181): "signals -> proposed episodes -> pending bindings -> quiesce -> closure ->
derived salience drop, all idempotent."

No live Postgres: every DB/vault I/O boundary ``run_segmentation_tick`` touches is stubbed at its
own module (the same house discipline ``tests/episodes/test_segmentation_core.py`` and
``tests/episodes/test_assignment.py`` already established for ERE-04/05) -- only the real guarded
episode-note write seam runs for real, against ``tmp_path``. The closure candidate reader is
replaced with an equivalent VAULT-scan (rather than the production ``episodes`` DB projection) so
this stays a ``not pg`` test while still exercising the real quiescence math against real on-disk
note state across two ticks.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app.episodes import closure as closure_module
from app.episodes import closure_decay
from app.episodes import segmenter
from app.episodes.closure import EPISODE_CLOSURE_QUIESCENCE_MINUTES, EpisodeCloseCandidate
from app.episodes.closure_decay import CLOSURE_DECAY_STEP_DOWN_FACTOR
from app.episodes.notes import EPISODE_NOTES_DIR, parse_episode_note
from app.episodes.segmenter import HEIMDAL_STREAM_ID, run_segmentation_tick
from app.heimdal.observation_log import ObservationRow
from app.retrieval.capability import RetrievalRequest, retrieve
from app.retrieval.hybrid import get_store, reset_durable_rebuild_state
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg


def _allow_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy", "reason": None})


def _dt(hour: int, minute: int = 0, day: int = 1) -> datetime:
    # A fixed, unambiguously "long past" fixture day: closure's own wall-clock quiescence check
    # always sees these bounds as quiesced relative to `_FIXED_NOW` below, independent of when
    # this test actually executes.
    return datetime(2020, 1, day, hour, minute, tzinfo=timezone.utc)


_FIXED_NOW = datetime(2020, 6, 1, tzinfo=timezone.utc)


def _heimdal_row(
    *,
    observation_id: str,
    observed_at_start: datetime,
    protagonist: str,
    heimdal_session_hint: str | None = None,
    scope_hint: str = "work",
    sequence: int = 1,
) -> ObservationRow:
    payload: dict[str, Any] = {
        "observation_id": observation_id,
        "observed_at_start": observed_at_start.isoformat(),
        "scope_hint": scope_hint,
        "attributions": [{"mention_id": protagonist, "resolution": "resolved"}],
    }
    if heimdal_session_hint is not None:
        payload["episode_id"] = heimdal_session_hint
    return ObservationRow(
        id=f"log-{observation_id}",
        topic="heimdal.observation.published",
        idempotency_key=f"k-{observation_id}",
        envelope={"payload": payload},
        created_at=_dt(12, 0),
        sequence=sequence,
    )


def _stub_segmentation_and_assignment_io(
    monkeypatch: pytest.MonkeyPatch, *, heimdal_rows: list[ObservationRow]
) -> list[dict[str, int]]:
    """Stub every ERE-04/ERE-05 I/O boundary (house pattern) so the REAL tick body -- frontier
    building, fold, emission, assignment diff -- runs without Postgres or live streams."""
    monkeypatch.setattr(
        segmenter,
        "enumerate_consumable_streams",
        lambda *a, **k: (SimpleNamespace(stream_id=HEIMDAL_STREAM_ID),),
    )
    monkeypatch.setattr(segmenter, "read_observations_for_consumer", lambda *a, **k: heimdal_rows)
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", lambda *a, **k: None)
    monkeypatch.setattr(segmenter.engine_state, "all_state_with_prefix", lambda prefix: {})
    monkeypatch.setattr(segmenter.engine_state, "set_state", lambda key, value: None)
    monkeypatch.setattr(segmenter.engine_state, "delete_state", lambda key: None)
    monkeypatch.setattr(segmenter, "read_candidate_episodes_for_scopes", lambda scopes: [])
    monkeypatch.setattr(segmenter, "read_existing_bindings", lambda refs: {})
    monkeypatch.setattr(segmenter, "read_existing_bindings_for_episodes", lambda episode_ids: {})

    commits: list[dict[str, int]] = []

    def _fake_commit(to_insert, to_correct, write_guard=None, vault_root=None):
        summary = {"pending": len(to_insert), "corrected": len(to_correct)}
        commits.append(summary)
        return summary

    monkeypatch.setattr(segmenter, "commit_assignment_diff", _fake_commit)
    return commits


def _fake_find_closable_from_vault(vault_root: Path):
    """ERE-06 closure candidates, re-derived from real on-disk Episode notes (equivalent to the
    production ``episodes`` DB projection, without needing Postgres) -- so closure idempotency
    across two ticks is proven against REAL note state, not a canned return value."""

    def _find(*, now: datetime | None = None, quiescence: timedelta | None = None) -> list[EpisodeCloseCandidate]:
        threshold = timedelta(minutes=EPISODE_CLOSURE_QUIESCENCE_MINUTES)
        notes_dir = vault_root / EPISODE_NOTES_DIR
        out: list[EpisodeCloseCandidate] = []
        if not notes_dir.is_dir():
            return out
        for note_path in sorted(notes_dir.glob("*.md")):
            fields = parse_episode_note(note_path.read_text(encoding="utf-8"))
            time_fields = fields.get("time") or {}
            if bool(time_fields.get("closed", False)):
                continue
            end_raw = time_fields.get("end")
            if not end_raw:
                continue
            end_dt = datetime.fromisoformat(str(end_raw).replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            if _FIXED_NOW - end_dt > threshold:
                out.append(
                    EpisodeCloseCandidate(
                        episode_id=str(fields["episode_id"]),
                        scope=str(fields["scope"]),
                        note_path=f"{EPISODE_NOTES_DIR}/{fields['episode_id']}.md",
                        time_end=end_dt,
                    )
                )
        return out

    return _find


def test_fixture_day_full_loop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"

    # Fixture day: signal A (09:00, alice, no session) then signal B (09:10, bob, session
    # "sess-b") -- B's disjoint protagonist set triggers a shift that closes A (bounds
    # [09:00, 09:00]) and opens B as a new, still-open, session-bound segment.
    row_a = _heimdal_row(observation_id="obs-a", observed_at_start=_dt(9, 0), protagonist="alice", sequence=1)
    row_b = _heimdal_row(
        observation_id="obs-b",
        observed_at_start=_dt(9, 10),
        protagonist="bob",
        heimdal_session_hint="sess-b",
        sequence=2,
    )
    _stub_segmentation_and_assignment_io(monkeypatch, heimdal_rows=[row_a, row_b])

    monkeypatch.setattr(closure_module, "find_closable_episodes", _fake_find_closable_from_vault(vault_root))
    monkeypatch.setattr(closure_module, "_count_active_bound_artifacts", lambda episode_id: 1)
    emitted: list[tuple[Any, str, bool]] = []
    monkeypatch.setattr(
        closure_module,
        "write_outbox_event",
        lambda event, *, idempotency_key, required_db=False: (
            emitted.append((event, idempotency_key, required_db)) or idempotency_key
        ),
    )
    # #3181 review fix: close_episode now ALSO syncs the `episodes` projection's `closed` column
    # itself (app.episodes.closure._sync_projection_closed) -- stub it like every other DB
    # boundary this fixture-day test stubs (house "not pg" discipline); the vault-scan fake above
    # already exercises the candidate-filtering behavior this sync exists to make real in
    # production, so this test only needs to prove close_episode CALLS it, not re-verify its SQL
    # (that is covered directly in tests/episodes/test_closure.py).
    projection_synced: list[str] = []
    monkeypatch.setattr(closure_module, "_sync_projection_closed", projection_synced.append)

    # --- Tick 1: signals -> episodes -> bindings -> quiesce -> closure -------------------------
    result_1 = run_segmentation_tick(vault_root=vault_root, write_guard=_allow_guard())

    assert len(result_1["proposed"]) == 1, result_1
    closed_episode_id = result_1["proposed"][0]
    assert result_1["assigned"]["pending"] == 1, result_1  # obs-a's provenance binding to A
    assert result_1["closed"] == [closed_episode_id], result_1
    assert result_1["events_emitted"] == 1, result_1
    assert len(emitted) == 1
    assert emitted[0][0].payload["episode_id"] == closed_episode_id
    assert projection_synced == [closed_episode_id]

    note_text = (vault_root / EPISODE_NOTES_DIR / f"{closed_episode_id}.md").read_text(encoding="utf-8")
    assert parse_episode_note(note_text)["time"]["closed"] is True

    # --- Tick 2 (at-least-once redelivery of the SAME rows): idempotent, nothing new -----------
    result_2 = run_segmentation_tick(vault_root=vault_root, write_guard=_allow_guard())

    assert result_2["proposed"] == [], result_2  # the note already exists -- no duplicate write
    assert result_2["closed"] == [], result_2  # already closed -- excluded from candidates
    assert result_2["events_emitted"] == 0, result_2
    assert len(emitted) == 1  # no second event

    # --- Retrieval bridge: the derived salience drop at the production retrieve() call site ----
    # A hypothetical artifact whose bundle was stamped `episode_ref: [closed_episode_id]` (what a
    # fully wired ERE-05 bundle-mutation pipeline produces for a vault-serialized artifact) now
    # carries the closure-derived drop; an artifact bound to the still-open session segment
    # carries none -- proving the SAME episode id the engine just closed is exactly the one
    # retrieval dampens, end to end.
    monkeypatch.setattr("app.retrieval.hybrid.embed_text", lambda text, language=None: [0.2, 0.2, 0.2])
    monkeypatch.setattr("app.retrieval.hybrid.embed_docs", lambda texts: ([[0.2, 0.2, 0.2] for _ in texts], {}))
    monkeypatch.setattr(
        closure_decay, "read_closed_episode_ids", lambda ids: {i for i in ids if i == closed_episode_id}
    )
    # This suite runs thousands of tests in one process; an EARLIER, unrelated test may have left
    # the retrieval store's durable-rebuild-cache flag set (app.retrieval.hybrid module state),
    # which would otherwise make this call revalidate against a real durable index with a
    # different embedding dimension than this test's own 3-dim fake. Force a clean in-memory-only
    # cache state before seeding.
    reset_durable_rebuild_state()
    get_store().set_documents(
        [
            {
                "doc_id": "artifact-closed",
                "text": "fixture day loop note",
                "payload": {"episode_ref": [closed_episode_id]},
            },
            {
                "doc_id": "artifact-open",
                "text": "fixture day loop note",
                "payload": {"episode_ref": ["ep-still-open-session-b"]},
            },
        ]
    )
    try:
        response = retrieve(RetrievalRequest(query="fixture day loop", k=2))
    finally:
        get_store().set_documents([])

    by_id = {hit.doc_id: hit for hit in response.hits}
    closed_hit = by_id["artifact-closed"]
    open_hit = by_id["artifact-open"]

    assert closed_hit.signal_payload.salience["episode_closure"] == {
        "closed": True,
        "factor": CLOSURE_DECAY_STEP_DOWN_FACTOR,
        "closed_episode_refs": [closed_episode_id],
    }
    assert open_hit.signal_payload.salience == {}
    assert closed_hit.score == pytest.approx(open_hit.score * CLOSURE_DECAY_STEP_DOWN_FACTOR)
