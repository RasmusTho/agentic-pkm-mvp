from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from app.episodes import closure, segmenter
from app.episodes.stream_registry import STATUS_LIVE, StreamRegistry, StreamRegistryEntry, load_registry
from app.write_guard import WriteGuard


def _entry(stream_id: str) -> StreamRegistryEntry:
    return StreamRegistryEntry(
        stream_id=stream_id,
        status=STATUS_LIVE,
        owner_constituent="fixture",
        dimensions_fed=("time",),
        transport="module:app.episodes.segmenter",
        consent_class="fixture",
        cadence="sparse",
    )


@pytest.fixture(autouse=True)
def _tick_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(segmenter.engine_state, "all_state_with_prefix", lambda prefix: {})
    monkeypatch.setattr(segmenter.engine_state, "set_state", lambda key, value: None)
    monkeypatch.setattr(segmenter.engine_state, "delete_state", lambda key: None)
    monkeypatch.setattr(
        segmenter,
        "_emit_proposals_with_fusion_gate",
        lambda *a, **k: {"proposed": [], "fused": [], "fusions_denied": 0},
    )
    monkeypatch.setattr(closure, "run_closure_tick", lambda **k: {"closed": [], "events_emitted": 0})
    monkeypatch.setattr(segmenter, "artifact_candidates_from_signals", lambda signals: [])
    monkeypatch.setattr(segmenter, "episode_bounds_from_closed_segments", lambda *a, **k: [])
    monkeypatch.setattr(segmenter, "read_candidate_episodes_for_scopes", lambda scopes: [])
    monkeypatch.setattr(segmenter, "read_existing_bindings", lambda refs: {})
    monkeypatch.setattr(segmenter, "read_existing_bindings_for_episodes", lambda episode_ids: {})
    monkeypatch.setattr(
        segmenter,
        "commit_assignment_diff",
        lambda *a, **k: {"pending": 0, "corrected": 0},
    )


def _guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy", "reason": None})


def _signal(stream_id: str, signal_id: str, minute: int, *, hour: int = 9) -> segmenter.SegmentationSignal:
    return segmenter.SegmentationSignal(
        stream_id=stream_id,
        signal_id=signal_id,
        observed_at=datetime(2026, 7, 11, hour, minute, tzinfo=timezone.utc),
        scope="work",
        provenance_ref=f"{stream_id}:{signal_id}",
    )


@dataclass
class _FixtureAdapter:
    stream_id: str
    rows: list[Any]
    signal: segmenter.SegmentationSignal | None = None
    degraded: tuple[str, ...] = ()
    advances: list[str] | None = None
    crash_once: bool = False
    advanced: bool = False

    def read(self, ctx: segmenter.TickContext) -> segmenter.ReadResult:
        return segmenter.ReadResult(rows=[] if self.advanced else self.rows, degraded=self.degraded)

    def normalize(self, row: Any, ctx: segmenter.TickContext) -> segmenter.SegmentationSignal | None:
        return self.signal

    def advance_cursor(self, rows: list[Any], ctx: segmenter.TickContext) -> None:
        if self.advances is not None:
            self.advances.append(self.stream_id)
        if self.crash_once:
            self.crash_once = False
            raise RuntimeError("simulated crash between cursor advances")
        if rows:
            self.advanced = True


def test_three_live_streams_expose_adapters() -> None:
    for stream_id in (
        segmenter.HEIMDAL_STREAM_ID,
        segmenter.VAULT_ACTIVITY_STREAM_ID,
        segmenter.CALENDAR_STREAM_ID,
    ):
        adapter = segmenter.resolve_stream_adapter(_entry(stream_id))
        assert isinstance(adapter, segmenter.StreamAdapter)
        assert callable(adapter.read)
        assert callable(adapter.normalize)
        assert callable(adapter.advance_cursor)
    assert segmenter.ReadResult(rows=[], degraded=[]).degraded == []


def test_tick_dispatches_purely_via_registry(tmp_path: Path) -> None:
    first, second = _entry("fixture.one"), _entry("fixture.two")
    registry = StreamRegistry({first.stream_id: first, second.stream_id: second})
    adapters = {
        first.stream_id: _FixtureAdapter(first.stream_id, [1]),
        second.stream_id: _FixtureAdapter(second.stream_id, [2, 3]),
    }

    result = segmenter.run_segmentation_tick(
        vault_root=tmp_path, registry=registry, adapters=adapters, write_guard=_guard()
    )

    assert result["consumed"] == {"fixture.one": 1, "fixture.two": 2}


