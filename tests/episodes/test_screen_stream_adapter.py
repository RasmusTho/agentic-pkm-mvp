"""ERE screen stream adapter contract and production-path coverage (#3346)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.cli import episodes as episodes_cli_module
from app.episodes import recut, segmenter
from app.episodes.screen_stream import (
    OBSERVATION_TOPIC,
    SCREEN_CONSUMER_ID,
    SCREEN_STREAM_ID,
    ScreenSignalContractError,
    screen_observation_to_signal_contract,
)
from app.episodes.stream_registry import DIMENSIONS, StreamRegistry, StreamRegistryEntry
from app.heimdal.observation_log import ObservationRow
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg


def _row(
    observation_id: str,
    *,
    start: str = "2026-07-11T08:00:00Z",
    end: str = "2026-07-11T08:00:30Z",
    app: str = "Obsidian",
    window: str = "Project notes",
    scope: str = "work",
    goal: str = "review project notes",
    grant_ref: str | None = "consent:screen:grant-1",
    modality: str = "screen",
    sequence: int = 1,
) -> ObservationRow:
    consent: dict[str, str] = {"grant_ref": grant_ref} if grant_ref is not None else {}
    payload: dict[str, Any] = {
        "observation_id": observation_id,
        "modality": modality,
        "observed_at_start": start,
        "observed_at_end": end,
        "scope_hint": scope,
        "attributions": [{"mention_id": "operator", "resolution": "resolved"}],
        "content_structure": {
            "span": {
                "dimensions": {"app": app, "window": window, "scope": scope, "goal": goal},
                "raw_refs": [f"raw:{observation_id}"],
            }
        },
        "confidence": {
            "attribution": {"score": 1.0, "calibration": "by_construction", "method": "single_operator_capture"},
            "activity_summary": {"score": 0.8, "calibration": "heuristic", "method": "local_vision"},
            "entity_mention": {"score": 0.7, "calibration": "heuristic", "method": "local_vision"},
        },
        "provenance": {"content_identity": f"content:{observation_id}", "capture_chain": [f"capture:{observation_id}"]},
        "consent": consent,
    }
    return ObservationRow(
        id=f"log:{observation_id}",
        topic=OBSERVATION_TOPIC,
        idempotency_key=f"key:{observation_id}",
        envelope={"event": OBSERVATION_TOPIC, "payload": payload},
        created_at=datetime(2026, 7, 11, 8, 1, tzinfo=timezone.utc),
        sequence=sequence,
    )


def _screen_only_registry() -> StreamRegistry:
    return StreamRegistry(
        entries={
            SCREEN_STREAM_ID: StreamRegistryEntry(
                stream_id=SCREEN_STREAM_ID,
                status="live",
                owner_constituent="Heimdal",
                dimensions_fed=tuple(sorted(DIMENSIONS)),
                transport="module:app.heimdal.observation_log",
                consent_class="heimdal_gated",
                cadence="continuous",
            )
        }
    )


def _speech_and_screen_registry(*, screen_first: bool = False) -> StreamRegistry:
    speech = StreamRegistryEntry(
        stream_id="heimdal.observations",
        status="live",
        owner_constituent="Heimdal",
        dimensions_fed=("time", "protagonist"),
        transport="module:app.heimdal.observation_log",
        consent_class="heimdal_gated",
        cadence="continuous",
    )
    screen = StreamRegistryEntry(
        stream_id=SCREEN_STREAM_ID,
        status="live",
        owner_constituent="Heimdal",
        dimensions_fed=tuple(sorted(DIMENSIONS)),
        transport="module:app.heimdal.observation_log",
        consent_class="heimdal_gated",
        cadence="continuous",
    )
    entries = {SCREEN_STREAM_ID: screen, "heimdal.observations": speech} if screen_first else {
        "heimdal.observations": speech,
        SCREEN_STREAM_ID: screen,
    }
    return StreamRegistry(entries=entries)


def _install_fake_assignment_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[tuple[str, str], dict[str, str]], list[tuple[tuple[str, str], ...]]]:
    active: dict[tuple[str, str], dict[str, str]] = {}
    writes: list[tuple[tuple[str, str], ...]] = []

    def read_refs(refs: set[str]) -> dict[tuple[str, str], dict[str, str]]:
        return {key: value for key, value in active.items() if key[0] in refs}

    def read_episodes(episode_ids: set[str]) -> dict[tuple[str, str], dict[str, str]]:
        return {key: value for key, value in active.items() if key[1] in episode_ids}

    def commit(to_insert, to_correct, write_guard=None, vault_root=None):
        inserted: list[tuple[str, str]] = []
        for decision in to_insert:
            key = (decision.artifact_ref, decision.episode_id)
            active[key] = {
                "binding_state": "active",
                "basis": decision.basis,
                "scope": decision.scope,
            }
            inserted.append(key)
        for key in to_correct:
            if key in active:
                active[key]["binding_state"] = "corrected"
        if inserted or to_correct:
            writes.append(tuple(inserted) + tuple(to_correct))
        return {"pending": len(inserted), "corrected": len(to_correct)}

    monkeypatch.setattr(segmenter, "read_existing_bindings", read_refs)
    monkeypatch.setattr(segmenter, "read_existing_bindings_for_episodes", read_episodes)
    monkeypatch.setattr(segmenter, "commit_assignment_diff", commit)
    return active, writes


def _mixed_replay_rows() -> list[ObservationRow]:
    return [
        _row(
            "speech-s",
            modality="speech",
            start="2026-07-11T08:00:00Z",
            end="2026-07-11T08:00:30Z",
            sequence=1,
        ),
        _row(
            "screen-a",
            start="2026-07-11T08:01:00Z",
            end="2026-07-11T08:01:30Z",
            goal="goal one",
            sequence=2,
        ),
        _row(
            "screen-b",
            start="2026-07-11T08:02:00Z",
            end="2026-07-11T08:02:30Z",
            goal="goal two",
            sequence=3,
        ),
    ]


def _stub_tick_io(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, object]]:
    state: dict[str, dict[str, object]] = {}
    monkeypatch.setattr(segmenter.engine_state, "all_state_with_prefix", lambda prefix: {
        key: value for key, value in state.items() if key.startswith(prefix)
    })
    monkeypatch.setattr(segmenter.engine_state, "set_state", lambda key, value: state.__setitem__(key, value))
    monkeypatch.setattr(segmenter.engine_state, "delete_state", lambda key: state.pop(key, None))
    monkeypatch.setattr(segmenter, "read_candidate_episodes_for_scopes", lambda scopes: [])
    monkeypatch.setattr(segmenter, "read_existing_bindings", lambda refs: {})
    monkeypatch.setattr(segmenter, "read_existing_bindings_for_episodes", lambda episode_ids: {})
    monkeypatch.setattr(
        segmenter,
        "commit_assignment_diff",
        lambda to_insert, to_correct, write_guard=None, vault_root=None: {
            "pending": len(to_insert),
            "corrected": len(to_correct),
        },
    )
    import app.episodes.closure as closure_module

    monkeypatch.setattr(closure_module, "run_closure_tick", lambda **kwargs: {"closed": [], "events_emitted": 0})
    return state


def _healthy_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy", "reason": None})


def test_screen_span_maps_to_signal_contract() -> None:
    row = _row("screen-1")

    contract = screen_observation_to_signal_contract(row)

    assert contract is not None
    assert contract.stream_id == SCREEN_STREAM_ID
    assert contract.signal_id == "screen-1"
    assert contract.observed_at_start == "2026-07-11T08:00:00Z"
    assert contract.observed_at_end == "2026-07-11T08:00:30Z"
    assert contract.emitted_at == row.created_at.isoformat()
    assert contract.provenance_ref == "screen:screen-1"
    assert contract.scope_binding is not None and contract.scope_binding.scope == "work"
    assert set(contract.dimensions_fed) == {"time", "protagonist", "goal", "space"}
    assert contract.dimensions_fed["time"].calibration == "by_construction"
    assert contract.dimensions_fed["protagonist"].score == 1.0
    assert contract.dimensions_fed["goal"].score == 0.8
    assert contract.dimensions_fed["space"].score == 0.7


def test_span_boundaries_become_distinct_signals() -> None:
    rows = (
        _row("screen-a", start="2026-07-11T08:00:00Z", end="2026-07-11T08:00:30Z"),
        _row(
            "screen-b",
            start="2026-07-11T08:00:30Z",
            end="2026-07-11T08:01:00Z",
            app="Browser",
            window="Issue 3346",
            goal="read issue acceptance criteria",
            sequence=2,
        ),
        _row(
            "screen-c",
            start="2026-07-11T08:01:00Z",
            end="2026-07-11T08:01:30Z",
            app="Terminal",
            window="tests",
            goal="inspect adapter tests",
            sequence=3,
        ),
        _row(
            "screen-d",
            start="2026-07-11T08:01:30Z",
            end="2026-07-11T08:02:00Z",
            app="Terminal",
            window="tests",
            scope="private",
            goal="inspect adapter tests",
            sequence=4,
        ),
    )
    adapter = segmenter.resolve_stream_adapter(_screen_only_registry().get(SCREEN_STREAM_ID))
    assert adapter is not None

    signals = [adapter.normalize(row, SimpleNamespace()) for row in rows]

    assert all(signal is not None for signal in signals)
    normalized = [signal for signal in signals if signal is not None]
    assert [signal.signal_id for signal in normalized] == ["screen-a", "screen-b", "screen-c", "screen-d"]
    assert [(signal.observed_at.isoformat(), signal.observed_at_end.isoformat()) for signal in normalized] == [
        ("2026-07-11T08:00:00+00:00", "2026-07-11T08:00:30+00:00"),
        ("2026-07-11T08:00:30+00:00", "2026-07-11T08:01:00+00:00"),
        ("2026-07-11T08:01:00+00:00", "2026-07-11T08:01:30+00:00"),
        ("2026-07-11T08:01:30+00:00", "2026-07-11T08:02:00+00:00"),
    ]
    assert [signal.screen_dimensions for signal in normalized] == [
        {"app": "Obsidian", "window": "Project notes", "scope": "work", "goal": "review project notes"},
        {"app": "Browser", "window": "Issue 3346", "scope": "work", "goal": "read issue acceptance criteria"},
        {"app": "Terminal", "window": "tests", "scope": "work", "goal": "inspect adapter tests"},
        {"app": "Terminal", "window": "tests", "scope": "private", "goal": "inspect adapter tests"},
    ]


def test_production_tick_filters_modalities_and_requires_existing_consent_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The registry-resolved tick rejects cross-modality and unreferenced screen rows."""
    rows = [
        _row("speech-1", modality="speech", sequence=1),
        _row("screen-no-consent", grant_ref=None, sequence=2),
        _row("screen-accepted", sequence=3),
    ]
    reads: list[str] = []
    advances: list[tuple[str, list[str]]] = []

    def read_for_consumer(consumer_id: str, *, limit: int | None = None) -> Sequence[ObservationRow]:
        reads.append(consumer_id)
        return rows

    def advance_for_consumer(consumer_id: str, consumed_rows: list[ObservationRow]) -> None:
        advances.append((consumer_id, [row.id for row in consumed_rows]))

    monkeypatch.setattr(segmenter, "read_observations_for_consumer", read_for_consumer)
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", advance_for_consumer)
    state = _stub_tick_io(monkeypatch)

    folded: list[list[segmenter.SegmentationSignal]] = []
    real_fold = segmenter.fold_signals_into_segments

    def capture_fold(signals, **kwargs):
        folded.append(list(signals))
        return real_fold(signals, **kwargs)

    monkeypatch.setattr(segmenter, "fold_signals_into_segments", capture_fold)

    registry = StreamRegistry(
        entries={
            "heimdal.observations": StreamRegistryEntry(
                stream_id="heimdal.observations",
                status="live",
                owner_constituent="Heimdal",
                dimensions_fed=("time", "protagonist"),
                transport="module:app.heimdal.observation_log",
                consent_class="heimdal_gated",
                cadence="continuous",
            ),
            SCREEN_STREAM_ID: StreamRegistryEntry(
                stream_id=SCREEN_STREAM_ID,
                status="live",
                owner_constituent="Heimdal",
                dimensions_fed=tuple(sorted(DIMENSIONS)),
                transport="module:app.heimdal.observation_log",
                consent_class="heimdal_gated",
                cadence="continuous",
            ),
        }
    )
    result = segmenter.run_segmentation_tick(
        vault_root=tmp_path,
        registry=registry,
        write_guard=_healthy_guard(),
    )

    assert set(reads) == {segmenter.CONSUMER_ID, SCREEN_CONSUMER_ID}
    assert result["consumed"]["heimdal.observations"] == 1
    assert result["consumed"][SCREEN_STREAM_ID] == 1
    assert result["degraded"] == ["screen:screen-no-consent:refused:missing_consent_grant_ref"]
    assert len(folded) == 1
    assert {(signal.stream_id, signal.signal_id) for signal in folded[0]} == {
        ("heimdal.observations", "speech-1"),
        (SCREEN_STREAM_ID, "screen-accepted"),
    }
    assert any(
        consumer_id == SCREEN_CONSUMER_ID and row_ids == [row.id for row in rows]
        for consumer_id, row_ids in advances
    )
    assert any(
        consumer_id == segmenter.CONSUMER_ID and row_ids == [row.id for row in rows]
        for consumer_id, row_ids in advances
    )
    assert state["open_segment:work"]["signal_ids"] == ["screen-accepted", "speech-1"]


