from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from app.model_access.codex_remote_transport import (
    RemoteCatalogError,
    RemoteCompletionError,
    RemotePreflightError,
)
from app.model_access.executor_network_policy import (
    DEFAULT_EXECUTOR_NETWORK_POLICY_PATH,
    ExecutorNetworkConfigurationError,
    ExecutorNetworkPathRouter,
    ExecutorPathReceipt,
    ResolvedExecutorPath,
)
from app.model_access.remote_contract import (
    CatalogRequest,
    CatalogResponse,
    CompletionRequest,
    CompletionResponse,
    CompletionRouteIdentity,
    CompletionCapabilityIntent,
    PreflightRequest,
    PreflightResponse,
)
from app.llm.preflight_fallback import select_preflight_route


def _request() -> PreflightRequest:
    return PreflightRequest(
        route=CompletionRouteIdentity(
            provider="openai",
            model="gpt-6-luna",
            transport_id="codex_cli",
        ),
        reasoning_effort="max",
        capability_intent=CompletionCapabilityIntent(
            structured_output=True,
            native_tools=False,
            literal_system_role_required=False,
            max_output_tokens_required=False,
        ),
    )


def _complete_request() -> CompletionRequest:
    preflight = _request()
    return CompletionRequest(
        route=preflight.route,
        reasoning_effort=preflight.reasoning_effort,
        capability_intent=preflight.capability_intent,
        trusted_instructions="Use the configured executor.",
        user_input="Say hello.",
        output_schema={"type": "object"},
    )


def _host_environment(tmp_path: Path) -> dict[str, str]:
    paths = {}
    for name in ("ca.pem", "client.pem", "client.key"):
        value = tmp_path / name
        value.write_text("test-only placeholder", encoding="utf-8")
        paths[name] = str(value)
    return {
        "MODEL_ACCESS_CODEX_VLAN_ENDPOINT": "https://192.168.10.25:8443",
        "MODEL_ACCESS_CODEX_REMOTE_ENDPOINT": "https://executor.example.ts.net",
        "MODEL_ACCESS_CODEX_VLAN_CA_BUNDLE": paths["ca.pem"],
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_CERT": paths["client.pem"],
        "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY": paths["client.key"],
    }


class _FakePathTransport:
    def __init__(
        self,
        *,
        preflight_error: str | None = None,
        completion_error: str | None = None,
    ) -> None:
        self.preflight_error = preflight_error
        self.completion_error = completion_error
        self.preflight_requests: list[PreflightRequest] = []
        self.catalog_requests: list[CatalogRequest] = []
        self.catalog_response = None
        self.completion_requests: list[CompletionRequest] = []

    def preflight(self, request: PreflightRequest) -> PreflightResponse:
        self.preflight_requests.append(request)
        if self.preflight_error is not None:
            raise RemotePreflightError(self.preflight_error)
        return PreflightResponse(route=request.route, preflight_status="passed")

    def catalog(self, request: CatalogRequest) -> CatalogResponse:
        self.catalog_requests.append(request)
        if self.preflight_error is not None:
            raise RemoteCatalogError(self.preflight_error)
        if self.catalog_response is not None:
            return self.catalog_response
        raise AssertionError("catalog response is not needed in this test")

    def complete(self, request: CompletionRequest) -> CompletionResponse:
        self.completion_requests.append(request)
        if self.completion_error is not None:
            raise RemoteCompletionError(self.completion_error, indeterminate=True)
        return CompletionResponse(route=request.route, content="done")

    def close(self) -> None:
        return None


