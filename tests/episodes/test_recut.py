"""Human re-cut, silence-is-acceptance, and binding-reconciliation tests (ERE-07, #3182).

Spec: ``docs/EPISODE_RESOLUTION_ENGINE/RESPECT_HUMAN_RECUT.md``.

- AC1: an operator edit to a proposed episode note is detected (writer-identity based, not
  content-heuristic) and flips ``segmentation: re-cut``. Verify:
  ``test_operator_edit_detected_as_recut``
- AC2 (enforcement): the engine's write path refuses to mutate the cut of an
  ``accepted``/``re-cut`` episode, asserted at the PRODUCTION write seam
  (``app.episodes.store.write_episode_note``). Verify: ``test_engine_cannot_overwrite_human_cut``
- AC3: new overlapping evidence after a re-cut/acceptance yields a new proposed episode, never an
  edit of the terminal note. Verify: ``test_new_evidence_becomes_new_proposal_not_edit``
- AC4: re-cut bounds/derived_from changes trigger binding reconciliation via the ERE-05
  correction path. Verify: ``test_recut_reconciles_bindings``
- AC5: acceptance-by-silence transitions ``proposed -> accepted`` after the named quiet window,
  with no notification/approval surface. Verify: ``test_silence_is_acceptance``
- AC6: split and merge fixture flows land in consistent state -- no orphaned bindings, no
  dangling ``parent_episode``. Verify: ``test_split_and_merge_flows_consistent``

Uses the ``not pg`` lane established by ``tests/episodes/test_episode_store.py`` /
``test_assignment.py``: real filesystem writes under ``tmp_path`` for episode notes (the real
production write seam), a small stateful in-memory fake standing in for
``app.episodes.engine_state`` (mirroring the persistence shape the real table provides), and
either monkeypatched capture of ``app.episodes.assignment``'s reconciliation functions (AC1/AC5/
AC6 wiring) or a fake ``conn_rw`` (AC4, exercising the real reconciliation SQL-shaping logic) --
no live Postgres needed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.episodes import assignment as assignment_module
from app.episodes import recut as recut_module
from app.episodes import store as store_module
from app.episodes.assignment import (
    BASIS_PROVENANCE,
    BINDING_STATE_ACTIVE,
    BINDING_TABLE,
)
from app.episodes.notes import episode_note_rel_path, parse_episode_note
from app.episodes.recut import (
    ACCEPTANCE_QUIET_WINDOW_MINUTES,
    compute_fields_hash,
    run_recut_tick,
)
from app.episodes.store import (
    EpisodeCutTerminalError,
    write_episode_note,
)
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg


def _allow_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy", "reason": None})


def _dt(hour: int, minute: int = 0, day: int = 11) -> datetime:
    return datetime(2026, 7, day, hour, minute, tzinfo=timezone.utc)


class _FakeEngineState:
    """Stateful in-memory stand-in for ``app.episodes.engine_state``, persisted across multiple
    tick calls within one test the same way the real Postgres-backed table would be."""

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}

    def all_state_with_prefix(self, prefix: str) -> dict[str, dict[str, Any]]:
        return {k: dict(v) for k, v in self._store.items() if k.startswith(prefix)}

    def set_state(self, key: str, value: dict[str, Any]) -> None:
        self._store[key] = dict(value)

    def delete_state(self, key: str) -> None:
        self._store.pop(key, None)


def _install_fake_engine_state(monkeypatch: pytest.MonkeyPatch) -> _FakeEngineState:
    fake = _FakeEngineState()
    monkeypatch.setattr(recut_module.engine_state, "all_state_with_prefix", fake.all_state_with_prefix)
    monkeypatch.setattr(recut_module.engine_state, "set_state", fake.set_state)
    monkeypatch.setattr(recut_module.engine_state, "delete_state", fake.delete_state)
    return fake


def _stub_bindings(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, Any]]]:
    """Replace app.episodes.recut's bound names for the ERE-05 reconciliation functions with
    capture-only stubs, isolating AC1/AC5/AC6 wiring tests from Postgres. Returns the call log:
    ``[("reconcile", {...}), ("withdraw", {...}), ...]``."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def _fake_reconcile(episode_id: str, *, scope: str, start=None, end=None, derived_from, write_guard=None, vault_root=None):
        calls.append(
            (
                "reconcile",
                {
                    "episode_id": episode_id,
                    "scope": scope,
                    "start": start,
                    "end": end,
                    "derived_from": list(derived_from),
                },
            )
        )
        return {"pending": 0, "corrected": 0}

    def _fake_withdraw(episode_id: str, *, write_guard=None, vault_root=None):
        calls.append(("withdraw", {"episode_id": episode_id}))
        return {"pending": 0, "corrected": 0}

    monkeypatch.setattr(recut_module, "reconcile_episode_bindings", _fake_reconcile)
    monkeypatch.setattr(recut_module, "withdraw_episode_bindings", _fake_withdraw)
    return calls


