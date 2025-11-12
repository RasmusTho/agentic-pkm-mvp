from __future__ import annotations

import yaml
import pytest

from app.events import bus
from app.settings import compiler

pytestmark = pytest.mark.not_pg


def test_compile_roundtrip_writes_artifacts(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime/settings"
    monkeypatch.setenv("OTEL_TOKEN", "test-token")
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    bus.clear("settings.changed")
    captured = []
    bus.subscribe("settings.changed", lambda payload: captured.append(payload))

    bundle = compiler.compile_all()

    assert bundle.global_.enable is True
    assert bundle.providers.llm["default_chat"].model == "llama3.1:8b"
    assert "classifier" in bundle.agents

    global_yaml = yaml.safe_load((runtime_dir / "global.yaml").read_text())
    assert global_yaml["timeout_ms"] == 8000
    assert global_yaml["secrets"]["telemetry_token"] == "test-token"

    assert captured and "sha" in captured[0]
    bus.clear("settings.changed")