def test_screen_adapter_rejects_wrong_modality_and_malformed_span() -> None:
    assert screen_observation_to_signal_contract(_row("speech-only", modality="speech")) is None

    with pytest.raises(ScreenSignalContractError, match="span_end_before_start"):
        screen_observation_to_signal_contract(
            _row("reverse-span", start="2026-07-11T08:01:00Z", end="2026-07-11T08:00:00Z")
        )


def test_screen_cursor_replay_is_idempotent_after_tick_state_persisted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failure at cursor advance replays through the already-persisted open-segment ledger."""
    row = _row("screen-replay", sequence=1)
    cursor_positions: dict[str, int] = {}
    fail_screen_advance = True

    def read_for_consumer(consumer_id: str, *, limit: int | None = None) -> Sequence[ObservationRow]:
        position = cursor_positions.get(consumer_id, 0)
        unread = [candidate for candidate in (row,) if candidate.sequence >= position]
        return unread[:limit] if limit is not None else unread

    def advance_for_consumer(consumer_id: str, consumed_rows: list[ObservationRow]) -> None:
        nonlocal fail_screen_advance
        if consumer_id == SCREEN_CONSUMER_ID and fail_screen_advance:
            fail_screen_advance = False
            raise RuntimeError("simulated failure before screen cursor commit")
        if consumed_rows:
            cursor_positions[consumer_id] = max(candidate.sequence for candidate in consumed_rows) + 1

    monkeypatch.setattr(segmenter, "read_observations_for_consumer", read_for_consumer)
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", advance_for_consumer)
    state = _stub_tick_io(monkeypatch)

    with pytest.raises(RuntimeError, match="before screen cursor commit"):
        segmenter.run_segmentation_tick(
            vault_root=tmp_path,
            registry=_screen_only_registry(),
            write_guard=_healthy_guard(),
        )

    persisted = state["open_segment:work"]
    assert cursor_positions.get(SCREEN_CONSUMER_ID, 0) == 0
    assert persisted["signal_ids"] == ["screen-replay"]
    assert persisted["derived_from"] == ["screen:screen-replay"]

    replay = segmenter.run_segmentation_tick(
        vault_root=tmp_path,
        registry=_screen_only_registry(),
        write_guard=_healthy_guard(),
    )

    assert replay["consumed"][SCREEN_STREAM_ID] == 1
    assert replay["open_segments"] == 1
    assert cursor_positions[SCREEN_CONSUMER_ID] == 2
    assert state["open_segment:work"]["signal_ids"] == ["screen-replay"]
    assert state["open_segment:work"]["derived_from"] == ["screen:screen-replay"]


@pytest.mark.parametrize(
    ("failed_consumer", "screen_first"),
    [
        (SCREEN_CONSUMER_ID, False),
        (segmenter.CONSUMER_ID, True),
    ],
    ids=["generic-ack-before-screen-failure", "screen-ack-before-generic-failure"],
)
def test_production_tick_replay_admission_survives_partial_sibling_ack(
    failed_consumer: str,
    screen_first: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sibling cursor may commit first without replaying a segment as a new episode."""
    rows = _mixed_replay_rows()
    cursor_positions: dict[str, int] = {}
    fail_once = True

    def read_for_consumer(consumer_id: str, *, limit: int | None = None) -> Sequence[ObservationRow]:
        position = cursor_positions.get(consumer_id, 0)
        unread = [row for row in rows if row.sequence >= position]
        return unread[:limit] if limit is not None else unread

    def advance_for_consumer(consumer_id: str, consumed_rows: list[ObservationRow]) -> None:
        nonlocal fail_once
        if consumer_id == failed_consumer and fail_once:
            fail_once = False
            raise RuntimeError("simulated partial sibling cursor commit")
        if consumed_rows:
            cursor_positions[consumer_id] = max(row.sequence for row in consumed_rows) + 1

    monkeypatch.setattr(segmenter, "read_observations_for_consumer", read_for_consumer)
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", advance_for_consumer)
    monkeypatch.setattr(segmenter, "_sync_new_episode_row", lambda *args, **kwargs: None)
    projection_retries: list[str] = []
    monkeypatch.setattr(
        segmenter,
        "_retry_existing_episode_projection_sync",
        lambda *, vault_root, rel_path: projection_retries.append(rel_path),
    )
    state = _stub_tick_io(monkeypatch)
    active_bindings, binding_writes = _install_fake_assignment_ledger(monkeypatch)
    registry = _speech_and_screen_registry(screen_first=screen_first)

    with pytest.raises(RuntimeError, match="partial sibling cursor"):
        segmenter.run_segmentation_tick(
            vault_root=tmp_path,
            registry=registry,
            write_guard=_healthy_guard(),
        )

    notes_dir = tmp_path / "episodes"
    original_notes = sorted(notes_dir.glob("ep-*.md"))
    assert len(original_notes) == 1
    original_note_path = original_notes[0]
    original_note_bytes = original_note_path.read_bytes()
    original_fields = segmenter.parse_validated_episode_note(original_note_bytes.decode("utf-8"))
    assert original_fields["derived_from"] == [
        "heimdal.observations:speech-s",
        "screen:screen-a",
    ]
    open_before_retry = dict(state["open_segment:work"])
    bindings_before_retry = {key: dict(value) for key, value in active_bindings.items()}
    binding_writes_before_retry = list(binding_writes)

    replay = segmenter.run_segmentation_tick(
        vault_root=tmp_path,
        registry=registry,
        write_guard=_healthy_guard(),
    )

    assert replay["proposed"] == []
    assert sorted(notes_dir.glob("ep-*.md")) == [original_note_path]
    assert original_note_path.read_bytes() == original_note_bytes
    assert state["open_segment:work"] == open_before_retry
    assert active_bindings == bindings_before_retry
    assert binding_writes == binding_writes_before_retry
    assert projection_retries == [f"episodes/{original_note_path.name}"]
    assert cursor_positions == {segmenter.CONSUMER_ID: 4, SCREEN_CONSUMER_ID: 4}

    # Exact identity, not timestamp overlap, controls replay admission. A new
    # screen observation inside the old proposal's bounds still extends B.
    rows.append(
        _row(
            "screen-c",
            start="2026-07-11T08:00:45Z",
            end="2026-07-11T08:01:00Z",
            goal="goal two",
            sequence=4,
        )
    )
    new_inside_old_bounds = segmenter.run_segmentation_tick(
        vault_root=tmp_path,
        registry=registry,
        write_guard=_healthy_guard(),
    )
    assert new_inside_old_bounds["proposed"] == []
    assert state["open_segment:work"]["start"] == "2026-07-11T08:00:45+00:00"
    assert state["open_segment:work"]["derived_from"] == ["screen:screen-b", "screen:screen-c"]

    # A genuinely new goal boundary still closes B+C once and leaves D open.
    rows.append(
        _row(
            "screen-d",
            start="2026-07-11T08:03:00Z",
            end="2026-07-11T08:03:30Z",
            goal="goal three",
            sequence=5,
        )
    )
    boundary = segmenter.run_segmentation_tick(
        vault_root=tmp_path,
        registry=registry,
        write_guard=_healthy_guard(),
    )
    assert len(boundary["proposed"]) == 1
    closed_path = notes_dir / f"{boundary['proposed'][0]}.md"
    closed_fields = segmenter.parse_validated_episode_note(closed_path.read_text(encoding="utf-8"))
    assert closed_fields["derived_from"] == ["screen:screen-b", "screen:screen-c"]
    assert closed_fields["time"]["start"] == "2026-07-11T08:00:45+00:00"
    assert state["open_segment:work"]["derived_from"] == ["screen:screen-d"]


