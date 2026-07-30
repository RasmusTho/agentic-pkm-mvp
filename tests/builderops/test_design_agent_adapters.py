from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from app.builderops.design_agent_adapters import (
    DESIGN_AGENT_IDS,
    DESIGN_AGENT_ROLE_PROFILES,
    DesignAgentAdapterRegistry,
    DesignAgentUnavailableError,
    UnknownDesignAgentError,
)
from app.builderops.model_access_resolver import ModelAccessResolutionError
from app.ops.host_secret_contract import (
    UndeclaredSecretConsumerError,
    load_host_secret_contract,
)
from llm_contract import (
    AdapterResult,
    ModelCapabilities,
    ModelResolutionRequest,
    ResolvedModelAccess,
    validate_resolved_group,
)


@dataclass
class RecordingResolver:
    targets: Mapping[str, tuple[str, str, str]]
    calls: list[tuple[tuple[ModelResolutionRequest, ...], str, str, str]] = field(
        default_factory=list
    )

    def resolve(
        self,
        request: ModelResolutionRequest,
        *,
        runtime: str,
        channel: str,
        consumer: str,
    ) -> ResolvedModelAccess:
        return self.resolve_group(
            (request,),
            runtime=runtime,
            channel=channel,
            consumer=consumer,
        )[0]

    def resolve_group(
        self,
        requests: Sequence[ModelResolutionRequest],
        *,
        runtime: str,
        channel: str,
        consumer: str,
    ) -> tuple[ResolvedModelAccess, ...]:
        request_tuple = tuple(requests)
        self.calls.append((request_tuple, runtime, channel, consumer))
        resolutions = tuple(
            ResolvedModelAccess(
                request=request,
                provider=self.targets[request.role_profile][0],
                model=self.targets[request.role_profile][1],
                adapter_id=(
                    f"{self.targets[request.role_profile][0]}-"
                    f"{self.targets[request.role_profile][1]}"
                ),
                effective_identity=self.targets[request.role_profile][2],
                capabilities=ModelCapabilities(
                    structured_output=True,
                    system_prompt_channel=True,
                ),
                credential_identity_ref=(
                    f"{self.targets[request.role_profile][0]}.api-key"
                ),
            )
            for request in request_tuple
        )
        try:
            return validate_resolved_group(request_tuple, resolutions)
        except ValueError as exc:
            raise ModelAccessResolutionError(str(exc)) from exc


@dataclass
class RecordingAdapter:
    adapter_id: str
    provider: str
    model: str
    calls: list[dict[str, Any]] = field(default_factory=list)

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        self.calls.append(dict(request))
        return AdapterResult(response_text="bounded design output")


def _targets() -> dict[str, tuple[str, str, str]]:
    return {
        "design.codex": ("openai", "gpt-5.6-sol", "openai/gpt-5.6-sol"),
        "design.claude": (
            "anthropic",
            "claude-fable-5",
            "anthropic/claude-fable-5",
        ),
        "design.fable": (
            "anthropic",
            "claude-fable-5",
            "anthropic/claude-fable-5",
        ),
    }


def _adapters() -> dict[str, RecordingAdapter]:
    return {
        "openai-gpt-5.6-sol": RecordingAdapter(
            "openai-gpt-5.6-sol", "openai", "gpt-5.6-sol"
        ),
        "anthropic-claude-fable-5": RecordingAdapter(
            "anthropic-claude-fable-5", "anthropic", "claude-fable-5"
        ),
    }


def test_supported_design_adapters_conform_to_common_contract() -> None:
    production = DesignAgentAdapterRegistry.from_declared_sources(channel="dev")
    descriptors = production.descriptors(run_id="run.discovery")

    assert tuple(item.design_agent_id for item in descriptors) == DESIGN_AGENT_IDS
    assert DESIGN_AGENT_IDS == (
        "claude-design-via-claude-code",
        "codex",
        "fable",
    )
    assert {item.role_profile_id for item in descriptors} == {
        "design.claude",
        "design.codex",
        "design.fable",
    }
    assert all(item.supported_deliverables for item in descriptors)
    assert all(item.available is False for item in descriptors)
    assert all(item.provider_identity is None for item in descriptors)
    assert all(item.capabilities == () for item in descriptors)
    assert {
        item.design_agent_id: item.limitation_code for item in descriptors
    } == {
        "claude-design-via-claude-code": "interactive_subscription_only",
        "codex": "model_access_unavailable",
        "fable": "model_access_unavailable",
    }


