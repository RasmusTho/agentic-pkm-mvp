"""Compile-time validation for clone-selectable Product routing profiles."""

from __future__ import annotations

import pytest
import yaml

from app.settings import compiler
from app.settings.compiler import _resolve_llm_routing_model_ids
from app.settings.models import LLMRoutingSettings
from app.components.llm.router import LLMRouter, LLMTaskIntent
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


def test_profile_embedding_targets_resolve_from_registry() -> None:
    resolved = _resolve_llm_routing_model_ids(
        {
            "profiles": {
                "work": {
                    "default_embedding": {
                        "model_id": "gemini.embed.gemini_embedding_001",
                    },
                    "tasks": {
                        "embed": {"model_id": "ollama.embed.nomic_embed_text"},
                    },
                }
            }
        }
    )

    profile = LLMRoutingSettings(**resolved).profiles["work"]
    assert profile.default_embedding is not None
    assert (profile.default_embedding.provider, profile.default_embedding.model) == (
        "gemini",
        "gemini-embedding-001",
    )
    assert (profile.tasks["embed"].provider, profile.tasks["embed"].model) == (
        "ollama",
        "nomic-embed-text:latest",
    )


def test_profile_embedding_target_rejects_chat_model() -> None:
    with pytest.raises(ValueError, match="expected kind=embedding"):
        _resolve_llm_routing_model_ids(
            {
                "profiles": {
                    "work": {
                        "default_embedding": {
                            "model_id": "openai.chat.gpt_6_luna",
                        }
                    }
                }
            }
        )


def test_initialized_vault_default_profile_routes_luna_and_nomic(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_PROVIDER_ENFORCE", "0")
    monkeypatch.delenv("LLM_FORCE_PROVIDER", raising=False)
    monkeypatch.delenv("LLM_FORCE_MODEL", raising=False)
    vault_root = tmp_path / "fresh-vault"
    result = VaultManager().initialize_vault(vault_root, remember=False)
    assert "settings/llm_routing.md" in result.created_files

    runtime_dir = tmp_path / "runtime" / "settings"
    monkeypatch.setattr(compiler, "RUNTIME", runtime_dir)
    bundle = compiler.compile_all(vault_root=vault_root, auto_heal=False)

    chat = bundle.llm_routing.default_chat
    reasoning = bundle.llm_routing.default_reasoning
    embedding = bundle.llm_routing.default_embedding
    assert (chat.primary.model_id, chat.primary.provider, chat.primary.model) == (
        "openai.chat.gpt_6_luna",
        "openai",
        "gpt-6-luna",
    )
    assert (reasoning.primary.model_id, reasoning.primary.provider, reasoning.primary.model) == (
        "openai.chat.gpt_6_luna",
        "openai",
        "gpt-6-luna",
    )
    assert chat.fallback.mode == reasoning.fallback.mode == "never"
    router = LLMRouter(settings=bundle)
    for task_kind in ("ask", "qa", "decide", "plan"):
        route = router.route(LLMTaskIntent(task_kind=task_kind))
        assert (route.provider, route.model) == ("openai", "gpt-6-luna")
    assert (
        embedding.primary.model_id,
        embedding.primary.provider,
        embedding.primary.model,
        embedding.primary.profile,
    ) == (
        "ollama.embed.nomic_embed_text",
        "ollama",
        "nomic-embed-text:latest",
        "default",
    )
    assert embedding.fallback.mode == "never"
    assert embedding.require_compatible_identity is True


def test_initialize_vault_does_not_shadow_legacy_routing_policy(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    vault_root = tmp_path / "legacy-vault"
    legacy_path = vault_root / "@Settings" / "llm_routing.md"
    legacy_path.parent.mkdir(parents=True)
    legacy_policy = (
        "---\nscope: vault-shared\n---\n"
        "# Legacy owner routing policy\n\n"
        "```yaml settings\n"
        "default_chat:\n"
        "  primary:\n"
        "    model_id: openai.chat.gpt_5_6_sol\n"
        "```\n"
    )
    legacy_path.write_text(legacy_policy, encoding="utf-8")
    monkeypatch.setattr(compiler, "RUNTIME", tmp_path / "runtime" / "settings")

    result = VaultManager().initialize_vault(vault_root, remember=False)

    canonical_path = vault_root / "settings" / "llm_routing.md"
    assert not canonical_path.exists()
    assert legacy_path.read_text(encoding="utf-8") == legacy_policy
    assert "@Settings/llm_routing.md" in result.skipped_existing_files
    bundle = compiler.compile_all(vault_root=vault_root, auto_heal=False)
    assert bundle.llm_routing.default_chat.primary.model_id == "openai.chat.gpt_5_6_sol"
    route = LLMRouter(settings=bundle).route(LLMTaskIntent(task_kind="ask"))
    assert (route.provider, route.model) == ("openai", "gpt-5.6-sol")


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
