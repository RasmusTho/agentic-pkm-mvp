from __future__ import annotations

import json

import pytest

from app.llm.preflight_fallback import select_preflight_route
from app.model_access.codex_remote_transport import (
    RemoteCompletionError,
    RemotePreflightError,
)
from app.model_access.remote_contract import (
    CompletionCapabilityIntent,
    CompletionRequest,
    CompletionResponse,
    CompletionRouteIdentity,
    PreflightRequest,
    PreflightResponse,
)


PRIMARY = CompletionRouteIdentity(
    provider="openai", model="gpt-5.6-luna", transport_id="codex_cli"
)
OLLAMA = CompletionRouteIdentity(
    provider="ollama", model="llama3.1:8b", transport_id="ollama_http"
)


def _request(
    *,
    native_tools: bool = False,
    literal_system_role_required: bool = False,
    max_output_tokens: int | None = None,
) -> CompletionRequest:
    return CompletionRequest(
        route=PRIMARY,
        reasoning_effort="low",
        capability_intent=CompletionCapabilityIntent(
            native_tools=native_tools,
            literal_system_role_required=literal_system_role_required,
            max_output_tokens_required=max_output_tokens is not None,
        ),
        trusted_instructions="Keep the answer concise.",
        user_input="Summarize the sample.",
        output_schema=None,
        max_output_tokens=max_output_tokens,
    )


class FakeRemote:
    def __init__(
        self,
        *,
        primary_preflight_error: str | None = None,
        completion_error: RemoteCompletionError | None = None,
    ) -> None:
        self.primary_preflight_error = primary_preflight_error
        self.completion_error = completion_error
        self.events: list[tuple[str, str]] = []
        self.completion_requests: list[CompletionRequest] = []

    def preflight(self, request: PreflightRequest) -> PreflightResponse:
        route = request.route.transport_id
        self.events.append(("preflight", route))
        if route == "codex_cli" and self.primary_preflight_error is not None:
            raise RemotePreflightError(self.primary_preflight_error)
        if route == "ollama_http" and request.capability_intent.native_tools:
            raise RemotePreflightError("native_tools_unavailable")
        if (
            route == "codex_cli"
            and request.capability_intent.max_output_tokens_required
        ):
            raise RemotePreflightError("output_token_limit_unavailable")
        return PreflightResponse(route=request.route, preflight_status="passed")

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.events.append(("complete", request.route.transport_id))
        self.completion_requests.append(request)
        if self.completion_error is not None:
            raise self.completion_error
        return CompletionResponse(route=request.route, content="A concise summary.")


def test_compatible_fallback_occurs_before_first_model_call() -> None:
    remote = FakeRemote(primary_preflight_error="session_expired")

    selection = select_preflight_route(
        _request(),
        fallback_route=OLLAMA,
        fallback_requirement="fallback_compatible_identity",
        policy_authority="profile.product_llm",
        transport=remote,
    )

    assert remote.events == [
        ("preflight", "codex_cli"),
        ("preflight", "ollama_http"),
    ]
    response = remote.complete(selection.request)
    assert remote.events[-1] == ("complete", "ollama_http")
    assert len(remote.completion_requests) == 1
    assert remote.completion_requests[0].route == OLLAMA
    assert response.route == OLLAMA
    assert selection.fallback_provenance.used is True


def test_output_token_limit_uses_declared_ollama_after_codex_capability_preflight() -> None:
    remote = FakeRemote()
    request = _request(max_output_tokens=160)

    selection = select_preflight_route(
        request,
        fallback_route=OLLAMA,
        fallback_requirement="fallback_compatible_identity",
        policy_authority="profile.product_llm",
        transport=remote,
    )

    assert remote.events == [
        ("preflight", "codex_cli"),
        ("preflight", "ollama_http"),
    ]
    assert selection.request.route == OLLAMA
    assert selection.request.capability_intent.max_output_tokens_required is True
    assert selection.request.max_output_tokens == 160
    remote.complete(selection.request)
    assert remote.events[-1] == ("complete", "ollama_http")
    assert len(remote.completion_requests) == 1