def test_design_agents_use_the_shared_model_access_substrate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = load_host_secret_contract(
        Path("config/secrets/host_secret_contract.json")
    )
    for role in DESIGN_AGENT_ROLE_PROFILES.values():
        with pytest.raises(UndeclaredSecretConsumerError):
            contract.required_secrets_for_role(
                consumer="builderops-design-run",
                role=role,
            )

    def forbid_secret_read(*_args: object, **_kwargs: object) -> dict[str, str]:
        raise AssertionError("design registry must not read a credential binding")

    monkeypatch.setattr(
        "app.builderops.model_access_resolver.load_runtime_secret_values",
        forbid_secret_read,
    )
    production = DesignAgentAdapterRegistry.from_declared_sources(
        channel="dev",
        model_turn_adapters=_adapters(),
    )
    assert {
        descriptor.design_agent_id: descriptor.limitation_code
        for descriptor in production.descriptors(run_id="run.no-credential-grant")
    } == {
        "claude-design-via-claude-code": "interactive_subscription_only",
        "codex": "model_access_unavailable",
        "fable": "model_access_unavailable",
    }
    with pytest.raises(DesignAgentUnavailableError):
        production.select("codex", run_id="run.no-credential-read")

    resolver = RecordingResolver(_targets())
    adapters = _adapters()
    registry = DesignAgentAdapterRegistry(
        resolver=resolver,
        model_turn_adapters=adapters,
        channel="test",
    )

    selected = registry.select("codex", run_id="run.one")
    result = selected.execute({"brief_ref": "brief.one"})

    assert result.response_text == "bounded design output"
    assert adapters["openai-gpt-5.6-sol"].calls == [{"brief_ref": "brief.one"}]
    requests, runtime, channel, consumer = resolver.calls[0]
    assert (runtime, channel, consumer) == (
        "builder",
        "test",
        "builderops-design-run",
    )
    assert len(requests) == 1
    request = requests[0]
    assert request.role_profile == "design.codex"
    assert request.resolution_group_id == "design-run:run.one"
    assert set(request.intent.model_dump()) == {
        "capability_tier",
        "reasoning_effort",
        "determinism_required",
        "output_schema_ref",
        "independence",
        "fallback_requirement",
        "side_effect_class",
    }
    assert request.intent.fallback_requirement == "fallback_forbidden"
    source = Path("app/builderops/design_agent_adapters.py").read_text(
        encoding="utf-8"
    )
    assert all(
        forbidden not in source
        for forbidden in (
            "requests.",
            "subprocess",
            "credential_value(",
            "load_runtime_secret_values",
            "LocalCommandAdapter",
            "HttpModelAdapter",
        )
    )


def test_design_agents_use_grouped_builder_resolution_with_collision_refusal() -> None:
    resolver = RecordingResolver(_targets())
    adapters = _adapters()
    registry = DesignAgentAdapterRegistry(
        resolver=resolver,
        model_turn_adapters=adapters,
        channel="test",
    )

    with pytest.raises(DesignAgentUnavailableError):
        registry.resolve_group(
            ("claude-design-via-claude-code", "fable"),
            run_id="run.collision",
            independence="distinct_effective_target",
        )

    requests = resolver.calls[0][0]
    assert tuple(request.role_profile for request in requests) == (
        "design.claude",
        "design.fable",
    )
    assert {request.resolution_group_id for request in requests} == {
        "design-run:run.collision"
    }
    assert DESIGN_AGENT_ROLE_PROFILES == {
        "claude-design-via-claude-code": "design.claude",
        "codex": "design.codex",
        "fable": "design.fable",
    }
    assert all(not adapter.calls for adapter in adapters.values())


