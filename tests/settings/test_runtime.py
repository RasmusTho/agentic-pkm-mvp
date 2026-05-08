from __future__ import annotations

import yaml
import pytest

from app.events import bus
from app.settings import runtime
from app.settings.models import EmbeddingProfiles

pytestmark = pytest.mark.not_pg


def _write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=True), encoding="utf-8")


def _reset_runtime(monkeypatch, runtime_dir):
    monkeypatch.setattr(runtime, "RUNTIME", runtime_dir)
    monkeypatch.setattr(runtime, "_SUBSCRIBERS", [])
    monkeypatch.setattr(runtime, "_CURRENT", None)


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

    _reset_runtime(monkeypatch, runtime_dir)

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

    _reset_runtime(monkeypatch, runtime_dir)

    bundle = runtime.reload_settings_bundle(notify=False)

    assert bundle.llm_routing.default_chat.primary.provider == "openai"
    assert bundle.llm_routing.default_chat.primary.model_id == "openai.chat.gpt_5_4_mini"
    assert bundle.llm_routing.default_chat.fallback.mode == "local"
    assert bundle.llm_routing.default_embedding.require_compatible_identity is True


def test_runtime_defaults_invalid_optional_compiled_settings(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime/settings"
    _write_yaml(runtime_dir / "global.yaml", {})
    _write_yaml(runtime_dir / "providers.yaml", {})
    _write_yaml(runtime_dir / "llm_routing.yaml", {})
    _write_yaml(runtime_dir / "embeddings.yaml", {"profiles": {"default": {"dim": "invalid"}}})
    _write_yaml(runtime_dir / "instance.yaml", {"id": "laptop", "role": "invalid"})
    _write_yaml(runtime_dir / "yggdrasil.yaml", {"yggdrasil_root": "/tmp/ygg", "mimer_root": ["invalid"]})

    _reset_runtime(monkeypatch, runtime_dir)

    bundle = runtime.reload_settings_bundle(notify=False)

    assert bundle.embedding_profiles == EmbeddingProfiles()
    assert bundle.instance.id == "home"
    assert bundle.instance.role == "master"
    assert bundle.yggdrasil_paths is None


def test_hot_reload_keeps_last_good_bundle_on_invalid_update(tmp_path, monkeypatch):
    runtime_dir = tmp_path / "runtime/settings"
    _write_yaml(runtime_dir / "global.yaml", {"log_level": "INFO"})
    _write_yaml(runtime_dir / "providers.yaml", {})
    _write_yaml(
        runtime_dir / "llm_routing.yaml",
        {"default_chat": {"primary": {"provider": "openai", "model": "gpt-5.4-mini"}}},
    )

    _reset_runtime(monkeypatch, runtime_dir)
    bus.clear("settings.changed")
    bus.subscribe("settings.changed", runtime._handle_hot_reload)

    runtime.reload_settings_bundle(notify=False)
    before = runtime.get_settings_bundle()

    seen: list[str] = []
    runtime.subscribe_settings(lambda bundle: seen.append(bundle.global_.log_level), replay=False)

    _write_yaml(runtime_dir / "llm_routing.yaml", {"default_chat": {"primary": "invalid"}})
    bus.emit("settings.changed", {"sha": "bad-update"})

    after = runtime.get_settings_bundle()
    assert after.global_.log_level == before.global_.log_level
    assert after.llm_routing.default_chat.primary.provider == before.llm_routing.default_chat.primary.provider
    assert seen == []