def test_production_tick_replay_recovers_after_note_before_assignment_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A canonical note survives a crash before state and cursor commits, and assignment recovers."""
    rows = _mixed_replay_rows()
    cursor_positions: dict[str, int] = {}
    fail_assignment = True

    def read_for_consumer(consumer_id: str, *, limit: int | None = None) -> Sequence[ObservationRow]:
        position = cursor_positions.get(consumer_id, 0)
        unread = [row for row in rows if row.sequence >= position]
        return unread[:limit] if limit is not None else unread

    def advance_for_consumer(consumer_id: str, consumed_rows: list[ObservationRow]) -> None:
        if consumed_rows:
            cursor_positions[consumer_id] = max(row.sequence for row in consumed_rows) + 1

    monkeypatch.setattr(segmenter, "read_observations_for_consumer", read_for_consumer)
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", advance_for_consumer)
    monkeypatch.setattr(segmenter, "_sync_new_episode_row", lambda *args, **kwargs: None)
    projection_retries: list[str] = []
    monkeypatch.setattr(
        segmenter,
        "_retry_existing_episode_projection_sync",
        lambda *, vault_root, rel_path: projection_retries.append(rel_path),
    )
    state = _stub_tick_io(monkeypatch)
    active_bindings: dict[tuple[str, str], dict[str, str]] = {}

    def fail_then_persist(to_insert, to_correct, write_guard=None, vault_root=None):
        nonlocal fail_assignment
        if fail_assignment:
            fail_assignment = False
            raise RuntimeError("simulated failure after proposal before assignment")
        for decision in to_insert:
            active_bindings[(decision.artifact_ref, decision.episode_id)] = {
                "binding_state": "active",
                "basis": decision.basis,
                "scope": decision.scope,
            }
        return {"pending": len(to_insert), "corrected": len(to_correct)}

    monkeypatch.setattr(segmenter, "commit_assignment_diff", fail_then_persist)
    with pytest.raises(RuntimeError, match="after proposal before assignment"):
        segmenter.run_segmentation_tick(
            vault_root=tmp_path,
            registry=_speech_and_screen_registry(),
            write_guard=_healthy_guard(),
        )

    notes_dir = tmp_path / "episodes"
    first_note = sorted(notes_dir.glob("ep-*.md"))[0]
    first_note_bytes = first_note.read_bytes()
    assert not state
    assert cursor_positions == {}

    replay = segmenter.run_segmentation_tick(
        vault_root=tmp_path,
        registry=_speech_and_screen_registry(),
        write_guard=_healthy_guard(),
    )

    assert replay["proposed"] == []
    assert len(list(notes_dir.glob("ep-*.md"))) == 1
    assert first_note.read_bytes() == first_note_bytes
    assert state["open_segment:work"]["derived_from"] == ["screen:screen-b"]
    assert {key[0] for key in active_bindings} == {
        "heimdal.observations:speech-s",
        "screen:screen-a",
    }
    assert projection_retries == [f"episodes/{first_note.name}"]
    assert cursor_positions == {segmenter.CONSUMER_ID: 4, SCREEN_CONSUMER_ID: 4}


def test_production_tick_replay_admission_is_scope_specific(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.episodes.ids import mint_episode_id

    monkeypatch.setattr(segmenter, "_sync_new_episode_row", lambda *args, **kwargs: None)
    segmenter.write_episode_note(
        title="Existing work episode",
        scope="work",
        start="2026-07-11T08:00:00Z",
        end="2026-07-11T08:01:00Z",
        closed=False,
        derived_from=["screen:screen-same-id"],
        episode_id=mint_episode_id(),
        vault_root=tmp_path,
        write_guard=_healthy_guard(),
    )
    row = _row("screen-same-id", scope="private", sequence=1)
    positions: dict[str, int] = {}
    monkeypatch.setattr(segmenter, "read_observations_for_consumer", lambda consumer, **kwargs: [row])
    monkeypatch.setattr(
        segmenter,
        "advance_cursor_for_consumer",
        lambda consumer, consumed: positions.__setitem__(consumer, max(r.sequence for r in consumed) + 1)
        if consumed
        else None,
    )
    state = _stub_tick_io(monkeypatch)

    result = segmenter.run_segmentation_tick(
        vault_root=tmp_path,
        registry=_screen_only_registry(),
        write_guard=_healthy_guard(),
    )

    assert result["open_segments"] == 1
    assert state["open_segment:private"]["derived_from"] == ["screen:screen-same-id"]
    assert positions[SCREEN_CONSUMER_ID] == 2


def test_production_tick_does_not_ack_when_canonical_episode_evidence_is_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notes_dir = tmp_path / "episodes"
    notes_dir.mkdir()
    (notes_dir / "ep-invalid.md").write_text("---\nartifact_class: episode_note\nunknown: true\n---\n")
    row = _row("screen-needs-admission", sequence=1)
    advances: list[str] = []
    monkeypatch.setattr(segmenter, "read_observations_for_consumer", lambda consumer, **kwargs: [row])
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", lambda consumer, consumed: advances.append(consumer))
    state = _stub_tick_io(monkeypatch)

    with pytest.raises(segmenter.EpisodeReplayAdmissionError, match="cannot be validated"):
        segmenter.run_segmentation_tick(
            vault_root=tmp_path,
            registry=_screen_only_registry(),
            write_guard=_healthy_guard(),
        )

    assert advances == []
    assert state == {}


def test_production_tick_fails_closed_when_canonical_note_enumeration_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A partial sibling ACK cannot treat a failed canonical scan as an empty index."""
    rows = _mixed_replay_rows()
    cursor_positions: dict[str, int] = {}
    fail_screen_ack_once = True

    def read_for_consumer(consumer_id: str, *, limit: int | None = None) -> Sequence[ObservationRow]:
        position = cursor_positions.get(consumer_id, 0)
        unread = [row for row in rows if row.sequence >= position]
        return unread[:limit] if limit is not None else unread

    def advance_for_consumer(consumer_id: str, consumed_rows: list[ObservationRow]) -> None:
        nonlocal fail_screen_ack_once
        if consumer_id == SCREEN_CONSUMER_ID and fail_screen_ack_once:
            fail_screen_ack_once = False
            raise RuntimeError("simulated partial sibling cursor commit")
        if consumed_rows:
            cursor_positions[consumer_id] = max(row.sequence for row in consumed_rows) + 1

    monkeypatch.setattr(segmenter, "read_observations_for_consumer", read_for_consumer)
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", advance_for_consumer)
    monkeypatch.setattr(segmenter, "_sync_new_episode_row", lambda *args, **kwargs: None)
    state = _stub_tick_io(monkeypatch)
    active_bindings, binding_writes = _install_fake_assignment_ledger(monkeypatch)
    registry = _speech_and_screen_registry()

    with pytest.raises(RuntimeError, match="partial sibling cursor"):
        segmenter.run_segmentation_tick(
            vault_root=tmp_path,
            registry=registry,
            write_guard=_healthy_guard(),
        )

    notes_dir = tmp_path / "episodes"
    assert len(list(notes_dir.glob("ep-*.md"))) == 1
    assert state["open_segment:work"]["derived_from"] == ["screen:screen-b"]
    cursor_before_retry = dict(cursor_positions)
    state_before_retry = {key: dict(value) for key, value in state.items()}
    bindings_before_retry = {key: dict(value) for key, value in active_bindings.items()}
    writes_before_retry = list(binding_writes)

    fold_calls: list[bool] = []
    proposal_calls: list[bool] = []
    assignment_calls: list[bool] = []
    state_writes: list[str] = []
    state_deletes: list[str] = []
    original_set_state = segmenter.engine_state.set_state
    original_delete_state = segmenter.engine_state.delete_state
    monkeypatch.setattr(
        segmenter,
        "fold_signals_into_segments",
        lambda *args, **kwargs: fold_calls.append(True),
    )
    monkeypatch.setattr(
        segmenter,
        "_emit_proposals_with_fusion_gate",
        lambda *args, **kwargs: proposal_calls.append(True),
    )
    monkeypatch.setattr(
        segmenter,
        "commit_assignment_diff",
        lambda *args, **kwargs: assignment_calls.append(True),
    )

    def tracked_set_state(key: str, value: dict[str, object]) -> None:
        state_writes.append(key)
        original_set_state(key, value)

    def tracked_delete_state(key: str) -> None:
        state_deletes.append(key)
        original_delete_state(key)

    monkeypatch.setattr(segmenter.engine_state, "set_state", tracked_set_state)
    monkeypatch.setattr(segmenter.engine_state, "delete_state", tracked_delete_state)
    original_scandir = segmenter.os.scandir

    def fail_canonical_scan(path: str | bytes | Path):
        if Path(path) == notes_dir:
            raise PermissionError("simulated canonical note directory denial")
        return original_scandir(path)

    monkeypatch.setattr(segmenter.os, "scandir", fail_canonical_scan)
    with pytest.raises(segmenter.EpisodeReplayAdmissionError, match="could not enumerate"):
        segmenter.run_segmentation_tick(
            vault_root=tmp_path,
            registry=registry,
            write_guard=_healthy_guard(),
        )

    assert fold_calls == []
    assert proposal_calls == []
    assert assignment_calls == []
    assert state_writes == []
    assert state_deletes == []
    assert cursor_positions == cursor_before_retry
    assert state == state_before_retry
    assert active_bindings == bindings_before_retry
    assert binding_writes == writes_before_retry


