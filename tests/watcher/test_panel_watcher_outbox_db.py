from __future__ import annotations

import json
import logging
from pathlib import Path

from app.events.schema import OutboxEvent
from app.settings.panel_actions import PanelActionMapping
from app.vault.paths import get_vault_inbox_dir_rel
from app.watcher.registry import _emit_panel_events, _process_panel_note, RegistryConfig, WatcherSpec, _run_spec_tick
from app.watcher.state import WatcherState


def test_process_panel_note_enqueues_db_and_jsonl(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    note_dir = vault / get_vault_inbox_dir_rel(vault)
    note_dir.mkdir()
    note_path = note_dir / "note.md"
    note_path.write_text(
        """---
uuid: test-uuid
---
# Panel
- [x] Make this note evergreen <!--ai:id=promote.evergreen-->
""",
        encoding="utf-8",
    )

    events: list[OutboxEvent] = []

    def fake_write_outbox(ev):
        events.append(ev)
        return "ok"

    monkeypatch.setattr("app.watcher.registry.write_outbox_event", fake_write_outbox)

    outbox_jsonl = tmp_path / "outbox.jsonl"
    mappings = {
        "Make this note evergreen": PanelActionMapping(
            text="Make this note evergreen",
            event_type="promote.intent.created",
            payload_template={"maturity": "evergreen"},
            action_id="promote.evergreen",
        )
    }
    state = WatcherState()

    _process_panel_note(
        vault_root=vault,
        rel_path=note_path.relative_to(vault),
        outbox_path=outbox_jsonl,
        state=state,
        action_mappings=mappings,
    )

    assert events, "expected DB outbox event"
    assert outbox_jsonl.exists(), "expected JSONL telemetry"
    payloads = [
        json.loads(line)
        for line in outbox_jsonl.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert payloads, "expected payloads in JSONL"


def test_process_panel_note_retries_transient_read_failure(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    note_dir = vault / get_vault_inbox_dir_rel(vault)
    note_dir.mkdir()
    note_path = note_dir / "note.md"
    note_path.write_text(
        """---
uuid: test-uuid
---
# Panel
- [x] Make this note evergreen <!--ai:id=promote.evergreen-->
""",
        encoding="utf-8",
    )

    events: list[OutboxEvent] = []

    def fake_write_outbox(ev):
        events.append(ev)
        return "ok"

    monkeypatch.setattr("app.watcher.registry.write_outbox_event", fake_write_outbox)

    attempts = {"count": 0}
    real_read = Path.read_text

    def flaky_read(self: Path, *args, **kwargs):
        if self == note_path and attempts["count"] == 0:
            attempts["count"] += 1
            raise OSError(2, "No such file or directory")
        return real_read(self, *args, **kwargs)

    monkeypatch.setattr("pathlib.Path.read_text", flaky_read)

    mappings = {
        "Make this note evergreen": PanelActionMapping(
            text="Make this note evergreen",
            event_type="promote.intent.created",
            payload_template={"maturity": "evergreen"},
            action_id="promote.evergreen",
        )
    }
    state = WatcherState()

    written = _process_panel_note(
        vault_root=vault,
        rel_path=note_path.relative_to(vault),
        outbox_path=tmp_path / "outbox.jsonl",
        state=state,
        action_mappings=mappings,
    )

    assert written > 0
    assert events


def test_process_panel_note_retries_transient_uuid_failure(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    note_dir = vault / get_vault_inbox_dir_rel(vault)
    note_dir.mkdir()
    note_path = note_dir / "note.md"
    note_path.write_text(
        """---
uuid: test-uuid
---
# Panel
- [x] Make this note evergreen <!--ai:id=promote.evergreen-->
""",
        encoding="utf-8",
    )

    events: list[OutboxEvent] = []

    def fake_write_outbox(ev):
        events.append(ev)
        return "ok"

    monkeypatch.setattr("app.watcher.registry.write_outbox_event", fake_write_outbox)

    attempts = {"count": 0}

    def flaky_ensure(path: Path) -> str:
        if path == note_path and attempts["count"] == 0:
            attempts["count"] += 1
            raise OSError(2, "No such file or directory")
        return "test-uuid"

    monkeypatch.setattr("app.watcher.registry.ensure_note_uuid", flaky_ensure)

    mappings = {
        "Make this note evergreen": PanelActionMapping(
            text="Make this note evergreen",
            event_type="promote.intent.created",
            payload_template={"maturity": "evergreen"},
            action_id="promote.evergreen",
        )
    }
    state = WatcherState()

    written = _process_panel_note(
        vault_root=vault,
        rel_path=note_path.relative_to(vault),
        outbox_path=tmp_path / "outbox.jsonl",
        state=state,
        action_mappings=mappings,
    )

    assert written > 0
    assert events


def test_emit_panel_events_counts_only_real_emissions(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    note_dir = vault / get_vault_inbox_dir_rel(vault)
    note_dir.mkdir()
    note_path = note_dir / "note.md"
    note_path.write_text("stub", encoding="utf-8")

    cfg = RegistryConfig(
        enable=True,
        outbox_path=tmp_path / "outbox.jsonl",
        vault_path=vault,
        scope_glob="*.md",
        debounce_ms=0,
        rate_limit_per_min=30,
        state_dir=tmp_path / "state",
        heartbeat_path=tmp_path / "heartbeat.json",
        config_path=tmp_path / "watchers.yaml",
        summary_interval=0,
        stop_file=tmp_path / "WATCHER_STOP",
        tick_sleep_seconds=0.2,
        tick_log_path=tmp_path / "watcher_tick.jsonl",
        max_scanned_files_per_tick=500,
        max_bytes_read_per_tick=50_000_000,
        max_elapsed_ms_per_tick=2000,
        max_bad_ticks=10,
        bad_tick_backoff_seconds=2.0,
        specs=[],
    )
    spec = WatcherSpec(
        name="panel",
        scope_glob="*.md",
        debounce_ms=0,
        rate_limit_per_min=30,
        emit_event="panel.scan.requested",
    )
    state = WatcherState()

    monkeypatch.setattr("app.watcher.registry._process_panel_note", lambda **_: 0)

    trace_id = _emit_panel_events(
        spec=spec,
        cfg=cfg,
        rel=note_path.relative_to(vault),
        mtime=note_path.stat().st_mtime,
        digest="hash",
        state=state,
        action_mappings={},
    )

    assert trace_id is None
    assert state.intents_emitted == 0
    assert state.last_trace_id is None


def test_emit_panel_events_updates_state_after_success(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    note_dir = vault / get_vault_inbox_dir_rel(vault)
    note_dir.mkdir()
    note_path = note_dir / "note.md"
    note_path.write_text("stub", encoding="utf-8")

    cfg = RegistryConfig(
        enable=True,
        outbox_path=tmp_path / "outbox.jsonl",
        vault_path=vault,
        scope_glob="*.md",
        debounce_ms=0,
        rate_limit_per_min=30,
        state_dir=tmp_path / "state",
        heartbeat_path=tmp_path / "heartbeat.json",
        config_path=tmp_path / "watchers.yaml",
        summary_interval=0,
        stop_file=tmp_path / "WATCHER_STOP",
        tick_sleep_seconds=0.2,
        tick_log_path=tmp_path / "watcher_tick.jsonl",
        max_scanned_files_per_tick=500,
        max_bytes_read_per_tick=50_000_000,
        max_elapsed_ms_per_tick=2000,
        max_bad_ticks=10,
        bad_tick_backoff_seconds=2.0,
        specs=[],
    )
    spec = WatcherSpec(
        name="panel",
        scope_glob="*.md",
        debounce_ms=0,
        rate_limit_per_min=30,
        emit_event="panel.scan.requested",
    )
    state = WatcherState()

    monkeypatch.setattr("app.watcher.registry._process_panel_note", lambda **_: 2)

    trace_id = _emit_panel_events(
        spec=spec,
        cfg=cfg,
        rel=note_path.relative_to(vault),
        mtime=note_path.stat().st_mtime,
        digest="hash",
        state=state,
        action_mappings={},
    )

    assert trace_id
    assert state.intents_emitted == 1
    assert state.last_trace_id == trace_id
    file_state = state.files[str(note_path.relative_to(vault))]
    assert file_state.get("last_emitted") is not None


def test_run_spec_tick_does_not_count_panel_when_emit_returns_none(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    note_dir = vault / get_vault_inbox_dir_rel(vault)
    note_dir.mkdir()
    note_path = note_dir / "note.md"
    note_path.write_text("%% AI %%\n- [x] Make this note evergreen <!--ai:id=promote.evergreen-->\n%% AI %%\n", encoding="utf-8")

    cfg = RegistryConfig(
        enable=True,
        outbox_path=tmp_path / "outbox.jsonl",
        vault_path=vault,
        scope_glob="📥 Inbox/*.md",
        debounce_ms=0,
        rate_limit_per_min=30,
        state_dir=tmp_path / "state",
        heartbeat_path=tmp_path / "heartbeat.json",
        config_path=tmp_path / "watchers.yaml",
        summary_interval=0,
        stop_file=tmp_path / "WATCHER_STOP",
        tick_sleep_seconds=0.2,
        tick_log_path=tmp_path / "watcher_tick.jsonl",
        max_scanned_files_per_tick=500,
        max_bytes_read_per_tick=50_000_000,
        max_elapsed_ms_per_tick=2000,
        max_bad_ticks=10,
        bad_tick_backoff_seconds=2.0,
        specs=[],
    )
    spec = WatcherSpec(
        name="panel",
        scope_glob="📥 Inbox/*.md",
        debounce_ms=0,
        rate_limit_per_min=30,
        emit_event="panel.scan.requested",
    )
    state = WatcherState()

    monkeypatch.setattr("app.watcher.registry._emit_watch_event", lambda **_: None)
    monkeypatch.setattr("app.watcher.registry._panel_candidate_for_path", lambda *_: (True, True))
    monkeypatch.setattr("app.watcher.registry._auto_exec_enabled", lambda *_args, **_kwargs: True)

    summary = _run_spec_tick(cfg, spec, state, now=note_path.stat().st_mtime + 1)

    assert summary["emitted_in_tick"] == 0
    assert state.intents_emitted == 0
    assert state.last_trace_id is None


def test_emit_panel_events_logs_no_event_outcome(tmp_path, monkeypatch, caplog):
    vault = tmp_path / "vault"
    vault.mkdir()
    note_dir = vault / get_vault_inbox_dir_rel(vault)
    note_dir.mkdir()
    note_path = note_dir / "note.md"
    note_path.write_text("stub", encoding="utf-8")

    cfg = RegistryConfig(
        enable=True,
        outbox_path=tmp_path / "outbox.jsonl",
        vault_path=vault,
        scope_glob="*.md",
        debounce_ms=0,
        rate_limit_per_min=30,
        state_dir=tmp_path / "state",
        heartbeat_path=tmp_path / "heartbeat.json",
        config_path=tmp_path / "watchers.yaml",
        summary_interval=0,
        stop_file=tmp_path / "WATCHER_STOP",
        tick_sleep_seconds=0.2,
        tick_log_path=tmp_path / "watcher_tick.jsonl",
        max_scanned_files_per_tick=500,
        max_bytes_read_per_tick=50_000_000,
        max_elapsed_ms_per_tick=2000,
        max_bad_ticks=10,
        bad_tick_backoff_seconds=2.0,
        specs=[],
    )
    spec = WatcherSpec(
        name="panel",
        scope_glob="*.md",
        debounce_ms=0,
        rate_limit_per_min=30,
        emit_event="panel.scan.requested",
    )
    state = WatcherState()

    monkeypatch.setattr("app.watcher.registry._process_panel_note", lambda **_: 0)

    caplog.set_level(logging.INFO)
    trace_id = _emit_panel_events(
        spec=spec,
        cfg=cfg,
        rel=note_path.relative_to(vault),
        mtime=note_path.stat().st_mtime,
        digest="hash",
        state=state,
        action_mappings={},
    )

    assert trace_id is None
    assert any("panel emit produced no events" in rec.getMessage() for rec in caplog.records)
