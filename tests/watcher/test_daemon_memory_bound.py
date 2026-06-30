from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.watcher import registry
from app.watcher.state import WatcherState

pytestmark = pytest.mark.watcher_controls

SCOPE_GLOB = "📥 Inbox/*.md,📥 Inbox/**/*.md,🛠️ Workbench/*.md,🛠️ Workbench/**/*.md"


def _write_note(base: Path, rel: str, body: str = "content") -> Path:
    path = base / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _make_cfg(tmp_path: Path) -> tuple[registry.RegistryConfig, registry.WatcherSpec, Path]:
    vault = tmp_path / "vault"
    state_dir = tmp_path / "state"
    cfg = registry.RegistryConfig(
        enable=True,
        outbox_path=tmp_path / "outbox.jsonl",
        vault_path=vault,
        scope_glob=SCOPE_GLOB,
        debounce_ms=0,
        rate_limit_per_min=120,
        state_dir=state_dir,
        heartbeat_path=tmp_path / "heartbeat.json",
        config_path=tmp_path / "watchers.yaml",
        summary_interval=0,
        stop_file=tmp_path / "WATCHER_STOP",
        tick_sleep_seconds=0.0,
        tick_log_path=tmp_path / "tick.jsonl",
        max_scanned_files_per_tick=10_000,
        max_bytes_read_per_tick=10_000_000,
        max_elapsed_ms_per_tick=10_000,
        max_bad_ticks=10,
        bad_tick_backoff_seconds=0.0,
        specs=[],
    )
    spec = registry.WatcherSpec(
        name="ingest",
        scope_glob=SCOPE_GLOB,
        debounce_ms=0,
        rate_limit_per_min=120,
        emit_event="ingest.vault.changed",
        backoff_seconds=0,
    )
    cfg.specs = [spec]
    cfg.stop_file.parent.mkdir(parents=True, exist_ok=True)
    return cfg, spec, vault


def _current_state_path(cfg: registry.RegistryConfig, spec: registry.WatcherSpec) -> Path:
    return registry._state_path(cfg.state_dir, spec.name)


def test_scoped_daemon_does_not_accumulate_unbounded_tick_state(tmp_path: Path) -> None:
    cfg, spec, vault = _make_cfg(tmp_path)
    inbox_note = _write_note(vault, "📥 Inbox/inbox.md")
    workbench_note = _write_note(vault, "🛠️ Workbench/workbench.md")

    historical_files = {
        f"Archive/{idx}.md": {
            "mtime": float(idx),
            "hash": f"deadbeef-{idx}",
            "last_seen": 1_700_000_000.0 - idx,
            "last_emitted": 1_700_000_000.0 - idx,
        }
        for idx in range(2_500)
    }
    state = WatcherState(files=historical_files, ticks_run=17, changed_detected=99, intents_emitted=23)

    summary = registry._run_spec_tick(cfg, spec, state, now=1_700_000_000.0)

    assert summary["changed_in_tick"] == 2
    assert set(state.files) == {
        str(inbox_note.relative_to(vault)),
        str(workbench_note.relative_to(vault)),
    }
    assert _current_state_path(cfg, spec).exists()
    assert _current_state_path(cfg, spec).stat().st_size < 20_000


def test_scoped_daemon_updates_heartbeat(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg, spec, vault = _make_cfg(tmp_path)
    _write_note(vault, "📥 Inbox/inbox.md")
    _write_note(vault, "🛠️ Workbench/workbench.md")

    times = iter([100.0, 101.0])
    heartbeat_calls: list[float | None] = []

    monkeypatch.setattr(registry.time, "time", lambda: next(times))
    monkeypatch.setattr(registry.time, "sleep", lambda _: None)
    monkeypatch.setattr(registry, "load_registry_config", lambda _: cfg)

    original_write = registry.write_registry_heartbeat

    def capture_write_registry_heartbeat(**kwargs):
        heartbeat_calls.append(kwargs.get("now"))
        return original_write(**kwargs)

    def fake_run_spec_tick(
        cfg_arg: registry.RegistryConfig,
        spec_arg: registry.WatcherSpec,
        state_arg: WatcherState,
        *,
        now: float,
        states=None,
        process_panel_notes_inline: bool = False,
    ) -> dict[str, object]:
        del cfg_arg, spec_arg, states, process_panel_notes_inline
        state_arg.ticks_run += 1
        state_arg.last_summary_at = now
        return {"backoff_active": False}

    monkeypatch.setattr(registry, "write_registry_heartbeat", capture_write_registry_heartbeat)
    monkeypatch.setattr(registry, "_run_spec_tick", fake_run_spec_tick)

    registry.run_registry_forever(cfg.config_path, max_ticks=2)

    assert heartbeat_calls == [100.0, 101.0]
    heartbeat = json.loads(cfg.heartbeat_path.read_text(encoding="utf-8"))
    assert heartbeat["ts"] == 101.0
    assert heartbeat["status"] == "running"
    assert heartbeat["watchers"][spec.name]["ticks_total"] == 2


def test_daemon_file_outputs_are_bounded(tmp_path: Path) -> None:
    cfg, spec, vault = _make_cfg(tmp_path)
    _write_note(vault, "📥 Inbox/inbox.md")
    _write_note(vault, "🛠️ Workbench/workbench.md")

    state = WatcherState(
        files={
            f"Archive/{idx}.md": {
                "mtime": float(idx),
                "hash": f"deadbeef-{idx}",
                "last_seen": 1_700_000_000.0 - idx,
                "last_emitted": 1_700_000_000.0 - idx,
            }
            for idx in range(1_500)
        }
    )

    summary1 = registry._run_spec_tick(cfg, spec, state, now=1_700_000_100.0)
    summary2 = registry._run_spec_tick(cfg, spec, state, now=1_700_000_110.0)

    assert summary1["changed_in_tick"] == 2
    assert summary2["changed_in_tick"] == 0
    assert len(cfg.tick_log_path.read_text(encoding="utf-8").splitlines()) == 2
    assert cfg.tick_log_path.stat().st_size < 10_000
    assert cfg.outbox_path.stat().st_size < 10_000
    assert _current_state_path(cfg, spec).stat().st_size < 20_000
