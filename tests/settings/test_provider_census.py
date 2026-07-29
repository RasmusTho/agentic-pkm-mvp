from __future__ import annotations

from pathlib import Path
import re

import pytest

from app.components.embeddings.legacy import _supported_embed_providers
from app.components.llm.router import _KNOWN_PROVIDERS
from app.components.settings.models_loader import load_models
from app.components.settings.providers_loader import (
    ProviderProjectionDriftError,
    assert_provider_projection,
    load_provider_census,
)
from app.llm.adapter import _DISPATCH_PROVIDERS as ADAPTER_DISPATCH_PROVIDERS
from app.llm.embeddings import PROVIDER_REGISTRY
from app.services.llm import _DISPATCH_PROVIDERS as SERVICE_DISPATCH_PROVIDERS


def _census():
    return load_provider_census()


def test_census_loads_and_rejects_unknown_fields(tmp_path: Path) -> None:
    census = _census()
    assert {provider.id for provider in census.providers} == {
        "anthropic", "deepseek", "gemini", "mock", "ollama", "openai"
    }
    bad = tmp_path / "providers.yaml"
    bad.write_text("version: 1\nproviders: []\nruntime_channels: {}\nunexpected: true\n", encoding="utf-8")
    with pytest.raises(ValueError, match="extra_forbidden"):
        load_provider_census(bad)


@pytest.mark.parametrize(
    ("site", "actual"),
    [
        ("app/components/llm/router.py::_KNOWN_PROVIDERS", lambda: _KNOWN_PROVIDERS),
        ("app/components/embeddings/legacy.py::_SUPPORTED_EMBED_PROVIDERS", _supported_embed_providers),
        ("app/llm/embeddings.py::PROVIDER_REGISTRY", lambda: PROVIDER_REGISTRY),
        ("app/services/llm.py::_DISPATCH_PROVIDERS", lambda: SERVICE_DISPATCH_PROVIDERS),
        ("app/llm/adapter.py::_DISPATCH_PROVIDERS", lambda: ADAPTER_DISPATCH_PROVIDERS),
        ("app/cli/health.py::_check_llm_providers", lambda: {"mock", "ollama"}),
        ("docs/settings/models/registry.yaml::provider", lambda: {item.provider for item in load_models().values()}),
        (
            "docs/LLM.md::Providers (Current)",
            lambda: set(
                re.findall(
                    r"^- `([^`]+)`",
                    Path("docs/LLM.md").read_text(encoding="utf-8").split("## Core Environment Variables", 1)[0],
                    flags=re.MULTILINE,
                )
            ),
        ),
    ],
)
def test_all_allowlists_match_census(site: str, actual) -> None:
    assert_provider_projection(_census(), site, set(actual()))


def test_undeclared_or_unlinked_divergence_fails(tmp_path: Path) -> None:
    census = _census()
    assert census.known_divergences == []
    with pytest.raises(ProviderProjectionDriftError, match="app/components/llm/router.py::_KNOWN_PROVIDERS"):
        assert_provider_projection(
            census,
            "app/components/llm/router.py::_KNOWN_PROVIDERS",
            set(_KNOWN_PROVIDERS) | {"anthropic"},
        )
    source = Path("docs/settings/models/providers.yaml").read_text(encoding="utf-8")
    malformed_entries = [
        ("declared_on", "site: app/components/llm/router.py::_KNOWN_PROVIDERS\n    divergent_members: [anthropic]\n    issue: https://github.com/RasmusTho/agentic-pkm-mvp/issues/1"),
        ("issue", "site: app/components/llm/router.py::_KNOWN_PROVIDERS\n    divergent_members: [anthropic]\n    declared_on: '2026-07-29'"),
    ]
    for expected_error, entry in malformed_entries:
        malformed_path = tmp_path / f"provider-census-{expected_error}.yaml"
        malformed_path.write_text(source.replace("known_divergences: []", f"known_divergences:\n  - {entry}"), encoding="utf-8")
        with pytest.raises(ValueError, match=expected_error):
            load_provider_census(malformed_path)


def test_census_ships_no_stale_known_divergences() -> None:
    assert _census().known_divergences == []


def test_ladder_sites_dispatch_through_the_named_constant() -> None:
    assert SERVICE_DISPATCH_PROVIDERS == _census().projection("app/services/llm.py::_DISPATCH_PROVIDERS")
    assert ADAPTER_DISPATCH_PROVIDERS == _census().projection("app/llm/adapter.py::_DISPATCH_PROVIDERS")


def test_hot_paths_do_not_load_the_census_at_runtime() -> None:
    hot_paths = [
        Path("app/components/llm/router.py"),
        Path("app/components/embeddings/legacy.py"),
        Path("app/llm/embeddings.py"),
        Path("app/services/llm.py"),
        Path("app/llm/adapter.py"),
    ]
    assert all("providers_loader" not in path.read_text(encoding="utf-8") for path in hot_paths)


def _assert_mapping(census, mapping) -> None:
    provider = census.provider(mapping.provider)
    model = next(model for model in provider.models if model.id == mapping.model)
    for capability in mapping.requires:
        assert getattr(model.capabilities, capability) or getattr(provider.capabilities, capability)


def test_runtime_channel_tier_mappings_reference_capable_declared_models() -> None:
    census = _census()
    assert census.runtime_channels.product.keys() == census.runtime_channels.builder.keys() == {"dev", "test", "prod"}
    for runtime in (census.runtime_channels.product, census.runtime_channels.builder):
        for channels in runtime.values():
            for mapping in channels.values():
                _assert_mapping(census, mapping)


def test_model_inquiry_role_profiles_are_exact_distinct_and_provider_free() -> None:
    census = _census()
    expected = {
        "fable": ("anthropic", "claude-fable-5", "anthropic.api-key", {"structured_output", "system_prompt_channel"}),
        "gpt_codex": ("openai", "gpt-5.6-sol", "openai.api-key", {"structured_output"}),
    }
    for profiles in census.runtime_channels.model_inquiry_profiles.values():
        assert {profile.role for profile in profiles} == set(expected)
        targets = set()
        for profile in profiles:
            provider, model, credential, capabilities = expected[profile.role]
            assert (profile.provider, profile.model, profile.credential_identifier, profile.requires) == (provider, model, credential, capabilities)
            _assert_mapping(census, profile)
            declared = next(item for item in census.provider(profile.provider).models if item.id == profile.model)
            targets.add((profile.provider, profile.model, declared.effective_identity))
        assert len(targets) == 2
    assert census.runtime_channels.resolution_groups[0].independence == "distinct_effective_target"
    assert [group.id for group in census.runtime_channels.resolution_groups] == ["model-inquiry-independent-review"]
    assert all(profile.resolution_group == "model-inquiry-independent-review" for profiles in census.runtime_channels.model_inquiry_profiles.values() for profile in profiles)
    caller = Path("app/builderops/model_inquiry.py").read_text(encoding="utf-8")
    assert "claude-fable-5" not in caller
    assert "gpt-5.6-sol" not in caller