def _write_initial(
    vault_root: Path, *, episode_id: str, segmentation: str = "proposed", **overrides: Any
):
    kwargs: dict[str, Any] = dict(
        title="Debugging session",
        scope="work",
        start="2026-07-11T10:00:00+00:00",
        end="2026-07-11T11:00:00+00:00",
        protagonists=["p-1"],
        goal=["g-1"],
        derived_from=["heimdal.observations:seed"],
        segmentation=segmentation,
        episode_id=episode_id,
        vault_root=vault_root,
        write_guard=_allow_guard(),
    )
    kwargs.update(overrides)
    return write_episode_note(**kwargs)


def _edit_note_directly(vault_root: Path, episode_id: str, **field_overrides: Any) -> None:
    """Simulate a raw operator edit (Obsidian/external-sync/hand-edit) that bypasses
    ``app.episodes.store.write_episode_note`` entirely -- writes straight to the filesystem, the
    same as a human saving the note in their editor."""
    from app.episodes.notes import render_episode_note

    rel_path = episode_note_rel_path(episode_id)
    note_path = vault_root / rel_path
    fields = parse_episode_note(note_path.read_text(encoding="utf-8"))
    for key, value in field_overrides.items():
        if key.startswith("time."):
            time_fields = dict(fields.get("time") or {})
            time_fields[key.split(".", 1)[1]] = value
            fields["time"] = time_fields
        else:
            fields[key] = value
    note_path.write_text(render_episode_note(fields), encoding="utf-8")


# ---------------------------------------------------------------------------
# AC1 -- writer-identity-based re-cut detection
# ---------------------------------------------------------------------------


def test_operator_edit_detected_as_recut(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    calls = _stub_bindings(monkeypatch)
    _install_fake_engine_state(monkeypatch)

    episode_id = "ep-11111111-1111-4111-8111-111111111111"
    _write_initial(vault_root, episode_id=episode_id)

    # Tick 1: first sight -- adopts the baseline, no re-cut (nothing to diff against yet).
    result_1 = run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=_dt(10, 5))
    assert result_1["recut_detected"] == []
    tick1_reconcile = [args for kind, args in calls if kind == "reconcile" and args["episode_id"] == episode_id]
    assert tick1_reconcile and tick1_reconcile[0]["scope"] == "work"
    assert tick1_reconcile[0]["derived_from"] == ["heimdal.observations:seed"]
    assert tick1_reconcile[0]["start"] == _dt(10, 0) and tick1_reconcile[0]["end"] == _dt(11, 0)

    # A raw operator edit -- bypasses write_episode_note entirely, exactly like an Obsidian save.
    # Removes a protagonist and widens the end time (spec's own "Concretely" example).
    _edit_note_directly(vault_root, episode_id, **{"time.end": "2026-07-11T11:30:00+00:00"}, protagonists=[])

    # Tick 2: the on-disk content now diverges from the engine's own last-recorded write --
    # writer identity resolved by elimination (AC1), never by inspecting WHAT changed.
    result_2 = run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=_dt(10, 10))
    assert result_2["recut_detected"] == [episode_id]

    note_path = vault_root / episode_note_rel_path(episode_id)
    fields = parse_episode_note(note_path.read_text(encoding="utf-8"))
    assert fields["segmentation"] == "re-cut"
    # The human's own edits are preserved verbatim -- never reverted by the relabel write.
    assert fields["time"]["end"] == "2026-07-11T11:30:00+00:00"
    assert fields["protagonists"] == []

    # A third tick with no further change is a no-op -- the baseline now matches the re-cut note.
    result_3 = run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=_dt(10, 15))
    assert result_3["recut_detected"] == []