def test_descriptor_and_failure_surfaces_are_secret_safe() -> None:
    class ExplodingResolver(RecordingResolver):
        def resolve_group(
            self,
            requests: Sequence[ModelResolutionRequest],
            *,
            runtime: str,
            channel: str,
            consumer: str,
        ) -> tuple[ResolvedModelAccess, ...]:
            del requests, runtime, channel, consumer
            raise ModelAccessResolutionError(
                "Bearer secret-value from /Users/operator/private launcher command"
            )

    registry = DesignAgentAdapterRegistry(
        resolver=ExplodingResolver(_targets()),
        model_turn_adapters={},
        channel="test",
    )
    rendered = " ".join(
        descriptor.model_dump_json()
        for descriptor in registry.descriptors(run_id="run.secret-safe")
    ).lower()

    assert "secret-value" not in rendered
    assert "/users/" not in rendered
    assert "launcher" not in rendered
    assert "command" not in rendered
    assert "credential" not in rendered
    assert "retry" not in rendered
    assert "stderr" not in rendered
    with pytest.raises(DesignAgentUnavailableError) as resolver_failure:
        registry.select("codex", run_id="run.resolver-failure")
    assert str(resolver_failure.value) == "design agent unavailable: codex"

    resolver = RecordingResolver(_targets())
    adapters = _adapters()
    invalid_run_registry = DesignAgentAdapterRegistry(
        resolver=resolver,
        model_turn_adapters=adapters,
        channel="test",
    )
    invalid_run = " ".join(
        descriptor.model_dump_json()
        for descriptor in invalid_run_registry.descriptors(
            run_id="/Users/operator/private-launcher"
        )
    ).lower()
    assert "/users/" not in invalid_run
    assert "launcher" not in invalid_run
    assert resolver.calls == []
    assert all(not adapter.calls for adapter in adapters.values())

    class UnsafeIdentityResolver(RecordingResolver):
        def resolve_group(
            self,
            requests: Sequence[ModelResolutionRequest],
            *,
            runtime: str,
            channel: str,
            consumer: str,
        ) -> tuple[ResolvedModelAccess, ...]:
            del runtime, channel, consumer
            request = tuple(requests)[0]
            return (
                ResolvedModelAccess(
                    request=request,
                    provider="anthropic",
                    model="/Users/operator/private-launcher",
                    adapter_id="unsafe-adapter",
                    effective_identity="Bearer secret-value",
                    capabilities=ModelCapabilities(
                        structured_output=True,
                        system_prompt_channel=True,
                    ),
                    credential_identity_ref="anthropic.api-key",
                ),
            )

    unsafe_adapter = RecordingAdapter(
        "unsafe-adapter",
        "anthropic",
        "/Users/operator/private-launcher",
    )
    unsafe_registry = DesignAgentAdapterRegistry(
        resolver=UnsafeIdentityResolver(_targets()),
        model_turn_adapters={"unsafe-adapter": unsafe_adapter},
        channel="test",
    )
    unsafe_rendered = " ".join(
        descriptor.model_dump_json()
        for descriptor in unsafe_registry.descriptors(run_id="run.unsafe-identity")
    ).lower()
    assert "/users/" not in unsafe_rendered
    assert "secret-value" not in unsafe_rendered
    assert "launcher" not in unsafe_rendered
    assert unsafe_adapter.calls == []
    with pytest.raises(DesignAgentUnavailableError):
        unsafe_registry.select("codex", run_id="run.unsafe-selection")
    assert unsafe_adapter.calls == []


def test_unknown_or_unavailable_adapter_never_falls_back() -> None:
    resolver = RecordingResolver(_targets())
    adapters = _adapters()
    registry = DesignAgentAdapterRegistry(
        resolver=resolver,
        model_turn_adapters=adapters,
        channel="test",
    )

    with pytest.raises(UnknownDesignAgentError) as unknown:
        registry.select(
            "Bearer secret-value /Users/operator/private-launcher",
            run_id="run.unknown",
        )
    assert str(unknown.value) == "unknown design agent"
    assert resolver.calls == []

    with pytest.raises(ValueError, match="invalid design-run identifier"):
        registry.select("codex", run_id="/Users/operator/private-launcher")
    assert resolver.calls == []

    with pytest.raises(DesignAgentUnavailableError) as unavailable:
        registry.select(
            "claude-design-via-claude-code",
            run_id="run.unavailable",
        )
    assert unavailable.value.design_agent_id == "claude-design-via-claude-code"
    assert len(resolver.calls) == 1
    assert all(not adapter.calls for adapter in adapters.values())
