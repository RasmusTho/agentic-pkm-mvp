"""Compile-time validation for clone-selectable Product routing profiles."""

from __future__ import annotations

import pytest
import yaml

from app.settings import compiler
from app.settings.compiler import _resolve_llm_routing_model_ids
from app.settings.models import LLMRoutingSettings
from app.vault.manager import VaultManager

pytestmark = pytest.mark.not_pg


def test_profile_model_ids_resolve_from_registry() -> None:
    resolved = _resolve_llm_routing_model_ids(
        {
            "profiles": {
                "work": {
                    "default_chat": {"model_id": "openai.chat.gpt_6_luna"},
                    "tasks": {
                        "plan": {"model_id": "openai.chat.gpt_6_luna"},
                    },
                }
            }
        }
    )

    profile = LLMRoutingSettings(**resolved).profiles["work"]
    assert profile.default_chat is not None
    assert (profile.default_chat.provider, profile.default_chat.model) == (
        "openai",
        "gpt-6-luna",
    )
    assert (profile.tasks["plan"].provider, profile.tasks["plan"].model) == (
        "openai",
        "gpt-6-luna",
    )


def test_profile_rejects_embedding_model_id() -> None:
    with pytest.raises(ValueError, match="expected kind=chat"):
        _resolve_llm_routing_model_ids(
            {
                "profiles": {
                    "work": {
                        "default_chat": {"model_id": "ollama.embed.nomic_embed_text"}
                    }
                }
            }
        )


def test_profile_requires_registry_model_id() -> None:
    with pytest.raises(ValueError, match="must select a registry model_id"):
        _resolve_llm_routing_model_ids(
            {
                "profiles": {
                    "work": {
                        "default_chat": {
                            "provider": "openai",
                            "model": "free-form",
                        }
                    }
                }
            }
        )


def test_profile_rejects_embedding_override_field() -> None:
    with pytest.raises(ValueError):
        LLMRoutingSettings(
            profiles={
                "work": {
                    "default_embedding": {
                        "model_id": "ollama.embed.nomic_embed_text",
                    }
                }
            }
        )


def test_clone_local_profile_is_compiled_into_instance_runtime(tmp_path, monkeypatch) -> None:
    vault_root = tmp_path / "satellite-vault"
    VaultManager().initialize_vault(vault_root, remember=False, machine_role="satellite")
    local_settings = vault_root / "settings" / "local.md"
    local_settings.write_text(
        "---\n"
        "schema: design-handoff.local.v1\n"
        "scope: vault-local\n"
        "localInstanceId: satellite-test\n"
        "machineRole: satellite\n"
        "llmRoutingProfile: work\n"
        "---\n"
        "# Local settings\n",
        encoding="utf-8",
    )
    runtime_dir = tmp_path / "runtime" / "settings"
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)

    bundle = compiler.compile_all(vault_root=vault_root, auto_heal=False)

    assert bundle.instance.llm_routing_profile == "work"
    assert yaml.safe_load((runtime_dir / "instance.yaml").read_text(encoding="utf-8"))[
        "llm_routing_profile"
    ] == "work"
