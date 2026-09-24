from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
import os
from typing import Any
from urllib.parse import urlsplit

from app.components.embeddings import EmbeddingClientProtocol, get_embedding_client
from app.components.llm.router import LLMRouteError, LLMRouter, LLMRoute, LLMTaskIntent
from app.components.settings.models_loader import load_models
from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.catalog import (
    CatalogCache,
    CatalogError,
    CatalogSelectionPolicy,
    select_latest_compatible,
)
from app.llm.preflight_fallback import select_preflight_route
from app.model_access.codex_remote_transport import CodexRemoteTransport
from app.model_access.remote_contract import (
    CatalogRequest,
    CompletionCapabilityIntent,
    CompletionRequest,
    CompletionRouteIdentity,
    PreflightRequest,
)
from app.model_access.router import ModelAccessRouter
from app.services.llm import LLMBackendTimeout, call_llm
from llm_contract import (
    CapabilityProvenance,
    FallbackProvenance,
    FallbackRequirement,
    ModelAccessIntent,
    ModelAccessProfile,
    ModelAccessRoute,
    ModelCapabilities,
    ModelCapabilityRequirements,
    ModelResolutionRequest,
    ResolvedModelAccess,
)


@lru_cache(maxsize=1)
def _adapter_factory() -> ModelAccessAdapterFactory:
    return ModelAccessAdapterFactory.from_declared_sources()


@dataclass(frozen=True)
class AdapterRuntimeConfig:
    """Ephemeral adapter settings; never part of route intent or provenance."""

    base_url: str | None = field(default=None, repr=False)
    api_key: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.base_url is None:
            return
        parsed = urlsplit(self.base_url.strip())
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "adapter base URL must be absolute HTTP(S) without embedded credentials"
            )


class _SelectedProductTarget:
    """Adapt Product's existing route decision to the neutral resolver port."""

    def __init__(self, selected: ResolvedModelAccess) -> None:
        self._selected = selected

    def resolve(self, request, *, runtime: str, channel: str, consumer: str):
        if request != self._selected.request:
            raise ValueError("Product resolver received an unexpected model request")
        return self._selected

    def resolve_group(self, requests, *, runtime: str, channel: str, consumer: str):
        if len(requests) != 1 or requests[0] != self._selected.request:
            raise ValueError("Product resolver only supports this one selected target")
        return (self._selected,)


def _credential_ref(authentication_scheme: str, provider: str) -> str:
    if authentication_scheme == "provider_credential_ref":
        return f"{provider}.api-key"
    if authentication_scheme == "local_subscription_session":
        return f"{provider}.subscription-session"
    if authentication_scheme == "tailscale_app_capability":
        return "tailscale.credential-ref"
    return f"{provider}.session-ref"


_PRODUCT_CATALOG_CACHE = CatalogCache()


def _capability_intersection(
    declared: ModelCapabilities, discovered: ModelCapabilities
) -> ModelCapabilities:
    return ModelCapabilities(
        structured_output=declared.structured_output and discovered.structured_output,
        native_tools=declared.native_tools and discovered.native_tools,
        system_prompt_channel=(
            declared.system_prompt_channel and discovered.system_prompt_channel
        ),
        deterministic_execution=(
            declared.deterministic_execution and discovered.deterministic_execution
        ),
        embedding_dimension=discovered.embedding_dimension,
    )