def test_recut_detection_is_writer_identity_not_content_heuristic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A note nobody has ever touched (first sight, no engine-recorded baseline) is adopted, not
    flagged -- there is no writer identity to contradict yet, regardless of its content."""
    vault_root = tmp_path / "vault"
    calls = _stub_bindings(monkeypatch)
    _install_fake_engine_state(monkeypatch)

    episode_id = "ep-22222222-1111-4111-8111-111111111111"
    _write_initial(vault_root, episode_id=episode_id, segmentation="re-cut")

    result = run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=_dt(10, 5))
    assert result["recut_detected"] == []
    assert any(kind == "reconcile" and args["episode_id"] == episode_id for kind, args in calls)


# ---------------------------------------------------------------------------
# AC2 (enforcement) -- terminality at the production write seam
# ---------------------------------------------------------------------------


def test_engine_cannot_overwrite_human_cut(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    vault_root = tmp_path / "vault"
    episode_id = "ep-33333333-1111-4111-8111-111111111111"
    _write_initial(vault_root, episode_id=episode_id, segmentation="proposed")

    # proposed -> accepted is a legitimate lifecycle relabel (not yet terminal beforehand).
    write_episode_note(
        title="Debugging session",
        scope="work",
        start="2026-07-11T10:00:00+00:00",
        end="2026-07-11T11:00:00+00:00",
        protagonists=["p-1"],
        goal=["g-1"],
        derived_from=["heimdal.observations:seed"],
        segmentation="accepted",
        episode_id=episode_id,
        vault_root=vault_root,
        write_guard=_allow_guard(),
    )

    note_path = vault_root / episode_note_rel_path(episode_id)
    before = note_path.read_bytes()

    # A machine attempt to widen/edit the now-ACCEPTED (machine-terminal) episode's cut -- e.g.
    # new evidence trying to extend it instead of becoming its own new proposal (AC3).
    caplog.set_level(logging.WARNING, logger=store_module.logger.name)
    with pytest.raises(EpisodeCutTerminalError):
        write_episode_note(
            title="Debugging session (extended)",
            scope="work",
            start="2026-07-11T10:00:00+00:00",
            end="2026-07-11T12:00:00+00:00",  # attempted cut mutation
            protagonists=["p-1"],
            goal=["g-1"],
            derived_from=["heimdal.observations:seed"],
            segmentation="accepted",
            episode_id=episode_id,
            vault_root=vault_root,
            write_guard=_allow_guard(),
        )

    # The note is byte-for-byte untouched.
    assert note_path.read_bytes() == before
    # Rejected + logged (not a silent no-op).
    assert any("rejected machine mutation of terminal cut" in rec.message for rec in caplog.records)

    # Same guard fires once the episode has been human re-cut instead of accepted. A re-cut is
    # never expressed as a call to write_episode_note with new values (that IS the mutation this
    # guard exists to block) -- it is a raw file edit, exactly like the real re-cut-detection
    # flow in app.episodes.recut. Write it directly, bypassing the seam, to set up this state.
    _edit_note_directly(
        vault_root, episode_id,
        segmentation="re-cut",
        protagonists=[],
        **{"time.end": "2026-07-11T11:30:00+00:00"},
    )
    before_recut = note_path.read_bytes()
    with pytest.raises(EpisodeCutTerminalError):
        write_episode_note(
            title="Debugging session",
            scope="work",
            start="2026-07-11T10:00:00+00:00",
            end="2026-07-11T11:30:00+00:00",
            protagonists=["p-injected-by-engine"],  # attempted cut mutation
            goal=["g-1"],
            derived_from=["heimdal.observations:seed"],
            segmentation="re-cut",
            episode_id=episode_id,
            vault_root=vault_root,
            write_guard=_allow_guard(),
        )
    assert note_path.read_bytes() == before_recut

    # A relabel that changes ONLY segmentation (echoing the cut back unchanged) is NOT blocked --
    # this is exactly the mechanism AC1/AC5 relabels rely on.
    write_episode_note(
        title="Debugging session",
        scope="work",
        start="2026-07-11T10:00:00+00:00",
        end="2026-07-11T11:30:00+00:00",
        protagonists=[],
        goal=["g-1"],
        derived_from=["heimdal.observations:seed"],
        segmentation="re-cut",  # unchanged value; proves same-value relabel still passes
        episode_id=episode_id,
        vault_root=vault_root,
        write_guard=_allow_guard(),
    )

    # `time.closed` remains mutable post-terminal (ERE-06 closure decay) -- not part of "the cut".
    write_episode_note(
        title="Debugging session",
        scope="work",
        start="2026-07-11T10:00:00+00:00",
        end="2026-07-11T11:30:00+00:00",
        closed=True,
        protagonists=[],
        goal=["g-1"],
        derived_from=["heimdal.observations:seed"],
        segmentation="re-cut",
        episode_id=episode_id,
        vault_root=vault_root,
        write_guard=_allow_guard(),
    )
    fields = parse_episode_note(note_path.read_text(encoding="utf-8"))
    assert fields["time"]["closed"] is True


# ---------------------------------------------------------------------------
# AC3 -- new evidence becomes a new proposal, never an edit of a terminal episode
# ---------------------------------------------------------------------------


def test_new_evidence_becomes_new_proposal_not_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from types import SimpleNamespace

    from app.episodes import closure as closure_module
    from app.episodes import segmenter
    from app.episodes.segmenter import HEIMDAL_STREAM_ID, run_segmentation_tick
    from app.heimdal.observation_log import ObservationRow

    vault_root = tmp_path / "vault"
    fake_state = _FakeEngineState()
    monkeypatch.setattr(segmenter.engine_state, "all_state_with_prefix", fake_state.all_state_with_prefix)
    monkeypatch.setattr(segmenter.engine_state, "set_state", fake_state.set_state)
    monkeypatch.setattr(segmenter.engine_state, "delete_state", fake_state.delete_state)
    monkeypatch.setattr(
        segmenter, "enumerate_consumable_streams", lambda *a, **k: (SimpleNamespace(stream_id=HEIMDAL_STREAM_ID),)
    )
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", lambda *a, **k: None)
    # ERE-06 (#3181): run_segmentation_tick now runs an unconditional closure pass
    # (app.episodes.closure.run_closure_tick) that reads the `episodes` DB projection for closable
    # candidates. This re-cut test drives the tick with no DB -- stub the closure candidate reader
    # to none so the tick stays DB-free (this test is about segmentation re-cut, not decay
    # closure; closure's own behaviour is covered in tests/episodes/test_closure.py).
    monkeypatch.setattr(closure_module, "find_closable_episodes", lambda **k: [])
    monkeypatch.setattr(segmenter, "read_candidate_episodes_for_scopes", lambda scopes: [])
    monkeypatch.setattr(segmenter, "read_existing_bindings", lambda refs: {})
    monkeypatch.setattr(segmenter, "read_existing_bindings_for_episodes", lambda episode_ids: {})
    monkeypatch.setattr(segmenter, "commit_assignment_diff", lambda *a, **k: {"pending": 0, "corrected": 0})

    def _row(obs_id: str, hour: int, minute: int) -> ObservationRow:
        payload = {
            "observation_id": obs_id,
            "observed_at_start": _dt(hour, minute).isoformat(),
            "scope_hint": "work",
        }
        return ObservationRow(
            id=f"log-{obs_id}", topic="heimdal.observation.published",
            idempotency_key=f"k-{obs_id}", envelope={"payload": payload},
            created_at=_dt(hour, minute), sequence=1,
        )

    # Tick 1: two signals, gap > 45min -- the FIRST closes into episode E1; the SECOND opens a
    # new segment that stays open.
    tick_1_rows = [_row("s1", 9, 0), _row("s2", 10, 0)]
    monkeypatch.setattr(segmenter, "read_observations_for_consumer", lambda *a, **k: tick_1_rows)
    result_1 = run_segmentation_tick(vault_root=vault_root, write_guard=_allow_guard())
    assert len(result_1["proposed"]) == 1
    e1 = result_1["proposed"][0]

    # Mark E1 accepted -- machine-terminal from here on.
    e1_fields = parse_episode_note((vault_root / episode_note_rel_path(e1)).read_text(encoding="utf-8"))
    time_fields = e1_fields["time"]
    write_episode_note(
        title=e1_fields["title"], scope=e1_fields["scope"], start=time_fields["start"],
        end=time_fields.get("end"), closed=bool(time_fields.get("closed", False)),
        protagonists=e1_fields.get("protagonists") or [], goal=e1_fields.get("goal") or [],
        derived_from=e1_fields.get("derived_from") or [], segmentation="accepted",
        episode_id=e1, vault_root=vault_root, write_guard=_allow_guard(),
    )
    e1_path = vault_root / episode_note_rel_path(e1)
    e1_bytes_before = e1_path.read_bytes()

    # Tick 2: genuinely NEW evidence, gap > 45min past the still-open second segment -- closes
    # IT into a new episode E2. E1 (accepted) must never be touched.
    tick_2_rows = [_row("s3", 11, 0)]
    monkeypatch.setattr(segmenter, "read_observations_for_consumer", lambda *a, **k: tick_2_rows)
    result_2 = run_segmentation_tick(vault_root=vault_root, write_guard=_allow_guard())

    assert len(result_2["proposed"]) == 1
    e2 = result_2["proposed"][0]
    assert e2 != e1
    assert e1_path.read_bytes() == e1_bytes_before


# ---------------------------------------------------------------------------
# AC4 -- binding reconciliation via the ERE-05 correction path
# ---------------------------------------------------------------------------


class _FakeCursor:
    def __init__(self, rows_by_episode: dict[str, list[dict[str, Any]]], executed: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._rows_by_episode = rows_by_episode
        self._executed = executed
        self._result: Any = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._executed.append((sql, params))
        stripped = sql.strip()
        if "to_regclass" in stripped:
            self._result = (BINDING_TABLE,)
            return
        if stripped.startswith("SELECT artifact_ref, episode_id"):
            # episode_ids IN (...) -- params are the episode_id placeholders.
            self._result = [
                row
                for episode_id in params
                for row in self._rows_by_episode.get(episode_id, [])
            ]
            return
        if stripped.startswith("INSERT INTO"):
            self._result = None
            return
        if stripped.startswith("UPDATE"):
            self._result = None
            return
        self._result = None

    def fetchone(self) -> Any:
        return self._result[0] if isinstance(self._result, list) and self._result else self._result

    def fetchall(self) -> Any:
        return self._result if isinstance(self._result, list) else []


class _FakeConn:
    def __init__(self, rows_by_episode: dict[str, list[dict[str, Any]]], executed: list[tuple[str, tuple[Any, ...]]]) -> None:
        self._rows_by_episode = rows_by_episode
        self._executed = executed

    def __enter__(self) -> "_FakeConn":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._rows_by_episode, self._executed)


def _bindings_fixture(episode_id: str) -> dict[str, list[dict[str, Any]]]:
    """Active bindings BEFORE a re-cut: a provenance ref (in derived_from), a time-overlap ref
    whose observed_at is resolvable, and a time-overlap ref whose observed_at is NOT resolvable
    (a heimdal ref, per `_resolve_artifact_observed_at`'s HEIM-6 limitation)."""
    return {
        episode_id: [
            {"artifact_ref": "heimdal.observations:prov", "episode_id": episode_id, "scope": "work",
             "basis": BASIS_PROVENANCE, "binding_state": BINDING_STATE_ACTIVE},
            {"artifact_ref": "vault.activity:overlap", "episode_id": episode_id, "scope": "work",
             "basis": "time_overlap", "binding_state": BINDING_STATE_ACTIVE},
            {"artifact_ref": "heimdal.observations:unresolvable", "episode_id": episode_id, "scope": "work",
             "basis": "time_overlap", "binding_state": BINDING_STATE_ACTIVE},
        ]
    }


def test_recut_reconciles_bindings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 1 (CRITICAL): reconcile PRESERVES valid time-overlap bindings and corrects ONLY the
    ones a re-cut genuinely invalidated -- it must never unbind a binding merely because it is not
    provenance-based."""
    from app.episodes.assignment import reconcile_episode_bindings, withdraw_episode_bindings

    episode_id = "ep-44444444-1111-4111-8111-111111111111"

    # `vault.activity:overlap` observed at 10:30; the heimdal ref is deliberately unresolvable.
    def _fake_resolver(artifact_ref, *, vault_root=None):
        return _dt(10, 30) if artifact_ref == "vault.activity:overlap" else None

    monkeypatch.setattr(assignment_module, "_resolve_artifact_observed_at", _fake_resolver)

    # --- Case A: a re-cut that does NOT change bounds must leave the valid time-overlap binding
    #     intact (and the unresolvable one preserved) -- zero corrections. ---
    executed: list[tuple[str, tuple[Any, ...]]] = []
    monkeypatch.setattr(
        assignment_module, "conn_rw", lambda *a, **k: _FakeConn(_bindings_fixture(episode_id), executed)
    )
    result_same = reconcile_episode_bindings(
        episode_id, scope="work", start=_dt(10, 0), end=_dt(11, 0),
        derived_from=["heimdal.observations:prov"], write_guard=_allow_guard(),
    )
    assert result_same["corrected"] == 0, "an unchanged-bounds re-cut must not destroy a valid time-overlap binding"
    assert not [sql for sql, _ in executed if sql.strip().startswith("UPDATE")]

    # --- Case B: a re-cut that SHRINKS bounds so `vault.activity:overlap` (10:30) falls outside
    #     [10:00, 10:15] DOES correct that binding -- but the provenance and the unresolvable
    #     time-overlap bindings survive. ---
    executed.clear()
    monkeypatch.setattr(
        assignment_module, "conn_rw", lambda *a, **k: _FakeConn(_bindings_fixture(episode_id), executed)
    )
    result_shrunk = reconcile_episode_bindings(
        episode_id, scope="work", start=_dt(10, 0), end=_dt(10, 15),
        derived_from=["heimdal.observations:prov"], write_guard=_allow_guard(),
    )
    assert result_shrunk["corrected"] == 1
    update_calls = [(sql, params) for sql, params in executed if sql.strip().startswith("UPDATE")]
    assert len(update_calls) == 1
    _sql, params = update_calls[0]
    assert "vault.activity:overlap" in params and episode_id in params
    # The unresolvable heimdal time-overlap ref was NOT corrected (preserved, HEIM-6 honest).
    assert "heimdal.observations:unresolvable" not in params

    # --- Case C: a re-cut that drops a ref from derived_from corrects that provenance binding. ---
    executed.clear()
    monkeypatch.setattr(
        assignment_module, "conn_rw", lambda *a, **k: _FakeConn(_bindings_fixture(episode_id), executed)
    )
    result_dropped = reconcile_episode_bindings(
        episode_id, scope="work", start=_dt(10, 0), end=_dt(11, 0),
        derived_from=[],  # "prov" removed
        write_guard=_allow_guard(),
    )
    assert result_dropped["corrected"] == 1
    dropped_update = [(sql, params) for sql, params in executed if sql.strip().startswith("UPDATE")][0]
    assert "heimdal.observations:prov" in dropped_update[1]

    # --- Case D (round-2 finding): a re-cut that changes the episode's SCOPE must CORRECT an
    #     otherwise-preserved (unresolvable) time-overlap binding recorded under the old scope --
    #     cross-scope deny-by-default; scope mismatch is definitive and must never be preserved. ---
    executed.clear()
    monkeypatch.setattr(
        assignment_module, "conn_rw", lambda *a, **k: _FakeConn(_bindings_fixture(episode_id), executed)
    )
    reconcile_episode_bindings(
        episode_id, scope="personal", start=_dt(10, 0), end=None,  # end=None => the preserve branch
        derived_from=[], write_guard=_allow_guard(),
    )
    rescoped_updates = [(sql, params) for sql, params in executed if sql.strip().startswith("UPDATE")]
    # The unresolvable heimdal binding (seeded scope='work') is now cross-scope vs the 'personal'
    # re-cut -> corrected, not preserved.
    assert any("heimdal.observations:unresolvable" in params for _sql, params in rescoped_updates), \
        "a preserved binding whose scope no longer matches the re-cut episode must be corrected (cross-scope deny)"

    # --- Merge-deletion side: the note is gone entirely -- every active binding withdrawn. ---
    executed.clear()
    monkeypatch.setattr(
        assignment_module, "conn_rw", lambda *a, **k: _FakeConn(_bindings_fixture(episode_id), executed)
    )
    result_withdraw = withdraw_episode_bindings(episode_id, write_guard=_allow_guard())
    assert result_withdraw["corrected"] == 3


def test_recut_tick_wires_reconciliation_on_detected_recut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Integration-shaped: the production tick actually calls reconciliation with the note's
    POST-recut scope/derived_from, not stale pre-edit values."""
    vault_root = tmp_path / "vault"
    calls = _stub_bindings(monkeypatch)
    _install_fake_engine_state(monkeypatch)

    episode_id = "ep-55555555-1111-4111-8111-111111111111"
    _write_initial(vault_root, episode_id=episode_id, derived_from=["heimdal.observations:a", "heimdal.observations:b"])
    run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=_dt(10, 5))

    _edit_note_directly(vault_root, episode_id, derived_from=["heimdal.observations:a"])
    run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=_dt(10, 10))

    reconcile_calls = [args for kind, args in calls if kind == "reconcile" and args["episode_id"] == episode_id]
    assert reconcile_calls[-1]["derived_from"] == ["heimdal.observations:a"]


