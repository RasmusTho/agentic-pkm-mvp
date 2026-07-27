from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace

from app.events.schema import OutboxEvent
from app.knowledge.multiwriter import is_conflict_artifact
from app.knowledge.write_ops import write_note_from_absolute
from app.settings.panel_actions import PanelActionMapping
from app.vault.paths import get_vault_inbox_dir_rel
import app.watcher.registry as registry
from app.watcher.registry import _emit_panel_events, _process_panel_note, RegistryConfig, WatcherSpec, _run_spec_tick
from app.watcher.state import WatcherState


def test_process_panel_note_uses_canonical_store_identity(tmp_path, monkeypatch):
    vault_uuid = "11111111-1111-4111-8111-111111111111"
    canonical_id = "22222222-2222-4222-8222-222222222222"
    vault = tmp_path / "vault"
    vault.mkdir()
    note_path = vault / "panel.md"
    markdown = f"---\nuuid: {vault_uuid}\n---\n\n# Panel\n"
    note_path.write_text(markdown, encoding="utf-8")
    seen: dict[str, str] = {}

    monkeypatch.setattr(
        "app.watcher.registry.resolve_canonical_object_id",
        lambda value: seen.setdefault("vault_uuid", value) and canonical_id,
    )

    def fake_handle_note_update(*, note_id, **_kwargs):
        seen["note_id"] = note_id
        return SimpleNamespace(updated_markdown=markdown, events=[])

    monkeypatch.setattr("app.watcher.registry.handle_note_update", fake_handle_note_update)

    _process_panel_note(
        vault_root=vault,
        rel_path=note_path.relative_to(vault),
        outbox_path=tmp_path / "outbox.jsonl",
        state=WatcherState(),
        action_mappings={},
    )

    assert seen == {"vault_uuid": vault_uuid, "note_id": canonical_id}


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

    def fake_write_outbox(ev, **kwargs):
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


def test_process_panel_note_stale_write_has_no_acknowledgement_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    note_path = vault / "note.md"
    note_path.write_text(
        "---\nuuid: test-uuid\n---\n\n- [x] Do thing\n",
        encoding="utf-8",
    )
    concurrent = "---\nuuid: test-uuid\n---\n\nConcurrent human body\n"
    event = OutboxEvent(
        event="promote.intent.created",
        source="test",
        payload={"note": {"uuid": "test-uuid"}},
    )
    persisted_ids: list[object] = []
    emitted_events: list[object] = []

    monkeypatch.setattr(
        registry,
        "handle_note_update",
        lambda **kwargs: SimpleNamespace(
            updated_markdown="Prepared stale output\n",
            events=[event],
            executed_action_ids=["action-1"],
        ),
    )

    def interleave_human_write(
        path: Path,
        content: str,
        **kwargs: object,
    ):
        note_path.write_text(concurrent, encoding="utf-8")
        return write_note_from_absolute(path, content, **kwargs)

    monkeypatch.setattr(
        registry,
        "write_note_from_absolute",
        interleave_human_write,
    )
    monkeypatch.setattr(
        registry,
        "upsert_executed_ids",
        lambda *args, **kwargs: persisted_ids.append((args, kwargs)),
    )
    monkeypatch.setattr(
        registry,
        "write_outbox_event",
        lambda *args, **kwargs: emitted_events.append((args, kwargs)),
    )
    monkeypatch.setattr(
        registry,
        "_write_jsonl_event",
        lambda *args, **kwargs: emitted_events.append((args, kwargs)),
    )
    state = WatcherState()

    emitted = _process_panel_note(
        vault_root=vault,
        rel_path=note_path.relative_to(vault),
        outbox_path=tmp_path / "outbox.jsonl",
        state=state,
        action_mappings={},
    )

    assert emitted == 0
    assert state.errors == 1
    assert persisted_ids == []
    assert emitted_events == []
    assert note_path.read_text(encoding="utf-8") == concurrent
    artifacts = [
        path
        for path in note_path.parent.iterdir()
        if path != note_path and is_conflict_artifact(path.name)
    ]
    assert len(artifacts) == 1
    assert artifacts[0].read_text(encoding="utf-8") == "Prepared stale output\n"


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

    def fake_write_outbox(ev, **kwargs):
        events.append(ev)
        return "ok"

    monkeypatch.setattr("app.watcher.registry.write_outbox_event", fake_write_outbox)

    attempts = {"count": 0}
    real_read = registry.read_note_text_with_version

    def flaky_read(path: Path):
        if path == note_path and attempts["count"] == 0:
            attempts["count"] += 1
            raise OSError(2, "No such file or directory")
        return real_read(path)

    monkeypatch.setattr(registry, "read_note_text_with_version", flaky_read)

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
    assert attempts["count"] == 1


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

    def fake_write_outbox(ev, **kwargs):
        events.append(ev)
        return "ok"

    monkeypatch.setattr("app.watcher.registry.write_outbox_event", fake_write_outbox)

    attempts = {"count": 0}

    def flaky_ensure(path: Path, *, vault_root: Path) -> str:
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


def test_run_spec_tick_emits_second_panel_change_after_idle_tick(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    note_dir = vault / get_vault_inbox_dir_rel(vault) / "_alpha_e2e"
    note_dir.mkdir(parents=True)
    note_path = note_dir / "note.md"
    note_path.write_text("%% AI %%\n- [ ] Make this note evergreen <!--ai:id=promote.evergreen-->\n%% AI %%\n", encoding="utf-8")

    cfg = RegistryConfig(
        enable=True,
        outbox_path=tmp_path / "outbox.jsonl",
        vault_path=vault,
        scope_glob="📥 Inbox/_alpha_e2e/*.md",
        debounce_ms=1000,
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
        scope_glob="📥 Inbox/_alpha_e2e/*.md",
        debounce_ms=1000,
        rate_limit_per_min=30,
        emit_event="panel.scan.requested",
    )
    state = WatcherState()

    emissions: list[str] = []

    def fake_emit_watch_event(**kwargs):
        emissions.append(str(kwargs["rel_path"]))
        return f"trace-{len(emissions)}"

    monkeypatch.setattr("app.watcher.registry._emit_watch_event", fake_emit_watch_event)
    monkeypatch.setattr("app.watcher.registry._panel_candidate_for_path", lambda *_: (True, True))
    monkeypatch.setattr("app.watcher.registry._auto_exec_enabled", lambda *_args, **_kwargs: True)

    first_mtime = note_path.stat().st_mtime
    first = _run_spec_tick(cfg, spec, state, now=first_mtime + 0.1)
    assert first["emitted_in_tick"] == 1

    idle = _run_spec_tick(cfg, spec, state, now=first_mtime + 0.6)
    assert idle["emitted_in_tick"] == 0

    note_path.write_text("%% AI %%\n- [x] Make this note evergreen <!--ai:id=promote.evergreen-->\n%% AI %%\n", encoding="utf-8")
    second_mtime = first_mtime + 2
    os.utime(note_path, (second_mtime, second_mtime))

    second = _run_spec_tick(cfg, spec, state, now=first_mtime + 1.6)
    assert second["emitted_in_tick"] == 1
    assert emissions == [str(note_path.relative_to(vault)), str(note_path.relative_to(vault))]


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