def _latest_product_catalog_target(
    selected: LLMRoute,
    *,
    adapter_id: str,
    intent: LLMTaskIntent,
    remote_transport: CodexRemoteTransport | None,
    catalog_cache: CatalogCache,
):
    """Select only within an explicitly registered Product model family."""
    if adapter_id != "codex_cli_tailscale":
        return None
    models = load_models()
    pinned = next(
        (
            model
            for model in models.values()
            if model.provider == selected.provider and model.model == selected.model
        ),
        None,
    )
    if (
        pinned is None
        or not pinned.selection_group
        or adapter_id not in pinned.allowed_transports
    ):
        return None
    accepted_models = tuple(
        sorted(
            model.model
            for model in models.values()
            if model.provider == selected.provider
            and model.kind == "chat"
            and model.selection_group == pinned.selection_group
            and adapter_id in model.allowed_transports
        )
    )
    if selected.model not in accepted_models:
        raise ValueError("pinned Product model is not in its declared selection group")
    if remote_transport is None:
        raise CatalogError("catalog_unavailable")

    def load_snapshot(_now):
        try:
            snapshot = remote_transport.catalog(
                CatalogRequest(transport_id="codex_cli")
            ).snapshot
        except Exception as exc:
            code = getattr(exc, "code", None)
            if code == "catalog_unavailable":
                catalog_code = "catalog_unavailable"
            elif code == "catalog_auth_failed":
                catalog_code = "catalog_auth_failed"
            elif code == "catalog_stale":
                catalog_code = "catalog_stale"
            else:
                # A malformed, oversized, or transport-mismatched response is
                # invalid data, not an outage that can authorize stale routing.
                catalog_code = "catalog_invalid"
            raise CatalogError(catalog_code) from exc
        if snapshot.transport_id != "codex_cli":
            raise CatalogError("catalog_invalid")
        return snapshot

    snapshot = catalog_cache.get(
        provider=selected.provider,
        transport_id="codex_cli",
        loader=load_snapshot,
    )
    policy = CatalogSelectionPolicy(
        provider=selected.provider,
        accepted_models=accepted_models,
        accepted_transports=("codex_cli",),
        required_capabilities=ModelCapabilityRequirements(
            structured_output=intent.json_schema_required,
            native_tools=intent.native_tools_required,
            literal_system_role_required=intent.literal_system_role_required,
            deterministic_execution=intent.determinism_required,
        ),
        reasoning_effort=selected.reasoning_effort or "low",
        pinned_model=selected.model,
    )
    return snapshot, select_latest_compatible(snapshot, policy)


def _exact_product_model_route(
    intent: LLMTaskIntent, model_id: str, *, factory: ModelAccessAdapterFactory
) -> LLMRoute:
    """Resolve one explicit model only through Product's declared registry."""
    matches = [
        descriptor
        for descriptor in load_models().values()
        if descriptor.kind == "chat" and descriptor.model == model_id
    ]
    if len(matches) != 1:
        raise LLMRouteError(
            "explicit model must resolve to exactly one declared Product chat model"
        )
    descriptor = matches[0]
    allowed = tuple(descriptor.allowed_transports) or (
        factory.default_adapter_id(descriptor.provider),
    )
    default_adapter = factory.default_adapter_id(descriptor.provider)
    if default_adapter in allowed:
        adapter_id = default_adapter
    elif len(allowed) == 1:
        adapter_id = allowed[0]
    else:
        raise LLMRouteError(
            "explicit Product model has multiple allowed transports and no declared default"
        )
    try:
        factory.describe(adapter_id, provider=descriptor.provider, model=model_id)
    except ValueError as exc:
        raise LLMRouteError("explicit Product model transport is not declared") from exc
    return LLMRoute(
        provider=descriptor.provider,
        model=model_id,
        mode="chat",
        reason=f"explicit-model:{intent.task_kind}",
        transport_id=adapter_id,
    )