def _router(
    tmp_path: Path,
    *,
    first_error: str | None = None,
    second_error: str | None = None,
    first_completion_error: str | None = None,
    environment: dict[str, str] | None = None,
) -> tuple[ExecutorNetworkPathRouter, dict[str, _FakePathTransport], list[str]]:
    env = environment or _host_environment(tmp_path)
    transports: dict[str, _FakePathTransport] = {}
    construction_order: list[str] = []
    errors = {
        "ygg_vlan_primary": first_error,
        "tailscale_fallback": second_error,
    }

    def factory(path: ResolvedExecutorPath) -> _FakePathTransport:
        construction_order.append(path.path_profile)
        transport = _FakePathTransport(
            preflight_error=errors[path.path_profile],
            completion_error=(
                first_completion_error
                if path.path_profile == "ygg_vlan_primary"
                else None
            ),
        )
        transports[path.path_profile] = transport
        return transport

    policy_source = (
        Path(__file__).resolve().parents[2] / DEFAULT_EXECUTOR_NETWORK_POLICY_PATH
    )
    policy = yaml.safe_load(policy_source.read_text(encoding="utf-8"))
    policy["endpoint_references"]["ygg_codex_tailnet"] = {
        "endpoint_env": "MODEL_ACCESS_CODEX_REMOTE_ENDPOINT"
    }
    policy["authentication_profiles"]["ygg_tailscale_serve"] = {
        "mode": "tailscale_serve_app_capability"
    }
    policy["path_profiles"]["tailscale_fallback"] = {
        "adapter": "tailscale_serve_https",
        "endpoint_ref": "host_config.ygg_codex_tailnet",
        "authentication_profile_ref": "host_config.ygg_tailscale_serve",
        "caller_policy_ref": "policy.product_channel_actions",
    }
    policy["executor_path_policies"]["profile.codex_remote_host"]["order"] = [
        "ygg_vlan_primary",
        "tailscale_fallback",
    ]
    policy_path = tmp_path / "executor_network_paths.yaml"
    policy_path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    router = ExecutorNetworkPathRouter(
        policy_path=policy_path,
        environment=env,
        transport_factory=factory,
    )
    return router, transports, construction_order


def test_path_order_is_configuration_driven(tmp_path: Path) -> None:
    router, transports, construction_order = _router(tmp_path)
    try:
        result = router.preflight(_request())
    finally:
        router.close()

    assert construction_order == ["ygg_vlan_primary", "tailscale_fallback"]
    assert transports["ygg_vlan_primary"].preflight_requests == [_request()]
    assert transports["tailscale_fallback"].preflight_requests == []
    assert result.receipt.selected_path_profile == "ygg_vlan_primary"
    assert result.receipt.failure_before_selection is None


@pytest.mark.parametrize(
    "failure_code",
    [
        "PATH_UNAVAILABLE",
        "CONNECT_TIMEOUT",
        "PREFLIGHT_TIMEOUT",
        "PATH_AUTHENTICATION_FAILED",
    ],
)
def test_only_typed_path_local_failures_use_next_path(
    tmp_path: Path, failure_code: str
) -> None:
    request = _request()
    router, transports, _ = _router(tmp_path, first_error=failure_code)
    try:
        result = router.preflight(request)
    finally:
        router.close()

    assert transports["ygg_vlan_primary"].preflight_requests == [request]
    assert transports["tailscale_fallback"].preflight_requests == [request]
    assert result.response.route == request.route
    assert result.receipt.executor_profile == "profile.codex_remote_host"
    assert result.receipt.selected_path_profile == "tailscale_fallback"
    assert result.receipt.failure_before_selection == failure_code
    assert result.receipt.route == request.route
    assert result.receipt.reasoning_effort == request.reasoning_effort
    assert result.receipt.capability_intent == request.capability_intent


@pytest.mark.parametrize(
    "terminal_code",
    [
        "serve_capability_required",
        "serve_capability_invalid",
        "invalid_request",
        "route_not_declared",
        "structured_output_unavailable",
        "preflight_route_mismatch",
    ],
)
def test_terminal_preflight_failures_do_not_use_another_path(
    tmp_path: Path, terminal_code: str
) -> None:
    router, transports, _ = _router(tmp_path, first_error=terminal_code)
    try:
        with pytest.raises(RemotePreflightError, match=terminal_code):
            router.preflight(_request())
    finally:
        router.close()

    assert len(transports["ygg_vlan_primary"].preflight_requests) == 1
    assert transports["tailscale_fallback"].preflight_requests == []


def test_received_http_denial_uses_no_other_path_provider_or_completion(
    tmp_path: Path,
) -> None:
    request = CompletionRequest(
        route=_request().route,
        reasoning_effort="low",
        capability_intent=CompletionCapabilityIntent(),
        trusted_instructions="Use the configured executor.",
        user_input="Say hello.",
    )
    fallback_route = CompletionRouteIdentity(
        provider="ollama",
        model="llama3.1:8b",
        transport_id="ollama_http",
    )
    router, transports, _ = _router(tmp_path, first_error="preflight_http_403")
    try:
        with pytest.raises(RemotePreflightError, match="preflight_http_403"):
            select_preflight_route(
                request,
                fallback_route=fallback_route,
                fallback_requirement="fallback_policy_selected",
                policy_authority="profile.product_runtime",
                transport=router,
            )
    finally:
        router.close()

    assert len(transports["ygg_vlan_primary"].preflight_requests) == 1
    assert transports["tailscale_fallback"].preflight_requests == []
    assert all(not transport.completion_requests for transport in transports.values())


