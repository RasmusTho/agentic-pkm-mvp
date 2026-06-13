from __future__ import annotations

from pathlib import Path

import pytest

import app.watcher.registry as registry
from tests.helpers.vault_settings import initialize_test_vault

pytestmark = pytest.mark.not_pg


def _write_config(path: Path) -> None:
    payload = (
        "watchers:\n"
        "  - name: panel\n"
        '    scope_glob: ""\n'
        "    debounce_ms: 1500\n"
        "    rate_limit_per_min: 30\n"
        "    backoff_seconds: 10\n"
        "    emit_event: true\n"
    )
    path.write_text(payload, encoding="utf-8")


def _base_env(tmp_path: Path, *, tick_sleep: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    vault_path = tmp_path / "vault"
    initialize_test_vault(vault_path)

    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault_path))
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", tick_sleep)
    monkeypatch.setenv("WATCHER_SUMMARY_INTERVAL", "1")
    monkeypatch.setenv("WATCHER_HEARTBEAT_PATH", str(tmp_path / "watcher_heartbeat.json"))
    monkeypatch.setenv("WATCHER_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    return vault_path


def test_registry_tick_sleep_seconds_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "watchers.yaml"
    _write_config(config_path)

    _base_env(tmp_path, tick_sleep="0.75", monkeypatch=monkeypatch)

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

    _base_env(tmp_path, tick_sleep="0", monkeypatch=monkeypatch)

    cfg = registry.load_registry_config(config_path)
    assert cfg.tick_sleep_seconds == registry.MIN_TICK_SLEEP_SECONDS


def test_registry_tick_sleep_calls_sleep(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "watchers.yaml"
    _write_config(config_path)

    _base_env(tmp_path, tick_sleep="1.0", monkeypatch=monkeypatch)

    calls: list[float] = []

    def fake_sleep(value: float) -> None:
        calls.append(value)

    monkeypatch.setattr(registry.time, "sleep", fake_sleep)
    monkeypatch.setattr(registry, "_run_spec_tick", lambda *args, **kwargs: {"backoff_active": False})
    monkeypatch.setattr(registry, "_summary_line", lambda *args, **kwargs: "summary")

    registry.run_registry_forever(config_path, max_ticks=2)

    assert calls == [1.0]


def test_registry_scope_glob_uses_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "watchers.yaml"
    _write_config(config_path)

    _base_env(tmp_path, tick_sleep="0.5", monkeypatch=monkeypatch)
    monkeypatch.setenv("WATCHER_SCOPE_GLOB", "CustomScope/**")

    cfg = registry.load_registry_config(config_path)
    assert cfg.scope_glob == "CustomScope/**"
    assert cfg.specs[0].scope_glob == "CustomScope/**"


def test_registry_scope_glob_defaults_vaultwide(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_path = tmp_path / "watchers.yaml"
    _write_config(config_path)

    _base_env(tmp_path, tick_sleep="0.5", monkeypatch=monkeypatch)
    monkeypatch.delenv("WATCHER_SCOPE_GLOB", raising=False)

    cfg = registry.load_registry_config(config_path)
    assert cfg.scope_glob == "*.md,**/*.md"
    assert cfg.specs[0].scope_glob == "*.md,**/*.md"