def test_tick_output_byte_identical_to_prerefactor_golden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    entries = [_entry(segmenter.HEIMDAL_STREAM_ID), _entry(segmenter.VAULT_ACTIVITY_STREAM_ID), _entry(segmenter.CALENDAR_STREAM_ID)]
    registry = StreamRegistry({entry.stream_id: entry for entry in entries})
    adapters = {
        entries[0].stream_id: _FixtureAdapter(entries[0].stream_id, [1], _signal(entries[0].stream_id, "obs-1", 0)),
        entries[1].stream_id: _FixtureAdapter(entries[1].stream_id, [2, 3], _signal(entries[1].stream_id, "vault-1", 5)),
        entries[2].stream_id: _FixtureAdapter(
            entries[2].stream_id,
            [4],
            _signal(entries[2].stream_id, "cal-1", 10),
            degraded=("work-calendar",),
        ),
    }
    monkeypatch.setattr(
        segmenter,
        "_emit_proposals_with_fusion_gate",
        lambda closed, **k: {"proposed": [], "fused": [], "fusions_denied": 0},
    )

    result = segmenter.run_segmentation_tick(
        vault_root=tmp_path, registry=registry, adapters=adapters, write_guard=_guard()
    )
    prerefactor_golden = {
        "consumed": {
            segmenter.HEIMDAL_STREAM_ID: 1,
            segmenter.VAULT_ACTIVITY_STREAM_ID: 2,
            segmenter.CALENDAR_STREAM_ID: 1,
        },
        "skipped_no_observation_time": {},
        "proposed": [],
        "fused": [],
        "fusions_denied": 0,
        "open_segments": 1,
        "assigned": {"pending": 0, "corrected": 0},
        "closed": [],
        "events_emitted": 0,
        "degraded": ["work-calendar"],
    }
    assert {key: result[key] for key in prerefactor_golden} == prerefactor_golden


def test_deferred_cursor_advance_preserves_crash_safety(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[str] = []
    proposals: list[str] = []
    durable_state: dict[str, dict[str, Any]] = {}
    entries = [_entry("fixture.one"), _entry("fixture.two")]
    registry = StreamRegistry({entry.stream_id: entry for entry in entries})
    adapters = {
        entries[0].stream_id: _FixtureAdapter(
            entries[0].stream_id,
            [object()],
            _signal(entries[0].stream_id, "one", 0),
            advances=events,
        ),
        entries[1].stream_id: _FixtureAdapter(
            entries[1].stream_id,
            [object()],
            _signal(entries[1].stream_id, "two", 0, hour=10),
            advances=events,
            crash_once=True,
        ),
    }
    monkeypatch.setattr(segmenter.engine_state, "all_state_with_prefix", lambda prefix: dict(durable_state))
    monkeypatch.setattr(
        segmenter.engine_state,
        "set_state",
        lambda key, value: (events.append("persist"), durable_state.__setitem__(key, value)),
    )
    monkeypatch.setattr(
        segmenter,
        "_emit_proposals_with_fusion_gate",
        lambda closed, **k: (
            events.append("emit"),
            proposals.extend(c.derived_from[0] for c in closed),
            {"proposed": [c.derived_from[0] for c in closed], "fused": [], "fusions_denied": 0},
        )[-1],
    )

    with pytest.raises(RuntimeError, match="between cursor advances"):
        segmenter.run_segmentation_tick(
            vault_root=tmp_path, registry=registry, adapters=adapters, write_guard=_guard()
        )
    assert proposals == ["fixture.one:one"]
    assert events.index("persist") < events.index("fixture.one") < events.index("fixture.two")

    result = segmenter.run_segmentation_tick(
        vault_root=tmp_path, registry=registry, adapters=adapters, write_guard=_guard()
    )
    assert result["proposed"] == []
    assert proposals == ["fixture.one:one"]


def test_new_stream_joins_via_registry_and_adapter_only(tmp_path: Path) -> None:
    entry = _entry("future.fixture")
    result = segmenter.run_segmentation_tick(
        vault_root=tmp_path,
        registry=StreamRegistry({entry.stream_id: entry}),
        adapters={entry.stream_id: _FixtureAdapter(entry.stream_id, [1, 2, 3])},
        write_guard=_guard(),
    )
    assert result["consumed"] == {entry.stream_id: 3}


def test_every_live_entry_resolves_to_an_adapter() -> None:
    registry = load_registry()

    for entry in registry.live_entries():
        assert segmenter.resolve_stream_adapter(entry) is not None


def test_live_without_adapter_fails_loud_at_tick(tmp_path: Path) -> None:
    entry = _entry("fixture.unadapted")

    with pytest.raises(RuntimeError, match=r"fixture\.unadapted.*live.*no adapter"):
        segmenter.run_segmentation_tick(
            vault_root=tmp_path,
            registry=StreamRegistry({entry.stream_id: entry}),
            adapters={},
            write_guard=_guard(),
        )