# ---------------------------------------------------------------------------
# AC5 -- acceptance-by-silence
# ---------------------------------------------------------------------------


def test_silence_is_acceptance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    _stub_bindings(monkeypatch)
    _install_fake_engine_state(monkeypatch)

    episode_id = "ep-66666666-1111-4111-8111-111111111111"
    _write_initial(vault_root, episode_id=episode_id, segmentation="proposed")

    t0 = _dt(10, 0)
    result_1 = run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=t0)
    assert result_1["accepted"] == []
    fields = parse_episode_note((vault_root / episode_note_rel_path(episode_id)).read_text(encoding="utf-8"))
    assert fields["segmentation"] == "proposed"

    # Before the quiet window elapses: still proposed, no notification/approval artifact.
    almost_there = t0 + timedelta(minutes=ACCEPTANCE_QUIET_WINDOW_MINUTES - 1)
    result_2 = run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=almost_there)
    assert result_2["accepted"] == []

    # Quiet window elapsed with zero human interaction: silence is acceptance.
    after_window = t0 + timedelta(minutes=ACCEPTANCE_QUIET_WINDOW_MINUTES)
    result_3 = run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=after_window)
    assert result_3["accepted"] == [episode_id]

    fields = parse_episode_note((vault_root / episode_note_rel_path(episode_id)).read_text(encoding="utf-8"))
    assert fields["segmentation"] == "accepted"
    # Every other field is exactly what the engine originally proposed -- silence never rewrites
    # content, only the lifecycle label.
    assert fields["title"] == "Debugging session"
    assert fields["protagonists"] == ["p-1"]

    # No notification/approval surface: exactly one episode note exists in the vault -- the
    # acceptance produced no separate artifact (#2475).
    episode_notes = list((vault_root / "episodes").glob("*.md"))
    assert len(episode_notes) == 1


