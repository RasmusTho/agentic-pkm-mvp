"""Policy-agnostic route composition above the neutral model-access contract."""

from __future__ import annotations

from llm_contract import (
    ModelAccessAdapterRegistry,
    ModelAccessProfile,
    ModelAccessResolver,
    ModelAccessRoute,
    ModelResolutionRequest,
    validate_resolved_group,
)


class ModelAccessRouter:
    """Bind an owner-selected target to its registered transport metadata.

    This facade never chooses a provider, model, fallback, credential, or policy.
    The caller supplies its own resolver and profile, and the adapter registry is
    used only for a read-only descriptor lookup; no model call is made here.
    """

    def __init__(self, *, adapter_registry: ModelAccessAdapterRegistry) -> None:
        self._adapter_registry = adapter_registry

    def resolve(
        self,
        request: ModelResolutionRequest,
        *,
        resolver: ModelAccessResolver,
        profile: ModelAccessProfile,
    ) -> ModelAccessRoute:
        resolved = resolver.resolve(
            request,
            runtime=profile.runtime,
            channel=profile.channel,
            consumer=profile.consumer,
        )
        validate_resolved_group((request,), (resolved,))

        descriptor = self._adapter_registry.describe(resolved.adapter_id)
        if descriptor.adapter_id != resolved.adapter_id:
            raise ValueError("adapter registry descriptor does not match resolved adapter")
        if (descriptor.provider, descriptor.model) != (resolved.provider, resolved.model):
            raise ValueError("adapter registry identity does not match resolved target")

        return ModelAccessRoute(
            **resolved.model_dump(),
            policy_profile=profile.profile_id,
            transport_id=descriptor.transport_id,
            catalog_snapshot_ref=profile.catalog_snapshot_ref,
            catalog_snapshot_hash=profile.catalog_snapshot_hash,
            execution_host_profile=descriptor.execution_host_profile,
            execution_boundary=descriptor.execution_boundary,
            authentication_scheme=descriptor.authentication_scheme,
            caller_profile=profile.caller_profile,
            capability_provenance=profile.capability_provenance,
            trusted_instruction_mapping=descriptor.trusted_instruction_mapping,
            fallback_provenance=profile.fallback_provenance,
        )