def test_missing_path_configuration_fails_before_transport_creation(tmp_path: Path) -> None:
    environment = _host_environment(tmp_path)
    del environment["MODEL_ACCESS_CODEX_VLAN_ENDPOINT"]
    created: list[str] = []

    def factory(path: ResolvedExecutorPath) -> _FakePathTransport:
        created.append(path.path_profile)
        return _FakePathTransport()

    policy_path = Path(__file__).resolve().parents[2] / DEFAULT_EXECUTOR_NETWORK_POLICY_PATH
    with pytest.raises(ExecutorNetworkConfigurationError, match="path_configuration_missing"):
        ExecutorNetworkPathRouter(
            policy_path=policy_path,
            environment=environment,
            transport_factory=factory,
        )
    assert created == []


def test_ambiguous_completion_does_not_fail_over(tmp_path: Path) -> None:
    router, transports, _ = _router(
        tmp_path,
        first_completion_error="execution_indeterminate",
    )
    try:
        preflight = router.preflight(_request())
        with pytest.raises(RemoteCompletionError, match="execution_indeterminate"):
            router.complete_selected_path(
                _complete_request(), receipt=preflight.receipt
            )
        with pytest.raises(RemoteCompletionError, match="executor_path_preflight_required"):
            router.complete_selected_path(
                _complete_request(), receipt=preflight.receipt
            )
    finally:
        router.close()

    assert len(transports["ygg_vlan_primary"].completion_requests) == 1
    assert transports["tailscale_fallback"].completion_requests == []


@pytest.mark.parametrize(
    ("changed_request", "changed_receipt"),
    [
        ("route", False),
        ("reasoning_effort", False),
        ("capability_intent", False),
        (None, True),
    ],
)
def test_path_receipt_is_bound_and_consumed_before_completion(
    tmp_path: Path, changed_request: str | None, changed_receipt: bool
) -> None:
    router, transports, _ = _router(tmp_path)
    try:
        preflight = router.preflight(_request())
        request = _complete_request()
        receipt = preflight.receipt
        if changed_request == "route":
            changed_route = CompletionRouteIdentity(
                provider="openai", model="gpt-5.6-luna", transport_id="codex_cli"
            )
            request = request.model_copy(update={"route": changed_route})
        elif changed_request == "reasoning_effort":
            request = request.model_copy(update={"reasoning_effort": "low"})
        elif changed_request == "capability_intent":
            changed_intent = CompletionCapabilityIntent(
                structured_output=False,
                native_tools=False,
                literal_system_role_required=False,
                max_output_tokens_required=False,
            )
            request = request.model_copy(
                update={"capability_intent": changed_intent, "output_schema": None}
            )
        elif changed_receipt:
            receipt = ExecutorPathReceipt(
                executor_profile=preflight.receipt.executor_profile,
                selected_path_profile="tailscale_fallback",
                route=preflight.receipt.route,
                reasoning_effort=preflight.receipt.reasoning_effort,
                capability_intent=preflight.receipt.capability_intent,
                failure_before_selection=preflight.receipt.failure_before_selection,
                receipt_id=preflight.receipt.receipt_id,
            )
        with pytest.raises(RemoteCompletionError, match="executor_path_preflight_mismatch"):
            router.complete_selected_path(request, receipt=receipt)
    finally:
        router.close()

    assert transports["ygg_vlan_primary"].completion_requests == []
    assert transports["tailscale_fallback"].completion_requests == []


def test_catalog_uses_next_path_only_for_typed_path_failure(tmp_path: Path) -> None:
    router, transports, _ = _router(tmp_path, first_error="PATH_UNAVAILABLE")
    transports["tailscale_fallback"].catalog_response = SimpleNamespace(
        snapshot=SimpleNamespace(transport_id="codex_cli")
    )
    request = CatalogRequest(transport_id="codex_cli")
    try:
        response = router.catalog(request)
    finally:
        router.close()

    assert response.snapshot.transport_id == "codex_cli"
    assert transports["ygg_vlan_primary"].catalog_requests == [request]
    assert transports["tailscale_fallback"].catalog_requests == [request]