def test_silence_acceptance_content_hash_helper_is_stable(tmp_path: Path) -> None:
    """Sanity check on the writer-identity primitive both AC1 and AC5 depend on: identical CUT
    fields hash identically; a changed CUT field hashes differently."""
    fields = {"segmentation": "proposed", "title": "x", "time": {"start": "t", "closed": False}}
    assert compute_fields_hash(fields) == compute_fields_hash(dict(fields))
    changed = dict(fields, title="y")
    assert compute_fields_hash(fields) != compute_fields_hash(changed)


def test_content_hash_excludes_engine_lifecycle_fields(tmp_path: Path) -> None:
    """Finding 2: the writer-identity hash must cover ONLY the human-owned cut. An engine-only
    lifecycle write -- a `segmentation` relabel or an ERE-06 `time.closed` flip -- must NOT change
    the fingerprint, otherwise a non-atomic write+set_state could manufacture a false re-cut."""
    base = {
        "segmentation": "proposed", "title": "x", "scope": "work",
        "time": {"start": "2026-07-11T10:00:00+00:00", "end": "2026-07-11T11:00:00+00:00", "closed": False},
        "protagonists": ["p-1"], "goal": ["g-1"], "derived_from": ["heimdal.observations:seed"],
    }
    relabeled = dict(base, segmentation="accepted")
    closed_flip = dict(base, time={**base["time"], "closed": True})
    assert compute_fields_hash(base) == compute_fields_hash(relabeled)
    assert compute_fields_hash(base) == compute_fields_hash(closed_flip)
    # A real cut edit (protagonist removed) still changes the fingerprint.
    cut_edit = dict(base, protagonists=[])
    assert compute_fields_hash(base) != compute_fields_hash(cut_edit)


