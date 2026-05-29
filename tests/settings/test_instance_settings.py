from __future__ import annotations

import yaml
import pytest

from app.settings import runtime

pytestmark = pytest.mark.not_pg


def _write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")


def _reset_runtime(monkeypatch, runtime_dir):
    monkeypatch.setattr(runtime, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "_SUBSCRIBERS", [])
    monkeypatch.setattr(runtime, "_CURRENT", None)


def test_default_instance_when_missing(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime/settings"
    _write_yaml(runtime_dir / "global.yaml", {})
    _write_yaml(runtime_dir / "providers.yaml", {})
    _reset_runtime(monkeypatch, runtime_dir)

    bundle = runtime.reload_settings_bundle(notify=False)

    assert bundle.instance.id == "home"
    assert bundle.instance.role == "master"


def test_instance_loaded_from_runtime_file(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime/settings"
    _write_yaml(runtime_dir / "global.yaml", {})
    _write_yaml(runtime_dir / "providers.yaml", {})
    _write_yaml(runtime_dir / "instance.yaml", {"id": "laptop", "role": "satellite"})
    _reset_runtime(monkeypatch, runtime_dir)

    bundle = runtime.reload_settings_bundle(notify=False)

    assert bundle.instance.id == "laptop"
    assert bundle.instance.role == "satellite"


def test_vault_settings_default_when_unset(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime/settings"
    _write_yaml(runtime_dir / "global.yaml", {})
    _write_yaml(runtime_dir / "providers.yaml", {})
    _reset_runtime(monkeypatch, runtime_dir)

    bundle = runtime.reload_settings_bundle(notify=False)

    assert bundle.instance.vault.name is None
    assert bundle.instance.vault.purpose is None


def test_vault_name_loaded_from_runtime_file(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime/settings"
    _write_yaml(runtime_dir / "global.yaml", {})
    _write_yaml(runtime_dir / "providers.yaml", {})
    _write_yaml(
        runtime_dir / "instance.yaml",
        {"id": "laptop", "vault": {"name": "Niflheim", "purpose": "personal"}},
    )
    _reset_runtime(monkeypatch, runtime_dir)

    bundle = runtime.reload_settings_bundle(notify=False)

    assert bundle.instance.vault.name == "Niflheim"
    assert bundle.instance.vault.purpose == "personal"


def test_vault_name_hot_reloads_without_restart(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime/settings"
    _write_yaml(runtime_dir / "global.yaml", {})
    _write_yaml(runtime_dir / "providers.yaml", {})
    instance_path = runtime_dir / "instance.yaml"
    _write_yaml(instance_path, {"vault": {"name": "Niflheim"}})
    _reset_runtime(monkeypatch, runtime_dir)

    first = runtime.reload_settings_bundle(notify=False)
    assert first.instance.vault.name == "Niflheim"

    # Operator renames/switches the vault on disk; a reload (the same path the
    # hot-reload watcher drives) picks it up with no process restart.
    _write_yaml(instance_path, {"vault": {"name": "Midgard"}})
    second = runtime.reload_settings_bundle(notify=False)
    assert second.instance.vault.name == "Midgard"
