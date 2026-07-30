"""Provider-free design-agent registry above the shared model-access substrate.

The registry owns domain identities and sanitized availability only. Provider,
model, credential reference, and effective identity are resolver outputs, while
execution is delegated to an already-constructed ``ModelTurnAdapter``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from app.builderops.design_run_contract import (
    DesignAgentAvailabilityDescriptor,
    DesignDeliverableKind,
    is_safe_design_run_identifier,
)
from app.builderops.model_access_resolver import (
    BUILDER_RUNTIME,
    DESIGN_AGENT_CONSUMER,
    BuilderModelAccessResolver,
)
from llm_contract import (
    AdapterResult,
    IndependenceRequirement,
    ModelAccessIntent,
    ModelAccessResolver,
    ModelCapabilityRequirements,
    ModelResolutionRequest,
    ModelTurnAdapter,
    ResolvedModelAccess,
)

DESIGN_AGENT_IDS: Final = (
    "claude-design-via-claude-code",
    "codex",
    "fable",
)
DESIGN_AGENT_ROLE_PROFILES: Final = {
    "claude-design-via-claude-code": "design.claude",
    "codex": "design.codex",
    "fable": "design.fable",
}
DESIGN_AGENT_CONSUMER_ID: Final = DESIGN_AGENT_CONSUMER
_SUPPORTED_DELIVERABLES: Final[tuple[DesignDeliverableKind, ...]] = (
    "content_review",
    "interaction_specification",
    "visual_handoff",
)
_DISPLAY_NAMES: Final = {
    "claude-design-via-claude-code": "Claude Design via Claude Code",
    "codex": "Codex",
    "fable": "Fable",
}
_OUTPUT_SCHEMA_REF: Final = "builderops.design-agent-turn.v1"
_SIDE_EFFECT_CLASS: Final = "builder_design_material"
_INTERACTIVE_SUBSCRIPTION_ONLY: Final = frozenset(
    {"claude-design-via-claude-code"}
)
_LIMITATION_DETAIL: Final = {
    "model_access_unavailable": (
        "Shared model access could not resolve this design agent for headless use."
    ),
    "headless_adapter_unavailable": (
        "No headless model-turn adapter is registered for this resolved target."
    ),
    "adapter_identity_mismatch": (
        "The registered model-turn adapter does not match the resolved target."
    ),
    "interactive_subscription_only": (
        "This design-agent route is interactive-only and unavailable to headless runs."
    ),
}


class UnknownDesignAgentError(ValueError):
    """The requested domain adapter is not one of the exact registered IDs."""

    def __init__(self) -> None:
        super().__init__("unknown design agent")


class DesignAgentUnavailableError(RuntimeError):
    """The exact requested route is unavailable; no alternative is selected."""

    def __init__(self, design_agent_id: str) -> None:
        super().__init__(f"design agent unavailable: {design_agent_id}")
        self.design_agent_id = design_agent_id


@dataclass(frozen=True)
class ResolvedDesignAgentAdapter:
    """One exact domain selection backed by the shared neutral adapter port."""

    design_agent_id: str
    descriptor: DesignAgentAvailabilityDescriptor
    model_turn_adapter: ModelTurnAdapter

    def execute(self, request: Mapping[str, Any]) -> AdapterResult:
        return self.model_turn_adapter.execute(request)


@dataclass(frozen=True)
class DesignAgentAdapterRegistry:
    """Resolve exact design-agent selections without ranking or fallback."""

    resolver: ModelAccessResolver
    model_turn_adapters: Mapping[str, ModelTurnAdapter]
    channel: str
    runtime: str = BUILDER_RUNTIME
    consumer: str = DESIGN_AGENT_CONSUMER

    @classmethod
    def from_declared_sources(
        cls,
        *,
        channel: str,
        model_turn_adapters: Mapping[str, ModelTurnAdapter] | None = None,
    ) -> "DesignAgentAdapterRegistry":
        """Build the production registry from repo-declared Builder sources.

        An empty adapter map is the honest shipped state while metered
        credentials remain intentionally unprovisioned. This path resolves
        identity and capabilities but performs no credential read or provider
        call and never reuses the Model Inquiry subscription session.
        """

        return cls(
            resolver=BuilderModelAccessResolver.from_declared_sources(),
            model_turn_adapters={} if model_turn_adapters is None else model_turn_adapters,
            channel=channel,
        )

    def descriptors(
        self,
        *,
        run_id: str,
    ) -> tuple[DesignAgentAvailabilityDescriptor, ...]:
        """Return all exact registrations as sanitized CKM-facing DTOs."""

        if not is_safe_design_run_identifier(run_id):
            return tuple(
                self._descriptor(
                    design_agent_id,
                    available=False,
                    limitation_code="model_access_unavailable",
                )
                for design_agent_id in DESIGN_AGENT_IDS
            )
        descriptors: list[DesignAgentAvailabilityDescriptor] = []
        for design_agent_id in DESIGN_AGENT_IDS:
            try:
                resolution = self._resolve(
                    (design_agent_id,),
                    run_id=run_id,
                    independence="none",
                )[0]
                if design_agent_id in _INTERACTIVE_SUBSCRIPTION_ONLY:
                    descriptor = self._descriptor(
                        design_agent_id,
                        resolution=resolution,
                        available=False,
                        limitation_code="interactive_subscription_only",
                    )
                else:
                    adapter = self.model_turn_adapters.get(resolution.adapter_id)
                    if adapter is None:
                        descriptor = self._descriptor(
                            design_agent_id,
                            resolution=resolution,
                            available=False,
                            limitation_code="headless_adapter_unavailable",
                        )
                    elif not self._adapter_matches(adapter, resolution):
                        descriptor = self._descriptor(
                            design_agent_id,
                            resolution=resolution,
                            available=False,
                            limitation_code="adapter_identity_mismatch",
                        )
                    else:
                        descriptor = self._descriptor(
                            design_agent_id,
                            resolution=resolution,
                            available=True,
                        )
            except Exception:
                descriptor = self._descriptor(
                    design_agent_id,
                    available=False,
                    limitation_code="model_access_unavailable",
                )
            descriptors.append(descriptor)
        return tuple(descriptors)

    def select(
        self,
        design_agent_id: str,
        *,
        run_id: str,
    ) -> ResolvedDesignAgentAdapter:
        """Resolve one explicit selection through a one-request group."""

        return self.resolve_group((design_agent_id,), run_id=run_id)[0]

    def resolve_group(
        self,
        design_agent_ids: Sequence[str],
        *,
        run_id: str,
        independence: IndependenceRequirement = "none",
    ) -> tuple[ResolvedDesignAgentAdapter, ...]:
        """Resolve a typed group before obtaining or invoking any adapter."""

        selected_ids = tuple(design_agent_ids)
        if not selected_ids:
            raise ValueError("design-agent selection group must not be empty")
        if not is_safe_design_run_identifier(run_id):
            raise ValueError("invalid design-run identifier")
        if any(
            design_agent_id not in DESIGN_AGENT_ROLE_PROFILES
            for design_agent_id in selected_ids
        ):
            raise UnknownDesignAgentError
        try:
            resolutions = self._resolve(
                selected_ids,
                run_id=run_id,
                independence=independence,
            )
        except Exception:
            raise DesignAgentUnavailableError(selected_ids[0]) from None
        selected: list[ResolvedDesignAgentAdapter] = []
        for design_agent_id, resolution in zip(
            selected_ids,
            resolutions,
            strict=True,
        ):
            try:
                if design_agent_id in _INTERACTIVE_SUBSCRIPTION_ONLY:
                    raise DesignAgentUnavailableError(design_agent_id)
                adapter = self.model_turn_adapters.get(resolution.adapter_id)
                if adapter is None or not self._adapter_matches(adapter, resolution):
                    raise DesignAgentUnavailableError(design_agent_id)
                descriptor = self._descriptor(
                    design_agent_id,
                    resolution=resolution,
                    available=True,
                )
            except DesignAgentUnavailableError:
                raise
            except Exception:
                raise DesignAgentUnavailableError(design_agent_id) from None
            selected.append(
                ResolvedDesignAgentAdapter(
                    design_agent_id=design_agent_id,
                    descriptor=descriptor,
                    model_turn_adapter=adapter,
                )
            )
        return tuple(selected)

    def _resolve(
        self,
        design_agent_ids: tuple[str, ...],
        *,
        run_id: str,
        independence: IndependenceRequirement,
    ) -> tuple[ResolvedModelAccess, ...]:
        requests = tuple(
            self._request(
                design_agent_id,
                run_id=run_id,
                independence=independence,
            )
            for design_agent_id in design_agent_ids
        )
        return self.resolver.resolve_group(
            requests,
            runtime=self.runtime,
            channel=self.channel,
            consumer=self.consumer,
        )

    def _request(
        self,
        design_agent_id: str,
        *,
        run_id: str,
        independence: IndependenceRequirement,
    ) -> ModelResolutionRequest:
        role_profile = DESIGN_AGENT_ROLE_PROFILES.get(design_agent_id)
        if role_profile is None:
            raise UnknownDesignAgentError
        return ModelResolutionRequest(
            intent=ModelAccessIntent(
                capability_tier="frontier",
                reasoning_effort="high",
                determinism_required=False,
                output_schema_ref=_OUTPUT_SCHEMA_REF,
                independence=independence,
                fallback_requirement="fallback_forbidden",
                side_effect_class=_SIDE_EFFECT_CLASS,
            ),
            role_profile=role_profile,
            resolution_group_id=f"design-run:{run_id}",
            requirements=ModelCapabilityRequirements(
                structured_output=True,
                system_prompt_channel=True,
            ),
        )

    @staticmethod
    def _adapter_matches(
        adapter: ModelTurnAdapter,
        resolution: ResolvedModelAccess,
    ) -> bool:
        return (
            adapter.adapter_id == resolution.adapter_id
            and adapter.provider == resolution.provider
            and adapter.model == resolution.model
        )

    @staticmethod
    def _descriptor(
        design_agent_id: str,
        *,
        available: bool,
        resolution: ResolvedModelAccess | None = None,
        limitation_code: Literal[
            "model_access_unavailable",
            "headless_adapter_unavailable",
            "adapter_identity_mismatch",
            "interactive_subscription_only",
        ]
        | None = None,
    ) -> DesignAgentAvailabilityDescriptor:
        return DesignAgentAvailabilityDescriptor(
            design_agent_id=design_agent_id,
            display_name=_DISPLAY_NAMES[design_agent_id],
            role_profile_id=DESIGN_AGENT_ROLE_PROFILES[design_agent_id],
            supported_deliverables=_SUPPORTED_DELIVERABLES,
            available=available,
            provider_identity=resolution.provider if resolution else None,
            model_identity=resolution.model if resolution else None,
            effective_identity=resolution.effective_identity if resolution else None,
            capabilities=(
                tuple(
                    sorted(
                        capability
                        for capability in (
                            "deterministic_execution",
                            "native_tools",
                            "structured_output",
                            "system_prompt_channel",
                        )
                        if getattr(resolution.capabilities, capability)
                    )
                )
                if resolution
                else ()
            ),
            resolution_group_id=(
                resolution.request.resolution_group_id if resolution else None
            ),
            limitation_code=limitation_code,
            limitation_detail=(
                _LIMITATION_DETAIL[limitation_code]
                if limitation_code is not None
                else None
            ),
        )


__all__ = [
    "DESIGN_AGENT_CONSUMER_ID",
    "DESIGN_AGENT_IDS",
    "DESIGN_AGENT_ROLE_PROFILES",
    "DesignAgentAdapterRegistry",
    "DesignAgentUnavailableError",
    "ResolvedDesignAgentAdapter",
    "UnknownDesignAgentError",
]
