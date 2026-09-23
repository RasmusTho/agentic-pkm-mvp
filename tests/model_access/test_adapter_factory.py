from __future__ import annotations

import pytest

from app.model_access.adapter_factory import (
    AdapterRegistryError,
    ModelAccessAdapterFactory,
    SUPPORTED_ADAPTER_IDS,
)


@pytest.fixture
def factory() -> ModelAccessAdapterFactory:
    return ModelAccessAdapterFactory.from_declared_sources()


def test_factory_resolves_only_declared_adapter_ids(
    factory: ModelAccessAdapterFactory,
) -> None:
    targets = {
        "codex_cli": ("openai", "gpt-5.6-luna"),
        "ollama_http": ("ollama", "llama3.1:8b"),
        "openai_api": ("openai", "gpt-5.6-sol"),
        "anthropic_api": ("anthropic", "claude-fable-5"),
        "deepseek_api": ("deepseek", "deepseek-chat"),
        "mock": ("mock", "mock-chat"),
    }

    assert set(targets) == SUPPORTED_ADAPTER_IDS
    for adapter_id, (provider, model) in targets.items():
        descriptor = factory.describe(adapter_id, provider=provider, model=model)
        assert descriptor.adapter_id == adapter_id
        assert (descriptor.provider, descriptor.model) == (provider, model)
        assert descriptor.transport_id == adapter_id

    with pytest.raises(AdapterRegistryError, match="not declared"):
        factory.describe("undeclared", provider="openai", model="gpt-5.6-sol")
    with pytest.raises(AdapterRegistryError, match="resolved provider"):
        factory.describe("openai_api", provider="anthropic", model="claude-fable-5")
    with pytest.raises(AdapterRegistryError, match="not declared for this provider"):
        factory.describe("openai_api", provider="openai", model="missing-model")


def test_deepseek_route_remains_available_from_declared_provider_config(
    factory: ModelAccessAdapterFactory,
) -> None:
    descriptor = factory.describe(
        "deepseek_api", provider="deepseek", model="deepseek-chat"
    )

    assert descriptor.transport_id == "deepseek_api"
    assert descriptor.authentication_scheme == "provider_credential_ref"
    assert descriptor.execution_boundary == "provider_https"
    assert descriptor.supported_capabilities.native_tools is False


def test_codex_adapter_capability_maximum_never_inherits_native_tools(
    factory: ModelAccessAdapterFactory,
) -> None:
    descriptor = factory.describe(
        "codex_cli", provider="openai", model="gpt-5.6-luna"
    )

    assert descriptor.supported_capabilities.native_tools is False
    assert descriptor.transport_id == "codex_cli"
