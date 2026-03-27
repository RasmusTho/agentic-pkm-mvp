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
    _write_yaml(
        runtime_dir / "llm_routing.yaml",
        {"tasks": {"plan": {"primary": {"provider": "openai", "model": "gpt-plan"}}}},
    )
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


def test_runtime_loads_llm_routing_settings(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime/settings"
    _write_yaml(runtime_dir / "global.yaml", {})
    _write_yaml(runtime_dir / "providers.yaml", {})
    _write_yaml(
        runtime_dir / "llm_routing.yaml",
        {
            "default_chat": {
                "primary": {
                    "model_id": "openai.chat.gpt_5_4_mini",
                    "provider": "openai",
                    "model": "gpt-5.4-mini",
                },
                "fallback": {
                    "mode": "local",
                    "model_id": "ollama.chat.llama3_1_8b",
                    "provider": "ollama",
                    "model": "llama3.1:8b",
                },
            },
            "default_embedding": {
                "primary": {
                    "model_id": "ollama.embed.nomic_embed_text",
                    "provider": "ollama",
                    "model": "nomic-embed-text:latest",
                    "profile": "default",
                },
                "fallback": {"mode": "never"},
                "require_compatible_identity": True,
            },
        },
    )

    monkeypatch.setattr(runtime, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "_SUBSCRIBERS", [])
    monkeypatch.setattr(runtime, "_CURRENT", None)

    bundle = runtime.reload_settings_bundle(notify=False)

    assert bundle.llm_routing.default_chat.primary.provider == "openai"
    assert bundle.llm_routing.default_chat.primary.model_id == "openai.chat.gpt_5_4_mini"
    assert bundle.llm_routing.default_chat.fallback.mode == "local"
    assert bundle.llm_routing.default_embedding.require_compatible_identity is True
