from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from app.watcher.config import WatcherConfig
from app.watcher.registry import RegistryConfig, WatcherSpec
from app.settings import compiler
from app.settings.ingestion import SettingsIngestionState
from app.settings.models import SettingsBundle, WatcherAndTuningSettings
from tests.helpers.vault_settings import initialize_test_vault


pytestmark = pytest.mark.not_pg


def _specs() -> list[WatcherSpec]:
    return [
        WatcherSpec(
            name="ingest",
            scope_glob="",
            debounce_ms=0,
            rate_limit_per_min=0,
            emit_event="ingest.vault.changed",
        )
    ]


def _write_registry_config(path: Path) -> None:
    path.write_text(
        dedent(
            """\
            version: 1
            watchers:
              - name: ingest
                scope_glob: ""
                debounce_ms: 50
                rate_limit_per_min: 120
                emit_event: "ingest.vault.changed"
            """
        ),
        encoding="utf-8",
    )


def test_registry_ignores_dev_knobs_in_operator_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault"
    initialize_test_vault(vault)
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "operator")
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "1")
    monkeypatch.setenv("WATCHER_RATE_LIMIT_PER_MIN", "2")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.75")

    cfg = RegistryConfig.from_env(_specs(), config_path=tmp_path / "watchers.yaml")
    assert cfg.debounce_ms == 1500
    assert cfg.rate_limit_per_min == 30
    assert cfg.tick_sleep_seconds == 0.2


def test_registry_honors_dev_knobs_in_lab_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault"
    initialize_test_vault(vault)
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "1")
    monkeypatch.setenv("WATCHER_RATE_LIMIT_PER_MIN", "2")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.75")

    cfg = RegistryConfig.from_env(_specs(), config_path=tmp_path / "watchers.yaml")
    assert cfg.debounce_ms == 1
    assert cfg.rate_limit_per_min == 2
    assert cfg.tick_sleep_seconds == 0.75


def test_watcher_config_ignores_dev_knobs_in_operator_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    initialize_test_vault(tmp_path)
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "operator")
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "1")
    monkeypatch.setenv("WATCHER_RATE_LIMIT_PER_MIN", "2")
    monkeypatch.setenv("WATCHER_BACKOFF_SECONDS", "3")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.5")

    cfg = WatcherConfig.from_env()
    assert cfg.debounce_ms == 1500
    assert cfg.rate_limit_per_min == 30
    assert cfg.backoff_seconds == 10
    assert cfg.tick_sleep_seconds == 1.0


def test_watcher_config_honors_dev_knobs_in_lab_profile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    initialize_test_vault(tmp_path)
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(tmp_path))
    monkeypatch.setenv("WATCHER_DEBOUNCE_MS", "1")
    monkeypatch.setenv("WATCHER_RATE_LIMIT_PER_MIN", "2")
    monkeypatch.setenv("WATCHER_BACKOFF_SECONDS", "3")
    monkeypatch.setenv("WATCHER_TICK_SLEEP_SECONDS", "0.5")

    cfg = WatcherConfig.from_env()
    assert cfg.debounce_ms == 1
    assert cfg.rate_limit_per_min == 2
    assert cfg.backoff_seconds == 3
    assert cfg.tick_sleep_seconds == 0.5


def test_watcher_tunables_reach_startup_and_reload_from_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = initialize_test_vault(tmp_path / "vault")
    (vault / "settings" / "watcher_and_tuning.md").write_text(
        "# Watcher and tuning\n\n```yaml settings\n"
        "debounce_ms: 125\nrate_limit_per_min: 7\nbackoff_seconds: 3\n"
        "tick_sleep_seconds: 0.25\nconnect_relatedness_floor: 0.45\n"
        "contradiction_floor: 0.3\n```\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(compiler, "RUNTIME", tmp_path / "runtime" / "settings")
    bundle = compiler.compile_all(vault_root=vault)
    callbacks = []
    monkeypatch.setattr("app.watcher.config.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr(
        "app.watcher.config.subscribe_settings", lambda callback, *, replay: callbacks.append(callback)
    )
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    monkeypatch.delenv("WATCHER_DEBOUNCE_MS", raising=False)

    cfg = WatcherConfig.from_env()

    assert (cfg.debounce_ms, cfg.rate_limit_per_min, cfg.backoff_seconds, cfg.tick_sleep_seconds) == (
        125,
        7,
        3,
        0.25,
    )

    reloaded = SettingsBundle(
        watcher_and_tuning=WatcherAndTuningSettings(
            debounce_ms=220,
            rate_limit_per_min=11,
            backoff_seconds=4,
            tick_sleep_seconds=0.5,
        )
    )
    monkeypatch.setattr("app.watcher.config.get_settings_bundle", lambda: reloaded)
    assert len(callbacks) == 1
    callbacks[0](reloaded)

    assert (cfg.debounce_ms, cfg.rate_limit_per_min, cfg.backoff_seconds, cfg.tick_sleep_seconds) == (
        220,
        11,
        4,
        0.5,
    )


def test_one_shot_ingests_selected_vault_before_tunable_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    vault = initialize_test_vault(tmp_path / "vault")
    events: list[str] = []
    monkeypatch.setenv("PKM_SETTINGS_PROFILE", "lab")
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    monkeypatch.setattr(
        "app.watcher.config.ingest_settings",
        lambda **kwargs: (
            events.append(f"ingest:{kwargs['vault_root']}")
            or SettingsIngestionState(state="ok", source="vault")
        ),
    )
    monkeypatch.setattr(
        "app.watcher.config.get_settings_bundle",
        lambda: events.append("resolve") or SettingsBundle(),
    )
    monkeypatch.setattr(
        "app.watcher.config.subscribe_settings", lambda callback, *, replay: None
    )

    WatcherConfig.from_env(ingest_selected_vault=True)

    assert events[0] == f"ingest:{vault}"
    assert "resolve" in events[1:]