def _global_route_enforcement_active() -> bool:
    if os.getenv("LLM_FORCE_PROVIDER", "").strip() or os.getenv(
        "LLM_FORCE_MODEL", ""
    ).strip():
        return True
    return os.getenv("LLM_PROVIDER_ENFORCE", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _matches_enforced_route(enforced: LLMRoute, selected: LLMRoute) -> bool:
    if (enforced.provider, enforced.model) != (selected.provider, selected.model):
        return False
    if enforced.transport_id and enforced.transport_id != selected.transport_id:
        return False
    if (
        enforced.reasoning_effort
        and enforced.reasoning_effort != selected.reasoning_effort
    ):
        return False
    return True


def _resolve_product_access_route(
    intent: LLMTaskIntent,
    selected: LLMRoute,
    *,
    adapter_factory: ModelAccessAdapterFactory | None = None,
    remote_transport: CodexRemoteTransport | None = None,
    catalog_cache: CatalogCache | None = None,
    fallback_requirement: FallbackRequirement = "fallback_forbidden",
    fallback_provenance: FallbackProvenance | None = None,
    allow_catalog_promotion: bool = True,
) -> ModelAccessRoute:
    factory = adapter_factory or _adapter_factory()
    adapter_id = selected.transport_id or factory.default_adapter_id(selected.provider)
    if adapter_id == "codex_cli":
        raise LLMRouteError(
            "Product chat facade cannot execute the local codex_cli transport"
        )
    product_descriptor = next(
        (
            model
            for model in load_models().values()
            if model.kind == "chat"
            and model.provider == selected.provider
            and model.model == selected.model
        ),
        None,
    )
    if (
        product_descriptor is not None
        and product_descriptor.allowed_transports
        and adapter_id not in product_descriptor.allowed_transports
    ):
        raise LLMRouteError("selected transport is not allowed for the Product model")
    # Validate the pinned target before any catalog discovery. A catalog adapter
    # must not become an oracle for an unknown provider/model/transport pair.
    pinned_adapter = factory.describe(
        adapter_id, provider=selected.provider, model=selected.model
    )
    catalog_result = (
        _latest_product_catalog_target(
            selected,
            adapter_id=adapter_id,
            intent=intent,
            remote_transport=remote_transport,
            catalog_cache=catalog_cache or _PRODUCT_CATALOG_CACHE,
        )
        if allow_catalog_promotion
        else None
    )
    selected_model = selected.model
    catalog_snapshot = None
    discovered_capabilities = None
    if catalog_result is not None:
        catalog_snapshot, catalog_target = catalog_result
        selected_model = catalog_target.model
        discovered_capabilities = catalog_target.capabilities
    descriptor = (
        pinned_adapter
        if selected_model == selected.model
        else factory.describe(adapter_id, provider=selected.provider, model=selected_model)
    )
    reasoning_effort = selected.reasoning_effort or "low"
    access_intent = ModelAccessIntent(
        capability_tier=(
            "frontier"
            if intent.risk == "high" or intent.complexity_hint == "high"
            else "standard"
        ),
        reasoning_effort=reasoning_effort,
        determinism_required=intent.determinism_required,
        output_schema_ref=("product.inline_output_schema" if intent.json_schema_required else None),
        independence="none",
        fallback_requirement=fallback_requirement,
        side_effect_class="model_completion",
    )
    request = ModelResolutionRequest(
        intent=access_intent,
        role_profile=intent.task_kind,
        resolution_group_id=f"product.{intent.task_kind}",
        requirements=ModelCapabilityRequirements(
            structured_output=intent.json_schema_required,
            native_tools=intent.native_tools_required,
            literal_system_role_required=intent.literal_system_role_required,
            deterministic_execution=intent.determinism_required,
        ),
    )
    selected_target = ResolvedModelAccess(
        request=request,
        provider=selected.provider,
        model=selected_model,
        adapter_id=adapter_id,
        effective_identity=f"{selected.provider}/{selected_model}",
        capabilities=(
            _capability_intersection(
                descriptor.supported_capabilities, discovered_capabilities
            )
            if discovered_capabilities is not None
            else descriptor.supported_capabilities
        ),
        credential_identity_ref=_credential_ref(
            descriptor.authentication_scheme, selected.provider
        ),
        degraded=selected.degraded,
        degradation_reason=(
            "policy_selected_compatible_route" if selected.degraded else None
        ),
        fallback_provenance=fallback_provenance or FallbackProvenance(),
    )
    capability_provenance = CapabilityProvenance(
        source=(
            "catalog_snapshot" if catalog_snapshot is not None else "adapter_attestation"
        ),
        source_ref=(
            catalog_snapshot.snapshot_ref if catalog_snapshot is not None else adapter_id
        ),
    )
    profile = ModelAccessProfile(
        profile_id="profile.product_runtime",
        runtime="product",
        channel="runtime",
        consumer="product.chat",
        caller_profile="profile.product_chat_client",
        catalog_snapshot_ref=(
            catalog_snapshot.snapshot_ref if catalog_snapshot is not None else None
        ),
        catalog_snapshot_hash=(
            catalog_snapshot.snapshot_hash if catalog_snapshot is not None else None
        ),
        capability_provenance=capability_provenance,
    )
    return ModelAccessRouter(adapter_registry=factory).resolve(
        request,
        resolver=_SelectedProductTarget(selected_target),
        profile=profile,
    )


def _codex_remote_request(
    route: ModelAccessRoute,
    pack: dict[str, Any],
    *,
    response_format: dict[str, Any] | str | None,
    max_output_tokens: int | None = None,
) -> CompletionRequest:
    output_schema: dict[str, Any] | None
    if isinstance(response_format, dict):
        output_schema = response_format
    elif response_format == "json":
        output_schema = {"type": "object"}
    else:
        output_schema = None
    if route.transport_id == "codex_cli_tailscale":
        provider = "openai"
        transport_id = "codex_cli"
        reasoning_effort = route.request.intent.reasoning_effort
    elif route.transport_id == "ollama_http_tailscale":
        provider = "ollama"
        transport_id = "ollama_http"
        reasoning_effort = None
    else:
        raise ValueError("selected route is not an authenticated remote transport")
    return CompletionRequest(
        route=CompletionRouteIdentity(
            provider=provider, model=route.model, transport_id=transport_id
        ),
        reasoning_effort=reasoning_effort,
        capability_intent=CompletionCapabilityIntent(
            structured_output=output_schema is not None,
            native_tools=route.request.requirements.native_tools,
            literal_system_role_required=(
                route.request.requirements.literal_system_role_required
            ),
            max_output_tokens_required=max_output_tokens is not None,
        ),
        trusted_instructions=str(pack.get("system", "")),
        user_input=str(pack.get("user", "")),
        output_schema=output_schema,
        max_output_tokens=max_output_tokens,
    )


def _same_route_target(left: LLMRoute, right: LLMRoute) -> bool:
    return (
        left.provider,
        left.model,
        left.transport_id,
        left.reasoning_effort,
    ) == (
        right.provider,
        right.model,
        right.transport_id,
        right.reasoning_effort,
    )


def _explicit_remote_ollama_fallback(
    candidates: list[LLMRoute], *, factory: ModelAccessAdapterFactory
) -> LLMRoute | None:
    """Return only a registry-approved, explicitly remote Ollama alternative."""
    models = load_models()
    for candidate in candidates[1:]:
        adapter_id = candidate.transport_id or factory.default_adapter_id(
            candidate.provider
        )
        if candidate.provider != "ollama" or adapter_id != "ollama_http_tailscale":
            continue
        descriptor = next(
            (
                model
                for model in models.values()
                if model.provider == candidate.provider
                and model.model == candidate.model
                and model.kind == "chat"
            ),
            None,
        )
        if descriptor is None or adapter_id not in descriptor.allowed_transports:
            continue
        return LLMRoute(
            provider=candidate.provider,
            model=candidate.model,
            mode=candidate.mode,
            reason=candidate.reason,
            degraded=True,
            timeout_seconds=candidate.timeout_seconds,
            temperature=candidate.temperature,
            transport_id=adapter_id,
            reasoning_effort=None,
        )
    return None


def _with_preflight_passed(route: ModelAccessRoute) -> ModelAccessRoute:
    """Revalidate the bound route after its no-inference probe succeeds."""
    return ModelAccessRoute(
        **{
            **route.model_dump(),
            "preflight_status": "passed",
            "preflight_failure_code": None,
        }
    )


def _product_fallback_provenance(
    selection_provenance: FallbackProvenance,
    *,
    primary: ModelAccessRoute,
    fallback: ModelAccessRoute,
) -> FallbackProvenance:
    return FallbackProvenance(
        used=True,
        phase="preflight",
        reason_code=selection_provenance.reason_code,
        source_transport_id=primary.transport_id,
        selected_transport_id=fallback.transport_id,
        policy_authority="profile.product_runtime",
        source_effective_identity=primary.effective_identity,
        selected_effective_identity=fallback.effective_identity,
    )


@dataclass
class ChatClient:
    route: LLMRoute
    model_access_route: ModelAccessRoute | None = None
    remote_transport: CodexRemoteTransport | None = None
    _intent: LLMTaskIntent | None = field(default=None, repr=False, compare=False)
    _output_limit_route_resolved: bool = field(default=False, repr=False, compare=False)
    _adapter_runtime_config: AdapterRuntimeConfig | None = field(
        default=None, repr=False, compare=False
    )
    _fallback_access_route: ModelAccessRoute | None = field(
        default=None, repr=False, compare=False
    )
    _fallback_route: LLMRoute | None = field(default=None, repr=False, compare=False)

    def _resolve_output_limit_route(self, max_tokens: int) -> None:
        """Preflight the caller's token cap without re-resolving its bound model."""
        route = self.model_access_route
        if route is None or self._intent is None:
            raise ValueError("a remote output-token limit needs its bound Product route")
        endpoint = os.getenv("MODEL_ACCESS_CODEX_REMOTE_ENDPOINT", "").strip()
        if not endpoint:
            raise RuntimeError(
                "MODEL_ACCESS_CODEX_REMOTE_ENDPOINT is required for the remote model route"
            )
        transport = self.remote_transport
        owns_transport = transport is None
        if transport is None:
            transport = CodexRemoteTransport(
                endpoint=endpoint,
                timeout_seconds=self.route.timeout_seconds or 1_260.0,
            )
        request = _codex_remote_request(
            route,
            {"system": "", "user": "preflight"},
            response_format=(
                {"type": "object"} if self._intent.json_schema_required else None
            ),
            max_output_tokens=max_tokens,
        )
        fallback_wire_route = None
        if (
            route.transport_id == "codex_cli_tailscale"
            and self._fallback_access_route is not None
            and not route.fallback_provenance.used
        ):
            fallback_wire_route = _codex_remote_request(
                self._fallback_access_route,
                {"system": "", "user": "preflight"},
                response_format=(
                    {"type": "object"} if self._intent.json_schema_required else None
                ),
                max_output_tokens=max_tokens,
            ).route
        try:
            selection = select_preflight_route(
                request,
                fallback_route=fallback_wire_route,
                fallback_requirement=(
                    "fallback_policy_selected"
                    if fallback_wire_route is not None
                    else "fallback_forbidden"
                ),
                policy_authority="profile.product_runtime",
                transport=transport,
            )
            if selection.fallback_provenance.used:
                assert self._fallback_access_route is not None
                assert self._fallback_route is not None
                provenance = _product_fallback_provenance(
                    selection.fallback_provenance,
                    primary=route,
                    fallback=self._fallback_access_route,
                )
                selected_access_route = ModelAccessRoute(
                    **{
                        **self._fallback_access_route.model_dump(),
                        "fallback_provenance": provenance,
                    }
                )
                self.model_access_route = _with_preflight_passed(
                    selected_access_route
                )
                self.route = LLMRoute.from_model_access_route(
                    self.model_access_route,
                    mode=self._fallback_route.mode,
                    reason=self._fallback_route.reason,
                    timeout_seconds=self._fallback_route.timeout_seconds,
                    temperature=self._fallback_route.temperature,
                )
            else:
                self.model_access_route = _with_preflight_passed(route)
                self.route = LLMRoute.from_model_access_route(
                    self.model_access_route,
                    mode=self.route.mode,
                    reason=self.route.reason,
                    embedding_identity=self.route.embedding_identity,
                    timeout_seconds=self.route.timeout_seconds,
                    temperature=self.route.temperature,
                )
            self._output_limit_route_resolved = True
        finally:
            if owns_transport:
                transport.close()

    def chat(
        self,
        name: str,
        pack: dict[str, Any],
        *,
        agent: str | None = None,
        kind: str | None = None,
        trace_id: str | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | str | None = None,
    ) -> str:
        if (
            self.model_access_route is not None
            and self.model_access_route.transport_id
            in {"codex_cli_tailscale", "ollama_http_tailscale"}
            and max_tokens is not None
            and not self._output_limit_route_resolved
        ):
            self._resolve_output_limit_route(max_tokens)

        if (
            self.model_access_route is not None
            and self.model_access_route.transport_id
            in {"codex_cli_tailscale", "ollama_http_tailscale"}
        ):
            route = self.model_access_route
            transport = self.remote_transport
            owns_transport = transport is None
            if transport is None:
                endpoint = os.getenv("MODEL_ACCESS_CODEX_REMOTE_ENDPOINT", "").strip()
                if not endpoint:
                    raise RuntimeError(
                        "MODEL_ACCESS_CODEX_REMOTE_ENDPOINT is required for the remote model route"
                    )
                transport = CodexRemoteTransport(
                    endpoint=endpoint,
                    timeout_seconds=self.route.timeout_seconds or 1_260.0,
                )
            request = _codex_remote_request(
                route,
                pack,
                response_format=response_format,
                max_output_tokens=max_tokens,
            )
            if (
                route.request.requirements.structured_output
                and request.output_schema is None
            ):
                raise ValueError("the selected route requires a structured-output schema")
            if (
                request.output_schema is not None
                and not route.capabilities.structured_output
            ):
                raise ValueError("the selected route does not attest structured output")
            try:
                if route.preflight_status != "passed":
                    transport.preflight(
                        PreflightRequest(
                            route=request.route,
                            reasoning_effort=request.reasoning_effort,
                            capability_intent=request.capability_intent,
                        )
                    )
                return transport.complete(request).content
            finally:
                if owns_transport:
                    transport.close()
        return call_llm(
            name,
            pack,
            agent=agent,
            kind=kind,
            trace_id=trace_id,
            provider_override=self.route.provider,
            model_override=self.route.model,
            timeout_seconds=self.route.timeout_seconds,
            temperature=self.route.temperature,
            max_tokens=max_tokens,
            response_format=response_format,
            base_url_override=(
                self._adapter_runtime_config.base_url
                if self._adapter_runtime_config is not None
                else None
            ),
            api_key_override=(
                self._adapter_runtime_config.api_key
                if self._adapter_runtime_config is not None
                else None
            ),
        )


def get_chat_client(
    intent: LLMTaskIntent,
    *,
    model_id: str | None = None,
    adapter_runtime_config: AdapterRuntimeConfig | None = None,
) -> ChatClient:
    """Bind a Product intent to its temporary route behind one thin facade."""
    if model_id is None:
        return get_chat_client_for_route(
            intent, adapter_runtime_config=adapter_runtime_config
        )
    selected = _exact_product_model_route(
        intent, model_id, factory=_adapter_factory()
    )
    return get_chat_client_for_route(
        intent,
        selected_route=selected,
        adapter_runtime_config=adapter_runtime_config,
        allow_catalog_promotion=False,
    )


def get_chat_client_for_route(
    intent: LLMTaskIntent,
    *,
    selected_route: LLMRoute | None = None,
    max_output_tokens: int | None = None,
    adapter_runtime_config: AdapterRuntimeConfig | None = None,
    allow_catalog_promotion: bool = True,
) -> ChatClient:
    """Bind one already-resolved Product policy route to the shared access facade."""
    router = LLMRouter()
    route_candidates = getattr(router, "candidate_routes", None)
    candidates = route_candidates(intent) if route_candidates is not None else []
    selected = selected_route or (candidates[0] if candidates else router.route(intent))
    if selected_route is not None and candidates and not _same_route_target(
        candidates[0], selected_route
    ):
        if _global_route_enforcement_active() and not _matches_enforced_route(
            candidates[0], selected_route
        ):
            raise LLMRouteError(
                "explicit Product route conflicts with active global route enforcement"
            )
        candidates = [selected_route]
    elif not candidates:
        candidates = [selected]

    factory = _adapter_factory()
    fallback = (
        _explicit_remote_ollama_fallback(candidates, factory=factory)
        if selected.transport_id == "codex_cli_tailscale"
        else None
    )
    remote_transport = None
    owns_remote_transport = False
    if selected.transport_id in {
        "codex_cli_tailscale",
        "ollama_http_tailscale",
    }:
        endpoint = os.getenv("MODEL_ACCESS_CODEX_REMOTE_ENDPOINT", "").strip()
        if not endpoint:
            raise RuntimeError(
                "MODEL_ACCESS_CODEX_REMOTE_ENDPOINT is required for the remote model route"
            )
        remote_transport = CodexRemoteTransport(
            endpoint=endpoint,
            timeout_seconds=selected.timeout_seconds or 1_260.0,
        )
        owns_remote_transport = True
    fallback_access_route = None
    try:
        model_access_route = _resolve_product_access_route(
            intent,
            selected,
            adapter_factory=factory,
            remote_transport=remote_transport,
            fallback_requirement=(
                "fallback_policy_selected" if fallback is not None else "fallback_forbidden"
            ),
            allow_catalog_promotion=allow_catalog_promotion,
        )
        if remote_transport is not None:
            request = _codex_remote_request(
                model_access_route,
                {"system": "", "user": "preflight"},
                response_format=(
                    {"type": "object"} if intent.json_schema_required else None
                ),
                max_output_tokens=max_output_tokens,
            )
            fallback_wire_route = None
            if fallback is not None:
                fallback_access_route = _resolve_product_access_route(
                    intent,
                    fallback,
                    adapter_factory=factory,
                    fallback_requirement="fallback_policy_selected",
                    allow_catalog_promotion=allow_catalog_promotion,
                )
                fallback_wire_route = _codex_remote_request(
                    fallback_access_route,
                    {"system": "", "user": "preflight"},
                    response_format=(
                        {"type": "object"} if intent.json_schema_required else None
                    ),
                    max_output_tokens=max_output_tokens,
                ).route
            selection = select_preflight_route(
                request,
                fallback_route=fallback_wire_route,
                fallback_requirement=(
                    "fallback_policy_selected"
                    if fallback_wire_route is not None
                    else "fallback_forbidden"
                ),
                policy_authority="profile.product_runtime",
                transport=remote_transport,
            )
            if selection.fallback_provenance.used:
                assert fallback is not None and fallback_access_route is not None
                provenance = _product_fallback_provenance(
                    selection.fallback_provenance,
                    primary=model_access_route,
                    fallback=fallback_access_route,
                )
                model_access_route = ModelAccessRoute(
                    **{
                        **fallback_access_route.model_dump(),
                        "fallback_provenance": provenance,
                    }
                )
            model_access_route = _with_preflight_passed(model_access_route)
    finally:
        if owns_remote_transport and remote_transport is not None:
            remote_transport.close()
    route = LLMRoute.from_model_access_route(
        model_access_route,
        mode=(
            fallback.mode
            if model_access_route.fallback_provenance.used and fallback
            else selected.mode
        ),
        reason=(
            fallback.reason
            if model_access_route.fallback_provenance.used and fallback
            else selected.reason
        ),
        embedding_identity=selected.embedding_identity,
        timeout_seconds=(
            fallback.timeout_seconds
            if model_access_route.fallback_provenance.used and fallback
            else selected.timeout_seconds
        ),
        temperature=(
            fallback.temperature
            if model_access_route.fallback_provenance.used and fallback
            else selected.temperature
        ),
    )
    return ChatClient(
        route=route,
        model_access_route=model_access_route,
        _intent=intent,
        _output_limit_route_resolved=max_output_tokens is not None,
        _adapter_runtime_config=adapter_runtime_config,
        _fallback_access_route=fallback_access_route,
        _fallback_route=fallback,
    )


def get_embeddings_client(intent: LLMTaskIntent) -> EmbeddingClientProtocol:
    router = LLMRouter()
    route = router.route(intent)
    if route.embedding_identity is not None:
        return get_embedding_client(resolved_identity=route.embedding_identity)
    return get_embedding_client(override_model=route.model, override_provider=route.provider)


def describe_default_routes() -> dict[str, dict[str, str]]:
    router = LLMRouter()
    intents = [intent for intent in router.verification_intents() if intent.task_kind in {"embed", "decide", "plan"}]
    routes = router.default_routes(intents)
    return {
        key: {
            "provider": route.provider,
            "model": route.model,
            "transport_id": (
                route.transport_id
                or (
                    _adapter_factory().default_adapter_id(route.provider)
                    if route.mode != "embeddings"
                    else ""
                )
            ),
            "reasoning_effort": route.reasoning_effort or "",
            "mode": route.mode,
            "reason": route.reason,
            "degraded": str(route.degraded),
        }
        for key, route in routes.items()
    }


def describe_default_route_policies() -> dict[str, dict[str, object]]:
    router = LLMRouter()
    policies = router.describe_routes(router.verification_intents())
    factory = _adapter_factory()
    for task_kind, policy in policies.items():
        if task_kind == "embed":
            continue
        for key in ("effective", "preferred"):
            route = policy.get(key)
            if not isinstance(route, dict):
                continue
            provider = str(route.get("provider") or "")
            if provider:
                route["transport_id"] = route.get("transport_id") or factory.default_adapter_id(provider)
                route["reasoning_effort"] = route.get("reasoning_effort") or "low"
    return policies


__all__ = [
    "AdapterRuntimeConfig",
    "LLMTaskIntent",
    "LLMRoute",
    "LLMBackendTimeout",
    "ChatClient",
    "get_chat_client",
    "get_chat_client_for_route",
    "get_embeddings_client",
    "describe_default_routes",
    "describe_default_route_policies",
]
