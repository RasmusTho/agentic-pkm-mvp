"""Product-only preflight selection for the configured Codex-to-Ollama pair."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from llm_contract import FallbackProvenance, FallbackRequirement

from app.model_access.codex_remote_transport import RemotePreflightError
from app.model_access.remote_contract import (
    CompletionRequest,
    CompletionRouteIdentity,
    PreflightRequest,
    ProductPreflightRequest,
)


_FALLBACKABLE_PREFLIGHT_FAILURES = {
    "preflight_unavailable": "executor_unreachable",
    "preflight_response_invalid": "executor_unreachable",
    "preflight_response_too_large": "executor_unreachable",
    "preflight_http_404": "executor_unreachable",
    "preflight_http_429": "executor_unreachable",
    "preflight_http_500": "executor_unreachable",
    "preflight_http_502": "executor_unreachable",
    "preflight_http_503": "executor_unreachable",
    "preflight_http_504": "executor_unreachable",
    "executor_busy": "executor_unreachable",
    "command_timeout": "executor_unreachable",
    "cli_missing": "cli_missing",
    "cli_version_unsupported": "adapter_unavailable",
    "tool_surface_unknown": "adapter_unavailable",
    "unsupported_profile": "adapter_unavailable",
    "credential_unavailable": "authentication_unavailable",
    "authentication_unavailable": "authentication_unavailable",
    "session_expired": "session_expired",
    "model_unavailable": "model_unavailable",
    "output_token_limit_unavailable": "adapter_unavailable",
}
_FALLBACK_REQUIREMENTS = frozenset(
    {"fallback_compatible_identity", "fallback_policy_selected"}
)
_FALLBACK_REASONING_EFFORTS = frozenset({"minimal", "low"})


class _PreflightCompletionTransport(Protocol):
    def preflight(self, request: PreflightRequest) -> object: ...


class _ProductPreflightTransport(Protocol):
    def preflight_product(self, request: ProductPreflightRequest) -> object: ...


@dataclass(frozen=True)
class PreflightRouteSelection:
    request: CompletionRequest
    fallback_provenance: FallbackProvenance
    executor_path_receipt: object | None = None


@dataclass(frozen=True)
class ProductPreflightRouteSelection:
    """One exact host-resolved route selected by logical Product preflight."""

    response: object
    fallback_provenance: FallbackProvenance
    executor_path_receipt: object | None = None


def _preflight_request(request: CompletionRequest) -> PreflightRequest:
    return PreflightRequest(
        route=request.route,
        reasoning_effort=request.reasoning_effort,
        capability_intent=request.capability_intent,
    )


def _request_for_route(
    request: CompletionRequest,
    route: CompletionRouteIdentity,
) -> CompletionRequest:
    return CompletionRequest(
        route=route,
        reasoning_effort=(
            request.reasoning_effort if route.transport_id == "codex_cli" else None
        ),
        capability_intent=request.capability_intent,
        trusted_instructions=request.trusted_instructions,
        user_input=request.user_input,
        output_schema=request.output_schema,
        max_output_tokens=request.max_output_tokens,
    )


def select_preflight_route(
    request: CompletionRequest,
    *,
    fallback_route: CompletionRouteIdentity | None,
    fallback_requirement: FallbackRequirement,
    policy_authority: str,
    transport: _PreflightCompletionTransport,
) -> PreflightRouteSelection:
    """Preflight an owner-selected pair and return one exact route for execution.

    The Product resolver supplies the optional fallback route and requirement. This
    helper never invents targets, weakens capability intent, or catches completion
    failures to try another provider. Returning the selected route before inference
    lets the caller bind fallback provenance to its route receipt first.
    """
    fallback_allowed = fallback_route is not None
    if fallback_route is not None:
        if fallback_requirement not in _FALLBACK_REQUIREMENTS:
            raise ValueError("the caller's fallback requirement forbids this fallback")
        if (
            request.route.transport_id != "codex_cli"
            or fallback_route.transport_id != "ollama_http"
        ):
            raise ValueError("fallback target is outside the compatible Product profile")
        if fallback_route == request.route:
            raise ValueError("fallback route must differ from the primary target")
        fallback_allowed = (
            request.reasoning_effort in _FALLBACK_REASONING_EFFORTS
            and not request.capability_intent.literal_system_role_required
        )

    selected_request = request
    provenance = FallbackProvenance()
    path_result = None
    try:
        path_result = transport.preflight(_preflight_request(request))
    except RemotePreflightError as primary_failure:
        reason_code = _FALLBACKABLE_PREFLIGHT_FAILURES.get(primary_failure.code)
        if not fallback_allowed or fallback_route is None or reason_code is None:
            raise

        selected_request = _request_for_route(request, fallback_route)
        # The selected route must independently prove it satisfies the exact same
        # capability intent. A failure here is terminal; there is no third target.
        path_result = transport.preflight(_preflight_request(selected_request))
        provenance = FallbackProvenance(
            used=True,
            phase="preflight",
            reason_code=reason_code,
            source_transport_id=request.route.transport_id,
            selected_transport_id=fallback_route.transport_id,
            policy_authority=policy_authority,
            source_effective_identity=f"{request.route.provider}/{request.route.model}",
            selected_effective_identity=(
                f"{fallback_route.provider}/{fallback_route.model}"
            ),
        )

    return PreflightRouteSelection(
        request=selected_request,
        fallback_provenance=provenance,
        executor_path_receipt=getattr(path_result, "receipt", None),
    )


def select_product_preflight_route(
    request: ProductPreflightRequest,
    *,
    fallback_request: ProductPreflightRequest | None,
    fallback_requirement: FallbackRequirement,
    policy_authority: str,
    transport: _ProductPreflightTransport,
    allow_codex_to_ollama_fallback: bool,
) -> ProductPreflightRouteSelection:
    """Preflight one Product target and, if explicitly authorized, one Ollama fallback."""
    fallback_allowed = fallback_request is not None
    if fallback_request is not None:
        if fallback_requirement not in _FALLBACK_REQUIREMENTS:
            raise ValueError("the caller's fallback requirement forbids this fallback")
        if (
            not allow_codex_to_ollama_fallback
            or request.provider != "openai"
            or fallback_request.provider != "ollama"
            or fallback_request.capability_intent != request.capability_intent
        ):
            raise ValueError("fallback target is outside the compatible Product profile")
        fallback_allowed = (
            request.reasoning_effort in _FALLBACK_REASONING_EFFORTS
            and not request.capability_intent.literal_system_role_required
        )

    try:
        path_result = transport.preflight_product(request)
        response = getattr(path_result, "response", path_result)
    except RemotePreflightError as primary_failure:
        reason_code = _FALLBACKABLE_PREFLIGHT_FAILURES.get(primary_failure.code)
        if not fallback_allowed or fallback_request is None or reason_code is None:
            raise
        path_result = transport.preflight_product(fallback_request)
        response = getattr(path_result, "response", path_result)
        if (
            response.route.provider != fallback_request.provider
            or response.route.model != fallback_request.model
            or response.route.transport_id != "ollama_http"
        ):
            raise RemotePreflightError("preflight_route_mismatch")
        provenance = FallbackProvenance(
            used=True,
            phase="preflight",
            reason_code=reason_code,
            source_transport_id="codex_cli",
            selected_transport_id="ollama_http",
            policy_authority=policy_authority,
            source_effective_identity=f"{request.provider}/{request.model}",
            selected_effective_identity=(
                f"{fallback_request.provider}/{fallback_request.model}"
            ),
        )
        return ProductPreflightRouteSelection(
            response=response,
            fallback_provenance=provenance,
            executor_path_receipt=getattr(path_result, "receipt", None),
        )

    if (
        response.route.provider != request.provider
        or response.route.model != request.model
    ):
        raise RemotePreflightError("preflight_route_mismatch")
    return ProductPreflightRouteSelection(
        response=response,
        fallback_provenance=FallbackProvenance(),
        executor_path_receipt=getattr(path_result, "receipt", None),
    )


__all__ = [
    "PreflightRouteSelection",
    "ProductPreflightRouteSelection",
    "select_preflight_route",
    "select_product_preflight_route",
]
