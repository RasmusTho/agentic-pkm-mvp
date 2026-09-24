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
)


_FALLBACKABLE_PREFLIGHT_FAILURES = {
    "preflight_unavailable": "executor_unreachable",
    "preflight_response_invalid": "executor_unreachable",
    "preflight_response_too_large": "executor_unreachable",
    "preflight_http_403": "executor_unreachable",
    "preflight_http_404": "executor_unreachable",
    "preflight_http_429": "executor_unreachable",
    "preflight_http_500": "executor_unreachable",
    "preflight_http_502": "executor_unreachable",
    "preflight_http_503": "executor_unreachable",
    "preflight_http_504": "executor_unreachable",
    "serve_capability_required": "executor_unreachable",
    "serve_capability_invalid": "executor_unreachable",
    "loopback_only": "executor_unreachable",
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


@dataclass(frozen=True)
class PreflightRouteSelection:
    request: CompletionRequest
    fallback_provenance: FallbackProvenance


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
    try:
        transport.preflight(_preflight_request(request))
    except RemotePreflightError as primary_failure:
        reason_code = _FALLBACKABLE_PREFLIGHT_FAILURES.get(primary_failure.code)
        if not fallback_allowed or fallback_route is None or reason_code is None:
            raise

        selected_request = _request_for_route(request, fallback_route)
        # The selected route must independently prove it satisfies the exact same
        # capability intent. A failure here is terminal; there is no third target.
        transport.preflight(_preflight_request(selected_request))
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
    )


__all__ = [
    "PreflightRouteSelection",
    "select_preflight_route",
]
