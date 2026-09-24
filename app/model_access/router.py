"""Policy-agnostic route composition above the neutral model-access contract."""

from __future__ import annotations

from llm_contract import (
    ModelAccessAdapterRegistry,
    ModelAccessProfile,
    ModelAccessResolver,
    ModelAccessRoute,
    ModelResolutionRequest,
    ResolvedModelAccess,
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
        resolver_result = resolver.resolve(
            request,
            runtime=profile.runtime,
            channel=profile.channel,
            consumer=profile.consumer,
        )
        if not isinstance(resolver_result, ResolvedModelAccess):
            raise TypeError("model access resolver must return ResolvedModelAccess")
        # `BaseModel.model_copy(update=...)` does not validate update values;
        # reconstruct at the facade boundary before even looking up an adapter.
        resolved = ResolvedModelAccess(**resolver_result.model_dump())
        validate_resolved_group((request,), (resolved,))

        descriptor = self._adapter_registry.describe(
            resolved.adapter_id,
            provider=resolved.provider,
            model=resolved.model,
        )
        if descriptor.adapter_id != resolved.adapter_id:
            raise ValueError("adapter registry descriptor does not match resolved adapter")
        if (descriptor.provider, descriptor.model) != (resolved.provider, resolved.model):
            raise ValueError("adapter registry identity does not match resolved target")
        resolved_capabilities = resolved.capabilities
        supported_capabilities = descriptor.supported_capabilities
        unsupported = [
            name
            for name in (
                "structured_output",
                "native_tools",
                "system_prompt_channel",
                "deterministic_execution",
            )
            if getattr(resolved_capabilities, name)
            and not getattr(supported_capabilities, name)
        ]
        if (
            resolved_capabilities.embedding_dimension is not None
            and resolved_capabilities.embedding_dimension
            != supported_capabilities.embedding_dimension
        ):
            unsupported.append("embedding_dimension")
        if unsupported:
            raise ValueError(
                "adapter descriptor does not attest resolved capabilities: "
                + ", ".join(unsupported)
            )

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
        )
