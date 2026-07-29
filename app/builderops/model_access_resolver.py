"""Builder-owned resolution of neutral model-access intent through census policy.

This module is the Builder System's implementation of the neutral
``llm_contract.ModelAccessResolver`` port. Callers submit provider-free intent;
this resolver applies Builder policy, selects the target from the exact
declared provider census (MAS-01), verifies capabilities and grouped target
independence through the neutral kernel (MAS-04), and resolves credential
identities through the host secret contract (MAS-03).

Provider, model, effective identity, endpoint, and credential identifier are
outputs of this resolver. They are never caller fields and are never read from
ambient process environment.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.builderops.models import BuilderOpsValidationError
from app.components.settings.providers_loader import (
    ProviderCensus,
    ProviderEntry,
    RoleProfile,
    load_provider_census,
)
from app.ops.host_secret_bootstrap import (
    load_runtime_secret_values,
    validate_secret_value,
)
from app.ops.host_secret_contract import (
    HostSecretContract,
    UndeclaredSecretConsumerError,
    load_host_secret_contract,
)
from llm_contract import (
    ModelCapabilities,
    ModelResolutionRequest,
    ResolvedModelAccess,
    validate_resolved_group,
)


BUILDER_RUNTIME = "builder"
MODEL_INQUIRY_CONSUMER = "builderops-model-inquiry"
MODEL_INQUIRY_RESOLUTION_GROUP = "model-inquiry-independent-review"
NON_PROVIDER_IDENTITIES = frozenset({"mock", "fake", "deterministic", "test"})

_REPO_ROOT = Path(__file__).resolve().parents[2]
_PROVIDER_CENSUS_PATH = _REPO_ROOT / "docs" / "settings" / "models" / "providers.yaml"
_HOST_SECRET_CONTRACT_PATH = _REPO_ROOT / "config" / "secrets" / "host_secret_contract.json"

_CAPABILITY_FIELDS = (
    "structured_output",
    "native_tools",
    "system_prompt_channel",
    "deterministic_execution",
)


class ModelAccessResolutionError(BuilderOpsValidationError):
    """Builder policy refused to resolve a neutral request; no target was selected."""


class DeclaredCredentialUnavailableError(RuntimeError):
    """A declared credential is absent or unusable; names only the logical identifier."""

    def __init__(self, credential_identity_ref: str) -> None:
        super().__init__(f"declared credential unavailable: {credential_identity_ref}")
        self.credential_identity_ref = credential_identity_ref


@dataclass(frozen=True)
class BuilderModelAccessResolver:
    """Builder runtime resolver for the Model Inquiry independent-review group."""

    census: ProviderCensus
    contract: HostSecretContract
    env: Mapping[str, str] | None = None

    @classmethod
    def from_declared_sources(
        cls,
        *,
        env: Mapping[str, str] | None = None,
        census_path: Path | None = None,
        contract_path: Path | None = None,
    ) -> "BuilderModelAccessResolver":
        """Load the declared census and host secret contract from repository state."""
        try:
            census = load_provider_census(census_path or _PROVIDER_CENSUS_PATH)
            contract = load_host_secret_contract(contract_path or _HOST_SECRET_CONTRACT_PATH)
        except (OSError, ValueError) as exc:
            raise ModelAccessResolutionError(
                "declared model access sources are unavailable"
            ) from exc
        return cls(census=census, contract=contract, env=env)

    def resolve(
        self,
        request: ModelResolutionRequest,
        *,
        runtime: str,
        channel: str,
        consumer: str,
    ) -> ResolvedModelAccess:
        """Resolve one neutral role request into a validated Builder target."""
        return self.resolve_group(
            [request],
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
        """Resolve one caller-defined group and verify grouped target independence."""
        request_tuple = tuple(requests)
        if not request_tuple:
            raise ModelAccessResolutionError("resolution group must contain at least one request")
        self._require_builder_authority(runtime=runtime, consumer=consumer)
        profiles = self._channel_profiles(channel)
        resolutions = tuple(
            self._resolve_one(request, profiles=profiles, channel=channel, consumer=consumer)
            for request in request_tuple
        )
        try:
            validated = validate_resolved_group(request_tuple, resolutions)
        except ValueError as exc:
            raise ModelAccessResolutionError(str(exc)) from exc
        adapter_ids = [item.adapter_id for item in validated]
        if len(set(adapter_ids)) != len(adapter_ids):
            raise ModelAccessResolutionError(
                "resolved group requires distinct adapter_id values"
            )
        return validated

    def endpoint_for(self, resolved: ResolvedModelAccess) -> str:
        """Return the declared provider API endpoint for a resolved target."""
        provider = self._provider(resolved.provider)
        if not provider.api_endpoint:
            raise ModelAccessResolutionError(
                f"declared provider has no API endpoint: {resolved.provider}"
            )
        return provider.api_endpoint

    def credential_value(self, resolved: ResolvedModelAccess) -> str:
        """Resolve the declared credential value through the host secret contract.

        The value is read only from the mode-0600 runtime surface the host secret
        bootstrap materialized for this process. An absent, undeclared, or
        malformed value fails closed and names only the logical identifier.
        """
        secret = resolved.credential_identity_ref
        try:
            binding = self.contract.binding_for(secret)
            kind = self.contract.kind_for(secret)
        except UndeclaredSecretConsumerError as exc:
            raise DeclaredCredentialUnavailableError(secret) from exc
        values = load_runtime_secret_values(self.env)
        value = values.get(binding, "")
        if not value or not validate_secret_value(kind, value):
            raise DeclaredCredentialUnavailableError(secret)
        return value

    def _require_builder_authority(self, *, runtime: str, consumer: str) -> None:
        if runtime != BUILDER_RUNTIME:
            raise ModelAccessResolutionError(
                "Builder resolver refuses a non-Builder runtime request"
            )
        if consumer != MODEL_INQUIRY_CONSUMER:
            raise ModelAccessResolutionError(
                "Builder resolver refuses an undeclared model access consumer"
            )

    def _channel_profiles(self, channel: str) -> dict[str, RoleProfile]:
        profiles = self.census.runtime_channels.model_inquiry_profiles.get(channel)
        if not profiles:
            raise ModelAccessResolutionError(
                "declared census has no Model Inquiry profile for the requested channel"
            )
        by_role: dict[str, RoleProfile] = {}
        for profile in profiles:
            if profile.role in by_role:
                raise ModelAccessResolutionError(
                    "declared census repeats a Model Inquiry role profile"
                )
            by_role[profile.role] = profile
        return by_role

    def _resolve_one(
        self,
        request: ModelResolutionRequest,
        *,
        profiles: Mapping[str, RoleProfile],
        channel: str,
        consumer: str,
    ) -> ResolvedModelAccess:
        role = request.role_profile
        profile = profiles.get(role)
        if profile is None:
            raise ModelAccessResolutionError(
                f"declared census has no profile for role: {role}"
            )
        intent = request.intent
        if intent.fallback_requirement != "fallback_forbidden":
            raise ModelAccessResolutionError(
                "Builder Model Inquiry policy forbids any fallback requirement other than "
                "fallback_forbidden"
            )
        if intent.capability_tier != profile.capability_tier:
            raise ModelAccessResolutionError(
                "declared intent capability tier does not match the census role profile"
            )
        if request.resolution_group_id != profile.resolution_group:
            raise ModelAccessResolutionError(
                "declared intent resolution group does not match the census role profile"
            )
        group = next(
            (
                item
                for item in self.census.runtime_channels.resolution_groups
                if item.id == profile.resolution_group
            ),
            None,
        )
        if group is None:
            raise ModelAccessResolutionError(
                "declared census has no matching resolution group"
            )
        if intent.independence != group.independence:
            raise ModelAccessResolutionError(
                "declared intent independence does not match the census resolution group"
            )
        provider = self._provider(profile.provider)
        if provider.id.lower() in NON_PROVIDER_IDENTITIES or provider.tier == "test":
            raise ModelAccessResolutionError(
                "provider-enabled roles cannot resolve a mock identity"
            )
        model = next((item for item in provider.models if item.id == profile.model), None)
        if model is None:
            raise ModelAccessResolutionError(
                "declared census profile references an undeclared model"
            )
        capabilities = self._capabilities(provider, model.capabilities)
        missing = sorted(
            capability
            for capability in profile.requires
            if not getattr(capabilities, capability)
        )
        if missing:
            raise ModelAccessResolutionError(
                "declared target does not satisfy census-required capabilities: "
                + ", ".join(missing)
            )
        credential = self._credential_identity(
            profile,
            provider,
            role=role,
            channel=channel,
            consumer=consumer,
        )
        try:
            return ResolvedModelAccess(
                request=request,
                provider=provider.id,
                model=model.id,
                adapter_id=f"{provider.id}-{model.id}",
                effective_identity=model.effective_identity,
                capabilities=capabilities,
                credential_identity_ref=credential,
            )
        except ValueError as exc:
            raise ModelAccessResolutionError(str(exc)) from exc

    def _capabilities(self, provider: ProviderEntry, model_capabilities: object) -> ModelCapabilities:
        resolved = {
            field: bool(
                getattr(model_capabilities, field) or getattr(provider.capabilities, field)
            )
            for field in _CAPABILITY_FIELDS
        }
        dimension = getattr(model_capabilities, "embedding_dimensions", None) or getattr(
            provider.capabilities, "embedding_dimensions", None
        )
        return ModelCapabilities(**resolved, embedding_dimension=dimension)

    def _credential_identity(
        self,
        profile: RoleProfile,
        provider: ProviderEntry,
        *,
        role: str,
        channel: str,
        consumer: str,
    ) -> str:
        credential = profile.credential_identifier
        if credential not in provider.credential_identifiers:
            raise ModelAccessResolutionError(
                "declared census role profile uses an undeclared provider credential"
            )
        try:
            required = self.contract.required_secrets_for_role(consumer=consumer, role=role)
            self.contract.require_declared(
                channel=channel,
                consumer=consumer,
                secret=credential,
            )
        except UndeclaredSecretConsumerError as exc:
            raise ModelAccessResolutionError(
                "host secret contract does not declare this role credential"
            ) from exc
        if required != (credential,):
            raise ModelAccessResolutionError(
                "host secret contract role requirement does not match the census credential"
            )
        return credential

    def _provider(self, provider_id: str) -> ProviderEntry:
        try:
            return self.census.provider(provider_id)
        except KeyError as exc:
            raise ModelAccessResolutionError(
                f"declared census has no provider: {provider_id}"
            ) from exc


__all__ = [
    "BUILDER_RUNTIME",
    "MODEL_INQUIRY_CONSUMER",
    "MODEL_INQUIRY_RESOLUTION_GROUP",
    "BuilderModelAccessResolver",
    "DeclaredCredentialUnavailableError",
    "ModelAccessResolutionError",
]
