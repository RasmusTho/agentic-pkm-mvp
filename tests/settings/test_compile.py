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
    assert bundle.global_.note_moves_enable is False
    assert bundle.providers.llm["default_chat"].model == "llama3.1:8b"
    assert {"classifier", "promotion", "reviewer", "qa"}.issubset(bundle.agents.keys())
    promo = bundle.agents["promotion"]
    assert promo.move_policy.enabled is True
    assert bundle.agents["reviewer"].rules.min_score >= 0.75

    global_yaml = yaml.safe_load((runtime_dir / "global.yaml").read_text())
    assert global_yaml["timeout_ms"] == 8000
    assert global_yaml["note_moves_enable"] is False
    assert global_yaml["secrets"]["telemetry_token"] == "test-token"
    assert (runtime_dir / "agents" / "qa.yaml").exists()
    assert (runtime_dir / "agents" / "reviewer.yaml").exists()

    assert captured and "sha" in captured[0]
    bus.clear("settings.changed")


def test_compile_removes_stale_agent_yaml(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime/settings"
    stale_file = runtime_dir / "agents/ghost.yaml"
    stale_file.parent.mkdir(parents=True, exist_ok=True)
    stale_file.write_text("ghost: true\n", encoding="utf-8")

    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)

    compiler.compile_all()

    assert not stale_file.exists()
