"""ERE screen stream adapter contract and production-path coverage (#3346)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Sequence

import pytest

from app.episodes import segmenter
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
