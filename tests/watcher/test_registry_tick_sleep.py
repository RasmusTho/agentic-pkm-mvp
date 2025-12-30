from __future__ import annotations

import os
from pathlib import Path

import pytest

import app.watcher.registry as registry

pytestmark = pytest.mark.not_pg


def _write_config(path: Path) -> None:
    payload = (
        "watchers:\n"
        "  - name: panel\n"
        "    scope_glob: \"@Inbox/**\"\n"
        "    debounce_ms: 1500\n"
        "    rate_limit_per_min: 30\n"
        "    backoff_seconds: 10\n"
        "    emit_event: true\n"
    )
    path.write_text(payload, encoding="utf-8")


def test_registry_tick_sleep_seconds_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "watchers.yaml"
    _write_config(config_path)

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.75")
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "1")
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(tmp_path / "watcher_heartbeat.json"))
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))

    cfg = registry.load_registry_config(config_path)
    assert cfg.tick_sleep_seconds == 0.75

    seen: list[float] = []

    def fake_summary(name, state, *, backoff_active: bool, tick_sleep_seconds: float) -> str:
        seen.append(tick_sleep_seconds)
        return "summary"

    monkeypatch.setattr(registry, "_summary_line", fake_summary)
    monkeypatch.setattr(registry, "_run_spec_tick", lambda *args, **kwargs: {"backoff_active": False})

    registry.run_registry_forever(config_path, max_ticks=1)

    assert seen == [0.75]


def test_registry_tick_sleep_clamps_minimum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "watchers.yaml"
    _write_config(config_path)

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(tmp_path / "vault"))
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0")
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "1")
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(tmp_path / "watcher_heartbeat.json"))
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))

    cfg = registry.load_registry_config(config_path)
    assert cfg.tick_sleep_seconds == registry.MIN_TICK_SLEEP_SECONDS