def test_production_tick_retries_projection_after_stale_open_note_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale-open retirement requests projection recovery for a durable canonical note."""
    rows = [_row("screen-a", goal="goal one", sequence=1)]
    cursor_positions: dict[str, int] = {}

    def read_for_consumer(consumer_id: str, *, limit: int | None = None) -> Sequence[ObservationRow]:
        position = cursor_positions.get(consumer_id, 0)
        unread = [row for row in rows if row.sequence >= position]
        return unread[:limit] if limit is not None else unread

    def advance_for_consumer(consumer_id: str, consumed_rows: list[ObservationRow]) -> None:
        if consumed_rows:
            cursor_positions[consumer_id] = max(row.sequence for row in consumed_rows) + 1

    monkeypatch.setattr(segmenter, "read_observations_for_consumer", read_for_consumer)
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", advance_for_consumer)
    monkeypatch.setattr(segmenter, "_sync_new_episode_row", lambda *args, **kwargs: None)
    state = _stub_tick_io(monkeypatch)
    registry = _screen_only_registry()

    first = segmenter.run_segmentation_tick(
        vault_root=tmp_path,
        registry=registry,
        write_guard=_healthy_guard(),
    )
    assert first["proposed"] == []
    assert state["open_segment:work"]["derived_from"] == ["screen:screen-a"]
    assert cursor_positions[SCREEN_CONSUMER_ID] == 2

    # B closes A. The canonical note lands, but a later assignment failure
    # prevents replacement of the stale open state and cursor advancement.
    rows.append(
        _row(
            "screen-b",
            start="2026-07-11T08:02:00Z",
            end="2026-07-11T08:02:30Z",
            goal="goal two",
            sequence=2,
        )
    )
    fail_assignment_once = True

    def fail_after_note_once(to_insert, to_correct, write_guard=None, vault_root=None):
        nonlocal fail_assignment_once
        if fail_assignment_once:
            fail_assignment_once = False
            raise RuntimeError("simulated failure after durable note projection failure")
        return {"pending": len(to_insert), "corrected": len(to_correct)}

    monkeypatch.setattr(segmenter, "commit_assignment_diff", fail_after_note_once)
    with pytest.raises(RuntimeError, match="after durable note"):
        segmenter.run_segmentation_tick(
            vault_root=tmp_path,
            registry=registry,
            write_guard=_healthy_guard(),
        )

    notes_dir = tmp_path / "episodes"
    note_paths = sorted(notes_dir.glob("ep-*.md"))
    assert len(note_paths) == 1
    note_fields = segmenter.parse_validated_episode_note(note_paths[0].read_text(encoding="utf-8"))
    episode_id = note_fields["episode_id"]
    assert note_fields["derived_from"] == ["screen:screen-a"]
    assert state["open_segment:work"]["derived_from"] == ["screen:screen-a"]
    assert cursor_positions[SCREEN_CONSUMER_ID] == 2

    projection_rows: set[str] = set()
    retry_requests: list[str] = []

    def successful_projection_retry(*, vault_root: Path, rel_path: str) -> None:
        retry_requests.append(rel_path)
        projection_rows.add(Path(rel_path).stem)

    monkeypatch.setattr(segmenter, "_retry_existing_episode_projection_sync", successful_projection_retry)
    import app.episodes.closure as closure_module

    closure_visibility: list[set[str]] = []
    monkeypatch.setattr(
        closure_module,
        "run_closure_tick",
        lambda **kwargs: (closure_visibility.append(set(projection_rows)) or {"closed": [], "events_emitted": 0}),
    )

    replay = segmenter.run_segmentation_tick(
        vault_root=tmp_path,
        registry=registry,
        write_guard=_healthy_guard(),
    )
    assert replay["proposed"] == []
    assert retry_requests == [f"episodes/{note_paths[0].name}"]
    assert episode_id in projection_rows
    assert len(list(notes_dir.glob("ep-*.md"))) == 1
    assert state["open_segment:work"]["derived_from"] == ["screen:screen-b"]
    assert cursor_positions[SCREEN_CONSUMER_ID] == 3

    # The retry is detached in production; after it succeeds, the next closure
    # scan can discover the restored projection row.
    segmenter.run_segmentation_tick(
        vault_root=tmp_path,
        registry=registry,
        write_guard=_healthy_guard(),
    )
    assert closure_visibility[-1] == {episode_id}


def test_episodes_cli_retries_founder_binding_after_interrupted_recut_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed first-adoption reconcile stays retryable through the public tick command."""
    rows = [_row("screen-a", sequence=1)]
    registry = _screen_only_registry()
    cursor_positions: dict[str, int] = {}

    def read_for_consumer(consumer_id: str, *, limit: int | None = None) -> Sequence[ObservationRow]:
        position = cursor_positions.get(consumer_id, 0)
        unread = [row for row in rows if row.sequence >= position]
        return unread[:limit] if limit is not None else unread

    def advance_for_consumer(consumer_id: str, consumed_rows: list[ObservationRow]) -> None:
        if consumed_rows:
            cursor_positions[consumer_id] = max(row.sequence for row in consumed_rows) + 1

    monkeypatch.setattr(segmenter, "read_observations_for_consumer", read_for_consumer)
    monkeypatch.setattr(segmenter, "advance_cursor_for_consumer", advance_for_consumer)
    monkeypatch.setattr(segmenter, "_sync_new_episode_row", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        segmenter,
        "_retry_existing_episode_projection_sync",
        lambda **kwargs: None,
    )
    state = _stub_tick_io(monkeypatch)

    production_segmenter_tick = segmenter.run_segmentation_tick

    def invoke_segmenter_tick(**kwargs):
        return production_segmenter_tick(
            registry=registry,
            write_guard=_healthy_guard(),
            **kwargs,
        )

    production_recut_tick = recut.run_recut_tick

    def invoke_recut_tick(**kwargs):
        return production_recut_tick(write_guard=_healthy_guard(), **kwargs)

    monkeypatch.setattr(episodes_cli_module, "run_segmentation_tick", invoke_segmenter_tick)
    monkeypatch.setattr(episodes_cli_module, "run_recut_tick", invoke_recut_tick)
    active_bindings: dict[tuple[str, str], dict[str, str]] = {}
    fail_segment_assignment = False

    def commit_segment_assignments(to_insert, to_correct, write_guard=None, vault_root=None):
        nonlocal fail_segment_assignment
        if fail_segment_assignment:
            fail_segment_assignment = False
            raise RuntimeError("simulated assignment interruption after canonical note write")
        for decision in to_insert:
            active_bindings[(decision.artifact_ref, decision.episode_id)] = {
                "binding_state": "active",
                "basis": decision.basis,
                "scope": decision.scope,
            }
        for key in to_correct:
            if key in active_bindings:
                active_bindings[key]["binding_state"] = "corrected"
        return {"pending": len(to_insert), "corrected": len(to_correct)}

    monkeypatch.setattr(segmenter, "commit_assignment_diff", commit_segment_assignments)
    fail_first_adoption_reconcile = False
    reconcile_calls: list[tuple[str, tuple[str, ...]]] = []

    def reconcile_first_adoption(
        episode_id: str,
        *,
        scope: str,
        start: datetime,
        end: datetime | None,
        derived_from: Sequence[str],
        write_guard=None,
        vault_root=None,
        flow_provider=None,
    ):
        nonlocal fail_first_adoption_reconcile
        refs = tuple(derived_from)
        reconcile_calls.append((episode_id, refs))
        if fail_first_adoption_reconcile:
            fail_first_adoption_reconcile = False
            raise RuntimeError("simulated interruption before founding binding reconciliation")
        for ref in refs:
            active_bindings[(ref, episode_id)] = {
                "binding_state": "active",
                "basis": "provenance",
                "scope": scope,
            }
        return {"pending": len(refs), "corrected": 0}

    monkeypatch.setattr(recut, "reconcile_episode_bindings", reconcile_first_adoption)
    runner = CliRunner()
    args = ["episodes", "tick", "--vault-root", str(tmp_path), "--json"]

    first = runner.invoke(cli, args)
    assert first.exit_code == 0, first.output
    assert cursor_positions[SCREEN_CONSUMER_ID] == 2
    assert state["open_segment:work"]["derived_from"] == ["screen:screen-a"]

    rows.append(
        _row(
            "screen-b",
            start="2026-07-11T08:02:00Z",
            end="2026-07-11T08:02:30Z",
            goal="goal two",
            sequence=2,
        )
    )
    fail_segment_assignment = True
    failed_segment = runner.invoke(cli, args)
    assert isinstance(failed_segment.exception, RuntimeError)
    assert "after canonical note write" in str(failed_segment.exception)
    notes_dir = tmp_path / "episodes"
    note_paths = sorted(notes_dir.glob("ep-*.md"))
    assert len(note_paths) == 1
    note_bytes = note_paths[0].read_bytes()
    episode_id = note_paths[0].stem
    assert cursor_positions[SCREEN_CONSUMER_ID] == 2
    assert state["open_segment:work"]["derived_from"] == ["screen:screen-a"]

    # Segmenter replay recovers the open replacement and acknowledges B. Then
    # fail the actual first-adoption reconciliation after segmenter returns.
    fail_first_adoption_reconcile = True
    failed_recut = runner.invoke(cli, args)
    assert isinstance(failed_recut.exception, RuntimeError)
    assert "before founding binding reconciliation" in str(failed_recut.exception)
    assert cursor_positions[SCREEN_CONSUMER_ID] == 3
    assert state["open_segment:work"]["derived_from"] == ["screen:screen-b"]
    assert ("screen:screen-a", episode_id) not in active_bindings
    assert not any(key.startswith(recut._RECUT_STATE_KEY_PREFIX) for key in state)
    assert note_paths[0].read_bytes() == note_bytes

    # With no new observation, the real CLI still runs recut. Since failed
    # reconciliation did not persist an adoption baseline, it retries A.
    healthy_retry = runner.invoke(cli, args)
    assert healthy_retry.exit_code == 0, healthy_retry.output
    summary = json.loads(healthy_retry.output)
    assert summary["proposed"] == []
    assert cursor_positions[SCREEN_CONSUMER_ID] == 3
    assert state["open_segment:work"]["derived_from"] == ["screen:screen-b"]
    assert len(list(notes_dir.glob("ep-*.md"))) == 1
    assert note_paths[0].read_bytes() == note_bytes
    assert active_bindings[("screen:screen-a", episode_id)]["binding_state"] == "active"
    assert reconcile_calls == [(episode_id, ("screen:screen-a",)), (episode_id, ("screen:screen-a",))]
