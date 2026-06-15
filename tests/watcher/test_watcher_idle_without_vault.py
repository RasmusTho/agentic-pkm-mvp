"""#2005 — the watcher idles (does not fail-exit) when there is no usable vault.

This flips the #1991 hard precondition (watcher raises on an absent/uninitialized
vault) into an idle-until-opened posture — the symmetric reverse of an invariant,
governed by the #1997 F4 rule. The validators and the `from_env` builders are
producers of that invariant and are updated together with this contract.

Three legs:
  * no vault bound          -> idle (build a disabled runtime, no raise)
  * uninitialized vault     -> idle (no raise)
  * set-but-missing vault   -> still fails loud (regression guard)

These tests are pure: no Docker, no network, no real watcher loop.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.vault.manager import VaultManager
from app.watcher import config as watcher_config
from app.watcher import registry as watcher_registry

pytestmark = pytest.mark.not_pg


_WATCHER_ENV_VARS = (
    "WATCHER_ENABLE",
    "WATCHER_VAULT_PATH",
    "WATCHER_SCOPE_GLOB",
    "VAULT_ROOT",
)


def _clear_watcher_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _WATCHER_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_watcher_idles_when_no_vault(monkeypatch: pytest.MonkeyPatch) -> None:
    """No vault bound: the watcher config builds an idle (disabled) runtime.

    With WATCHER_ENABLE=1 but no WATCHER_VAULT_PATH, the previous code raised
    `WATCHER_VAULT_PATH is required`. The flip turns that into an idle posture:
    `from_env` returns a config with `enable=False` so the run loop short-circuits
    and nothing is scanned or indexed.
    """
    _clear_watcher_env(monkeypatch)
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    # WATCHER_VAULT_PATH intentionally unset -> no vault bound.

    cfg = watcher_config.WatcherConfig.from_env()
    assert cfg.enable is False

    # The registry builder mirrors the same idle posture.
    specs = [
        watcher_registry.WatcherSpec(
            name="inbox",
            scope_glob="**/*.md",
            debounce_ms=1000,
            rate_limit_per_min=60,
            emit_event="ingest.vault.changed",
        )
    ]
    reg_cfg = watcher_registry.RegistryConfig.from_env(
        specs, config_path=Path("config/watchers.yaml")
    )
    assert reg_cfg.enable is False


def test_uninitialized_vault_idles_not_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An uninitialized vault (exists, but no settings) idles instead of raising.

    Directly exercises both validators: each returns False (idle) for an
    `uninitialized` vault rather than raising the #1991 fail-exit, and `from_env`
    propagates that into `enable=False`.
    """
    _clear_watcher_env(monkeypatch)
    vault = tmp_path / "uninitialized-vault"
    vault.mkdir()  # exists, but has no settings files -> status "uninitialized"

    # Validators idle (return False), never raise.
    assert watcher_config._validate_watcher_vault(vault) is False
    assert watcher_registry._validate_registry_vault(vault) is False

    # from_env with the uninitialized vault bound -> idle (enable=False).
    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))

    cfg = watcher_config.WatcherConfig.from_env()
    assert cfg.enable is False

    specs = [
        watcher_registry.WatcherSpec(
            name="inbox",
            scope_glob="**/*.md",
            debounce_ms=1000,
            rate_limit_per_min=60,
            emit_event="ingest.vault.changed",
        )
    ]
    reg_cfg = watcher_registry.RegistryConfig.from_env(
        specs, config_path=Path("config/watchers.yaml")
    )
    assert reg_cfg.enable is False


def test_set_but_missing_still_fails_loud(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A *set-but-missing* vault path still fails loud — no regression.

    The idle flip only covers "no vault bound" and "uninitialized". A vault path
    that is explicitly bound but does not exist is a misconfiguration and must
    raise (status "missing"), mirroring the open-vault-on-missing-vault decision.
    """
    _clear_watcher_env(monkeypatch)
    missing = tmp_path / "this-path-does-not-exist"
    assert not missing.exists()

    with pytest.raises(ValueError):
        watcher_config._validate_watcher_vault(missing)
    with pytest.raises(ValueError):
        watcher_registry._validate_registry_vault(missing)

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(missing))
    with pytest.raises(ValueError):
        watcher_config.WatcherConfig.from_env()

    specs = [
        watcher_registry.WatcherSpec(
            name="inbox",
            scope_glob="**/*.md",
            debounce_ms=1000,
            rate_limit_per_min=60,
            emit_event="ingest.vault.changed",
        )
    ]
    with pytest.raises(ValueError):
        watcher_registry.RegistryConfig.from_env(
            specs, config_path=Path("config/watchers.yaml")
        )


def test_selected_vault_still_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Sanity: a properly initialized (selected) vault still enables the watcher."""
    _clear_watcher_env(monkeypatch)
    vault = tmp_path / "selected-vault"
    VaultManager().initialize_vault(vault, remember=False)

    assert watcher_config._validate_watcher_vault(vault) is True
    assert watcher_registry._validate_registry_vault(vault) is True

    monkeypatch.setenv("WATCHER_ENABLE", "1")
    monkeypatch.setenv("WATCHER_VAULT_PATH", str(vault))
    cfg = watcher_config.WatcherConfig.from_env()
    assert cfg.enable is True
    assert os.fspath(cfg.vault_path) == os.fspath(vault)