def test_catalog_http_denial_does_not_use_another_path(tmp_path: Path) -> None:
    request = CatalogRequest(transport_id="codex_cli")
    router, transports, _ = _router(tmp_path, first_error="catalog_http_403")
    try:
        with pytest.raises(RemoteCatalogError, match="catalog_http_403"):
            router.catalog(request)
    finally:
        router.close()

    assert transports["ygg_vlan_primary"].catalog_requests == [request]
    assert transports["tailscale_fallback"].catalog_requests == []


def test_path_receipts_are_logical_and_secret_free(tmp_path: Path) -> None:
    environment = _host_environment(tmp_path)
    secret_values = tuple(environment.values()) + ("raw-auth-claim-secret",)
    router, _, _ = _router(tmp_path, first_error="CONNECT_TIMEOUT", environment=environment)
    try:
        result = router.preflight(_request())
        receipt_json = json.dumps(result.receipt.to_dict(), sort_keys=True)
        receipt_repr = repr(result.receipt)
    finally:
        router.close()

    assert result.receipt.selected_path_profile == "tailscale_fallback"
    assert result.receipt.failure_before_selection == "CONNECT_TIMEOUT"
    assert "profile.codex_remote_host" in receipt_json
    assert all(secret not in receipt_json + receipt_repr for secret in secret_values)
    assert "endpoint" not in receipt_json
    assert "authorization" not in receipt_json.lower()
    assert "claims" not in receipt_json.lower()


@pytest.mark.parametrize(
    "authorization_error", ["serve_capability_invalid", "preflight_http_403"]
)
def test_authorization_failure_does_not_trigger_provider_fallback(
    authorization_error: str,
) -> None:
    route = _request().route
    request = CompletionRequest(
        route=route,
        reasoning_effort="low",
        capability_intent=CompletionCapabilityIntent(structured_output=True),
        trusted_instructions="Use the configured executor.",
        user_input="Say hello.",
        output_schema={"type": "object"},
    )
    fallback_route = CompletionRouteIdentity(
        provider="ollama",
        model="llama3.1:8b",
        transport_id="ollama_http",
    )

    class _DeniedPreflight:
        calls = 0

        def preflight(self, _request: PreflightRequest) -> None:
            self.calls += 1
            raise RemotePreflightError(authorization_error)

    transport = _DeniedPreflight()
    with pytest.raises(RemotePreflightError, match=authorization_error):
        select_preflight_route(
            request,
            fallback_route=fallback_route,
            fallback_requirement="fallback_policy_selected",
            policy_authority="profile.product_runtime",
            transport=transport,
        )

    assert transport.calls == 1


def test_exhausted_path_failures_do_not_select_another_provider(tmp_path: Path) -> None:
    request = _complete_request()
    router, transports, _ = _router(
        tmp_path,
        first_error="PATH_UNAVAILABLE",
        second_error="CONNECT_TIMEOUT",
    )
    fallback_route = CompletionRouteIdentity(
        provider="ollama",
        model="llama3.1:8b",
        transport_id="ollama_http",
    )
    try:
        with pytest.raises(RemotePreflightError, match="CONNECT_TIMEOUT"):
            select_preflight_route(
                request,
                fallback_route=fallback_route,
                fallback_requirement="fallback_policy_selected",
                policy_authority="profile.product_runtime",
                transport=router,
            )
    finally:
        router.close()

    assert transports["ygg_vlan_primary"].preflight_requests == [
        PreflightRequest(
            route=request.route,
            reasoning_effort=request.reasoning_effort,
            capability_intent=request.capability_intent,
        )
    ]
    assert transports["tailscale_fallback"].preflight_requests == [
        PreflightRequest(
            route=request.route,
            reasoning_effort=request.reasoning_effort,
            capability_intent=request.capability_intent,
        )
    ]


def test_unclassified_path_preflight_does_not_select_another_provider(
    tmp_path: Path,
) -> None:
    request = _complete_request()
    router, transports, _ = _router(tmp_path, first_error="preflight_unavailable")
    fallback_route = CompletionRouteIdentity(
        provider="ollama", model="llama3.1:8b", transport_id="ollama_http"
    )
    try:
        with pytest.raises(RemotePreflightError, match="path_preflight_unclassified"):
            select_preflight_route(
                request,
                fallback_route=fallback_route,
                fallback_requirement="fallback_policy_selected",
                policy_authority="profile.product_runtime",
                transport=router,
            )
    finally:
        router.close()

    assert transports["ygg_vlan_primary"].preflight_requests
    assert transports["tailscale_fallback"].preflight_requests == []
