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