def test_non_atomic_lifecycle_write_does_not_manufacture_false_recut(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 2 (CONFIRMED): the accept-by-silence write and its baseline `set_state` are
    non-atomic. Simulate the note reaching disk as `accepted` while the tracked baseline still
    records the PRE-accept `proposed` state (set_state having failed). The next tick must NOT
    report a re-cut and must NOT relabel accepted->re-cut -- and must self-heal the stale baseline."""
    vault_root = tmp_path / "vault"
    _stub_bindings(monkeypatch)
    fake_state = _install_fake_engine_state(monkeypatch)

    episode_id = "ep-fa11ed00-1111-4111-8111-111111111111"
    # Baseline recorded while the note was still `proposed` (this is what set_state persisted
    # BEFORE the accept write).
    _write_initial(vault_root, episode_id=episode_id, segmentation="proposed")
    run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=_dt(10, 0))
    baseline_key = f"episode_recut_state:{episode_id}"
    assert fake_state.all_state_with_prefix("episode_recut_state:")[baseline_key]["segmentation"] == "proposed"

    # The engine's accept write reaches disk, but its set_state baseline update is LOST: mutate the
    # note to `accepted` directly (bypassing recut's own bookkeeping) to model that exact torn state.
    _edit_note_directly(vault_root, episode_id, segmentation="accepted")

    # Next tick: the CUT is unchanged (accept touched only `segmentation`, excluded from the hash),
    # so this must NOT be detected as a re-cut, and the note must stay `accepted`.
    result = run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=_dt(10, 5))
    assert result["recut_detected"] == []
    assert result["accepted"] == []

    fields = parse_episode_note((vault_root / episode_note_rel_path(episode_id)).read_text(encoding="utf-8"))
    assert fields["segmentation"] == "accepted", "the engine must never relabel an accepted note back to re-cut"

    # Self-heal: the stale baseline label was refreshed to the on-disk truth.
    assert fake_state.all_state_with_prefix("episode_recut_state:")[baseline_key]["segmentation"] == "accepted"


# ---------------------------------------------------------------------------
# AC6 -- split and merge flows land in consistent state
# ---------------------------------------------------------------------------


def test_split_and_merge_flows_consistent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault_root = tmp_path / "vault"
    calls = _stub_bindings(monkeypatch)
    fake_state = _install_fake_engine_state(monkeypatch)

    episode_a = "ep-77777777-1111-4111-8111-111111111111"
    _write_initial(
        vault_root,
        episode_id=episode_a,
        segmentation="accepted",
        derived_from=["heimdal.observations:ref1", "heimdal.observations:ref2"],
        end="2026-07-11T12:00:00+00:00",
    )
    run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=_dt(9, 0))
    calls.clear()

    # --- SPLIT: narrow A to ref1 only; hand-author a NEW sibling note B covering ref2. ---
    _edit_note_directly(
        vault_root, episode_a,
        derived_from=["heimdal.observations:ref1"],
        **{"time.end": "2026-07-11T11:00:00+00:00"},
    )
    episode_b = "ep-88888888-1111-4111-8111-111111111111"
    write_episode_note(
        title="Debugging session (split half)",
        scope="work",
        start="2026-07-11T11:00:00+00:00",
        end="2026-07-11T12:00:00+00:00",
        derived_from=["heimdal.observations:ref2"],
        segmentation="re-cut",
        episode_id=episode_b,
        vault_root=vault_root,
        write_guard=_allow_guard(),
    )

    split_result = run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=_dt(9, 30))
    assert episode_a in split_result["recut_detected"]
    assert episode_b not in split_result["recut_detected"]  # first sight, adopted not "detected"

    by_episode = {}
    for kind, args in calls:
        if kind == "reconcile":
            by_episode[args["episode_id"]] = args["derived_from"]
    assert by_episode[episode_a] == ["heimdal.observations:ref1"]
    assert by_episode[episode_b] == ["heimdal.observations:ref2"]

    # No dangling parent_episode: B does not claim a parent that doesn't resolve.
    b_fields = parse_episode_note((vault_root / episode_note_rel_path(episode_b)).read_text(encoding="utf-8"))
    assert b_fields.get("parent_episode") in (None, episode_a)

    calls.clear()

    # --- MERGE: delete B; widen A back to cover both refs. ---
    (vault_root / episode_note_rel_path(episode_b)).unlink()
    _edit_note_directly(
        vault_root, episode_a,
        derived_from=["heimdal.observations:ref1", "heimdal.observations:ref2"],
        **{"time.end": "2026-07-11T12:00:00+00:00"},
    )

    merge_result = run_recut_tick(vault_root=vault_root, write_guard=_allow_guard(), now=_dt(10, 0))
    assert episode_a in merge_result["recut_detected"]

    withdraw_calls = [args for kind, args in calls if kind == "withdraw"]
    assert {c["episode_id"] for c in withdraw_calls} == {episode_b}

    reconcile_calls = {args["episode_id"]: args["derived_from"] for kind, args in calls if kind == "reconcile"}
    assert reconcile_calls[episode_a] == ["heimdal.observations:ref1", "heimdal.observations:ref2"]

    # B is no longer tracked at all -- no dangling baseline left behind for a deleted note.
    tracked_after = fake_state.all_state_with_prefix("episode_recut_state:")
    assert f"episode_recut_state:{episode_b}" not in tracked_after
    assert f"episode_recut_state:{episode_a}" in tracked_after
