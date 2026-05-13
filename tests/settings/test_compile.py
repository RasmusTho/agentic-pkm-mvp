from __future__ import annotations

import yaml
import pytest
from pathlib import Path


from app.events import bus
from app.settings import compiler

pytestmark = pytest.mark.not_pg


def test_compile_roundtrip_writes_artifacts(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime/settings"
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
    assert global_yaml["secrets"] == {}
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


def test_compile_includes_panel_and_watcher_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_dir = tmp_path / "runtime/settings"
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    compiler.compile_all()

    panel_yaml = yaml.safe_load((runtime_dir / "panel_actions.yaml").read_text())
    assert panel_yaml["paths"]
    assert any("panel-actions.md" in path for path in panel_yaml["paths"])
    assert panel_yaml["combined_sha"]
    assert panel_yaml["action_ids"]

    watchers_yaml = yaml.safe_load((runtime_dir / "watchers.yaml").read_text())
    assert watchers_yaml["allowed_actions"]
    assert watchers_yaml["auto_exec_env"] == "WATCHER_AUTO_EXEC"
    source = watchers_yaml["source"]
    assert source.get("path", "").endswith("watchers.md")
    assert source.get("sha256")


def test_compile_marks_missing_secret_placeholders_explicitly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    vault = tmp_path / "vault" / "@Settings"
    runtime_dir = tmp_path / "runtime" / "settings"
    vault.mkdir(parents=True, exist_ok=True)

    (vault / "global.md").write_text(
        "---\n"
        "uuid: global\n"
        "---\n"
        "## Runtime\n"
        "```yaml settings\n"
        "secrets:\n"
        "  api_token: ${SECRET:API_TOKEN}\n"
        "```\n",
        encoding="utf-8",
    )
    (vault / "providers.md").write_text(
        "---\n"
        "uuid: providers\n"
        "---\n"
        "## Providers\n"
        "```yaml settings\n"
        "llm: {}\n"
        "```\n",
        encoding="utf-8",
    )
    (vault / "llm_routing.md").write_text(
        "---\n"
        "uuid: routing\n"
        "---\n"
        "## Routing\n"
        "```yaml settings\n"
        "default_chat:\n"
        "  primary:\n"
        "    model_id: openai.chat.gpt_5_4_mini\n"
        "```\n",
        encoding="utf-8",
    )

    monkeypatch.delenv("API_TOKEN", raising=False)
    monkeypatch.setattr(compiler, "VAULT", vault)
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)

    bundle = compiler.compile_all(auto_heal=False)

    assert bundle.global_.secrets["api_token"] == "missing:API_TOKEN"
    global_yaml = yaml.safe_load((runtime_dir / "global.yaml").read_text(encoding="utf-8"))
    assert global_yaml["secrets"]["api_token"] == "missing:API_TOKEN"