def test_output_token_limit_does_not_weaken_strong_reasoning_route() -> None:
    remote = FakeRemote()
    request = _request(max_output_tokens=160).model_copy(
        update={"reasoning_effort": "high"}
    )

    with pytest.raises(RemotePreflightError) as error:
        select_preflight_route(
            request,
            fallback_route=OLLAMA,
            fallback_requirement="fallback_compatible_identity",
            policy_authority="profile.product_llm",
            transport=remote,
        )

    assert error.value.code == "output_token_limit_unavailable"
    assert remote.events == [("preflight", "codex_cli")]
    assert remote.completion_requests == []


def test_ollama_is_rejected_when_native_tools_are_required() -> None:
    remote = FakeRemote(primary_preflight_error="session_expired")

    with pytest.raises(RemotePreflightError) as error:
        select_preflight_route(
            _request(native_tools=True),
            fallback_route=OLLAMA,
            fallback_requirement="fallback_compatible_identity",
            policy_authority="profile.product_llm",
            transport=remote,
        )

    assert error.value.code == "native_tools_unavailable"
    assert remote.events == [
        ("preflight", "codex_cli"),
        ("preflight", "ollama_http"),
    ]
    assert remote.completion_requests == []


def test_strong_reasoning_failure_does_not_downgrade_to_ollama() -> None:
    remote = FakeRemote(primary_preflight_error="model_unavailable")
    request = _request().model_copy(update={"reasoning_effort": "high"})

    with pytest.raises(RemotePreflightError) as error:
        select_preflight_route(
            request,
            fallback_route=OLLAMA,
            fallback_requirement="fallback_compatible_identity",
            policy_authority="profile.product_llm",
            transport=remote,
        )

    assert error.value.code == "model_unavailable"
    assert remote.events == [("preflight", "codex_cli")]
    assert remote.completion_requests == []


def test_literal_system_role_requirement_does_not_downgrade_to_ollama() -> None:
    remote = FakeRemote(primary_preflight_error="session_expired")

    with pytest.raises(RemotePreflightError) as error:
        select_preflight_route(
            _request(literal_system_role_required=True),
            fallback_route=OLLAMA,
            fallback_requirement="fallback_compatible_identity",
            policy_authority="profile.product_llm",
            transport=remote,
        )

    assert error.value.code == "session_expired"
    assert remote.events == [("preflight", "codex_cli")]
    assert remote.completion_requests == []


def test_post_start_failure_never_calls_fallback_provider() -> None:
    remote = FakeRemote(
        primary_preflight_error="session_expired",
        completion_error=RemoteCompletionError(
            "execution_indeterminate", indeterminate=True
        )
    )

    selection = select_preflight_route(
        _request(),
        fallback_route=OLLAMA,
        fallback_requirement="fallback_compatible_identity",
        policy_authority="profile.product_llm",
        transport=remote,
    )
    with pytest.raises(RemoteCompletionError) as error:
        remote.complete(selection.request)

    assert error.value.indeterminate is True
    assert remote.events == [
        ("preflight", "codex_cli"),
        ("preflight", "ollama_http"),
        ("complete", "ollama_http"),
    ]
    assert len(remote.completion_requests) == 1
    assert selection.fallback_provenance.used is True


def test_fallback_receipt_binds_preflight_reason_without_secrets() -> None:
    remote = FakeRemote(primary_preflight_error="session_expired")

    selection = select_preflight_route(
        _request(),
        fallback_route=OLLAMA,
        fallback_requirement="fallback_policy_selected",
        policy_authority="profile.product_llm",
        transport=remote,
    )
    receipt = selection.fallback_provenance.model_dump(mode="json")
    serialized = json.dumps(receipt, sort_keys=True)

    assert receipt == {
        "used": True,
        "phase": "preflight",
        "reason_code": "session_expired",
        "source_transport_id": "codex_cli",
        "selected_transport_id": "ollama_http",
        "policy_authority": "profile.product_llm",
        "source_effective_identity": "openai/gpt-5.6-luna",
        "selected_effective_identity": "ollama/llama3.1:8b",
    }
    assert "https://" not in serialized
    assert "ts.net" not in serialized
    assert "secret" not in serialized.lower()


def test_fallback_forbidden_policy_never_selects_ollama() -> None:
    remote = FakeRemote(primary_preflight_error="session_expired")

    with pytest.raises(ValueError, match="forbids"):
        select_preflight_route(
            _request(),
            fallback_route=OLLAMA,
            fallback_requirement="fallback_forbidden",
            policy_authority="profile.builder_model_inquiry",
            transport=remote,
        )

    assert remote.events == []
    assert remote.completion_requests == []
