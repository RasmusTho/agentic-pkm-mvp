from __future__ import annotations

import yaml
import pytest

from app.settings import runtime
from app.settings.models import QaSettings

pytestmark = pytest.mark.not_pg


def _write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")


def test_runtime_subscriber_gets_updates(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime/settings"
    agents_dir = runtime_dir / "agents"
    _write_yaml(runtime_dir / "global.yaml", {"log_level": "DEBUG"})
    _write_yaml(runtime_dir / "providers.yaml", {})
    _write_yaml(agents_dir / "qa.yaml", {"llm": {"provider": "mock"}})

    monkeypatch.setattr(runtime, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "_SUBSCRIBERS", [])
    monkeypatch.setattr(runtime, "_CURRENT", None)

    seen = []

    runtime.reload_settings_bundle(notify=False)
    runtime.subscribe_settings(lambda bundle: seen.append(bundle.global_.log_level))
    assert seen[-1] == "DEBUG"

    _write_yaml(runtime_dir / "global.yaml", {"log_level": "WARN"})
    runtime.reload_settings_bundle()
    assert seen[-1] == "WARN"
