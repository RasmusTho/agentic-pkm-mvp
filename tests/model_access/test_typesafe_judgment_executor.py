from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from importlib.metadata import PackageNotFoundError
import json
import logging
from pathlib import Path
import socket
import ssl
from typing import Any

from fastapi.testclient import TestClient
import httpx
import httpx2
import pytest
import truststore

from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.codex_executor_service import create_codex_executor_app
from app.model_access.codex_remote_transport import CodexRemoteTransport
from app.model_access.product_judgment_contract import product_intent_request
from app.model_access.typesafe_adapter import TYPESAFE_SDK_VERSION, TypeSafeAdapter
from app.model_access.typesafe_judgment_executor import (
    PRODUCT_TYPESAFE_PROFILE_PATH,
    ProductTypeSafeExecutor,
)
from app.ops.host_secret_bootstrap import create_marr_typesafe_bws_reader


FAKE_KEY = "synthetic-typesafe-test-credential-5766"
INTENT = "Consider two possible plans without changing anything."
MARR_BWS_IDENTITY = ("non-prod", "dev/typesafe.api-key")


class _FakeCheckOperation:
    operation_id = "fixture-typesafe-check"

    def finish(self, _evidence) -> None:
        pass


class _FakeSecretController:
    @contextmanager
    def admit(self, _operation: str, _channel: str):
        yield _FakeCheckOperation()


def _headers(_channel: str = "product", _action: str = "judgment") -> dict[str, str]:
    """The VLAN mTLS ingress authenticates callers; no Tailscale claim is sent."""
    return {}


def _vlan_remote_transport(monkeypatch, transport: httpx.BaseTransport) -> CodexRemoteTransport:
    monkeypatch.setattr(
        "app.model_access.codex_remote_transport._private_ingress_ssl_context",
        lambda **_kwargs: object(),
    )
    return CodexRemoteTransport(
        endpoint="https://10.42.42.10:8443",
        path_adapter="private_https_ingress",
        tls_verify="/host-only/ca.pem",
        client_certificate=("/host-only/client.pem", "/host-only/client.key"),
        transport=transport,
    )


def _provider_body(request: httpx2.Request) -> dict[str, Any]:
    payload = json.loads(request.content)
    answers = {}
    for key, question in payload["questions"].items():
        choices = list(question["criteria"])
        answers[key] = {
            "type": "choice",
            "choice": choices[-1],
            "confidence": 0.9,
            "probabilities": {
                choice: (1.0 if choice == choices[-1] else 0.0) for choice in choices
            },
        }
    return {
        "model": payload["model"],
        "answers": answers,
        "usage": {"input_tokens": 100, "output_tokens": 10},
    }


class Provider:
    def __init__(self, behavior: str = "success") -> None:
        self.calls: list[httpx2.Request] = []
        self.behavior = behavior

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.calls.append(request)
        if self.behavior == "connect":
            raise httpx2.ConnectError(FAKE_KEY + INTENT)
        if self.behavior == "connect_timeout":
            raise httpx2.ConnectTimeout(FAKE_KEY + INTENT)
        if self.behavior == "read_timeout":
            raise httpx2.ReadTimeout(FAKE_KEY + INTENT)
        if self.behavior == "write_timeout":
            raise httpx2.WriteTimeout(FAKE_KEY + INTENT)
        if self.behavior == "lost_response":
            raise httpx2.RemoteProtocolError(FAKE_KEY + INTENT)
        if self.behavior == "rejected":
            return httpx2.Response(429, text=FAKE_KEY + INTENT, headers={"retry-after": "0"})
        if self.behavior == "redirect":
            return httpx2.Response(307, headers={"location": "https://attacker.invalid"})
        if self.behavior == "malformed":
            return httpx2.Response(200, text=FAKE_KEY + INTENT)
        if self.behavior == "oversize":
            return httpx2.Response(200, text="x" * 17000)
        body = _provider_body(request)
        if self.behavior == "wrong_model":
            body["model"] = "jev-9.99.0"
        if self.behavior == "extra":
            body["provider"] = FAKE_KEY
        if self.behavior == "answer_extra":
            body["answers"]["intent_class"]["question_id"] = "shadowed-extra"
        if self.behavior == "wrong_choice":
            body["answers"]["intent_class"]["choice"] = "not-requested"
        if self.behavior == "wrong_question":
            body["answers"]["other"] = body["answers"].pop("intent_class")
        if self.behavior == "nan":
            body["answers"]["intent_class"]["confidence"] = float("nan")
        if self.behavior == "duplicate":
            return httpx2.Response(200, content='{"model":"jev-0.0.0",' + json.dumps(body)[1:])
        return httpx2.Response(200, content=json.dumps(body))


def _app(
    provider: Provider,
    monkeypatch: pytest.MonkeyPatch,
    *,
    key: str = FAKE_KEY,
    mode: str = "accepted_dev",
    profile_path: Path = PRODUCT_TYPESAFE_PROFILE_PATH,
    runtime_channel: str = "dev",
    adapter: TypeSafeAdapter | None = None,
    bws_reader=None,
    acceptance_state_directory: Path | None = None,
):
    monkeypatch.setattr("app.ops.host_secret_bootstrap.sys.platform", "darwin")
    lookups = []

    class Reader:
        def lookup(self, project: str, identity: str) -> str:
            lookups.append((project, identity))
            return key

    executor = ProductTypeSafeExecutor(
        mode=mode,
        runtime_channel=runtime_channel,
        profile_path=profile_path,
        adapter=adapter or TypeSafeAdapter(
            transport_factory=lambda: httpx2.MockTransport(provider.handle)
        ),
        bws_reader=Reader() if bws_reader is None else bws_reader,
        secret_controller=_FakeSecretController(),
        acceptance_state_directory=acceptance_state_directory,
    )
    root = Path(__file__).resolve().parents[2]
    factory = ModelAccessAdapterFactory.from_declared_sources(
        adapters_path=root / "docs/settings/models/adapters.yaml",
        provider_census_path=root / "docs/settings/models/providers.yaml",
    )
    app = create_codex_executor_app(
        codex_executor=object(),
        ollama_adapter=object(),  # type: ignore[arg-type]
        adapter_factory=factory,
        product_judgment_executor=executor,
    )
    return app, lookups, executor


def _call(app, payload: dict[str, Any] | None = None, **kwargs: Any):
    # Match the Product client's UTF-8 wire representation. HTTPX's json= defaults
    # can escape Unicode, crossing the wire limit before the intent-byte check.
    body = json.dumps(
        payload or product_intent_request(INTENT).model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        return client.post(
            "/v1/judgment",
            content=body,
            headers={"Content-Type": "application/json", **kwargs.pop("headers", _headers())},
            **kwargs,
        )


def test_executor_dispatches_one_bounded_system_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = Provider()
    app, lookups, _ = _app(provider, monkeypatch)
    sent = []
    with TestClient(app, client=("127.0.0.1", 12345)) as server:

        def bridge(request: httpx.Request) -> httpx.Response:
            sent.append(request)
            response = server.post(
                request.url.path,
                content=request.content,
                headers={"Content-Type": "application/json", **_headers()},
            )
            return httpx.Response(response.status_code, content=response.content)

        client = _vlan_remote_transport(monkeypatch, httpx.MockTransport(bridge))
        result = client.judge_product_intent(INTENT)
        client.close()
    assert result.outcome == "success"
    assert result.selection is not None and result.judgment is not None
    assert result.selection.model == result.judgment.provenance.model == "jev-1.13.0"
    assert result.selection.provider == result.judgment.provenance.provider == "typesafe"
    assert result.selection.sdk_version == TYPESAFE_SDK_VERSION == "0.7.2"
    assert len(sent) == len(provider.calls) == len(lookups) == 1
    assert lookups == [MARR_BWS_IDENTITY]
    wire = provider.calls[0]
    assert str(wire.url) == "https://api.typesafe.ai/v1/systemone"
    assert wire.headers["authorization"] == "Bearer " + FAKE_KEY
    assert json.loads(wire.content)["state"] == {"intent_text": INTENT}
    assert len(wire.content) <= 4096 and len(sent[0].content) <= 4096
    assert FAKE_KEY not in sent[0].content.decode() + result.model_dump_json()
    assert "authorization" not in sent[0].headers


@pytest.mark.parametrize("key", ["", "bad key with spaces", "nul\x00value", "nönascii"])
def test_missing_typesafe_credential_fails_before_provider_call(monkeypatch, caplog, key) -> None:
    provider = Provider()
    app, lookups, _ = _app(provider, monkeypatch, key=key)
    with caplog.at_level(logging.DEBUG):
        response = _call(app)
    assert response.json()["outcome"] == "unavailable_before_send"
    assert len(lookups) == 1 and provider.calls == []
    assert INTENT not in response.text + caplog.text
    if key:
        assert key not in response.text + caplog.text


def test_bws_lookup_failure_fails_before_provider_call(monkeypatch, caplog) -> None:
    provider = Provider()

    class FailingReader:
        def lookup(self, _project: str, _identity: str) -> str:
            raise RuntimeError(FAKE_KEY + INTENT)

    app, lookups, _ = _app(provider, monkeypatch, bws_reader=FailingReader())
    with caplog.at_level(logging.DEBUG):
        response = _call(app)
    assert response.json()["outcome"] == "unavailable_before_send"
    assert len(lookups) == 0
    assert provider.calls == []
    assert FAKE_KEY + INTENT not in response.text + caplog.text


def test_exact_marr_reader_malformed_keychain_token_stops_product_adapter(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr("app.ops.host_secret_bootstrap.sys.platform", "darwin")
    provider = Provider()
    client_factory_calls = []

    def client_factory():
        client_factory_calls.append(True)
        return object()

    reader = create_marr_typesafe_bws_reader(
        environment={
            "BWS_READER_PROJECT": "non-prod",
            "BWS_PROJECT_ID": "00000000-0000-4000-8000-000000000001",
            "BWS_ORGANIZATION_ID": "00000000-0000-4000-8000-000000000002",
        },
        keychain_lookup=lambda _service, _account: "malformed token",
        client_factory=client_factory,
    )
    executor = ProductTypeSafeExecutor(
        mode="accepted_dev",
        bws_reader=reader,
        secret_controller=_FakeSecretController(),
        acceptance_state_directory=tmp_path / "typesafe-acceptance",
        adapter=TypeSafeAdapter(
            transport_factory=lambda: httpx2.MockTransport(provider.handle)
        ),
    )
    result = executor.execute(product_intent_request(INTENT))
    assert result.outcome == "unavailable_before_send"
    assert client_factory_calls == [] and provider.calls == []


@pytest.mark.parametrize("mode", ["accepted_dev", "acceptance_once"])
@pytest.mark.parametrize("stage", ["metadata", "factory", "tls", "http_client", "sdk_client"])
def test_adapter_setup_failure_is_presend_and_closes_owned_transport(
    monkeypatch, tmp_path, caplog, mode, stage
) -> None:
    """GH5791-R4180661727: default TLS setup is before the possible-send boundary."""
    provider = Provider()
    calls = {"factory": 0, "failure": 0, "close": 0, "network": 0}

    def fail(*args, **kwargs):
        calls["failure"] += 1
        error = PackageNotFoundError if stage == "metadata" else ssl.SSLError
        raise error(FAKE_KEY + INTENT)

    def close():
        calls["close"] += 1

    def factory():
        calls["factory"] += 1
        if stage == "factory":
            fail()
        transport = httpx2.MockTransport(provider.handle)
        monkeypatch.setattr(transport, "close", close)
        return transport

    def forbidden_network(*args, **kwargs):
        calls["network"] += 1
        pytest.fail("setup regression must never open a socket")

    monkeypatch.setattr(socket, "create_connection", forbidden_network)
    if stage == "tls":
        # Keep the real default HTTPTransport constructor; replace its OS TLS seam.
        monkeypatch.setattr(truststore, "SSLContext", fail)
        adapter = TypeSafeAdapter()
    else:
        adapter = TypeSafeAdapter(transport_factory=factory)
    targets = {
        "metadata": "app.model_access.typesafe_adapter.version",
        "http_client": "app.model_access.typesafe_adapter.httpx2.Client",
        "sdk_client": "app.model_access.typesafe_adapter.TypeSafeClient",
    }
    if stage in targets:
        monkeypatch.setattr(targets[stage], fail)
    app, lookups, _ = _app(
        provider,
        monkeypatch,
        mode=mode,
        adapter=adapter,
        acceptance_state_directory=tmp_path / "typesafe-acceptance",
    )
    with caplog.at_level(logging.DEBUG):
        response = _call(app)
        assert response.status_code == 200
        assert response.json()["outcome"] == "unavailable_before_send"
        if mode == "acceptance_once":
            # Even a pre-send setup failure consumes the explicit one-call allowance.
            assert _call(app).json()["outcome"] == "unavailable_before_send"
    assert calls == {
        "factory": int(stage not in {"metadata", "tls"}),
        "failure": 1,
        "close": int(stage in {"http_client", "sdk_client"}),
        "network": 0,
    }
    assert len(lookups) == 1 and provider.calls == []
    assert FAKE_KEY not in response.text + caplog.text
    assert INTENT not in response.text + caplog.text


@pytest.mark.parametrize(
    ("behavior", "outcome"),
    [
        ("connect", "unavailable_before_send"),
        ("connect_timeout", "unavailable_before_send"),
        ("read_timeout", "outcome_unknown_after_dispatch"),
        ("write_timeout", "outcome_unknown_after_dispatch"),
        ("lost_response", "outcome_unknown_after_dispatch"),
        ("rejected", "provider_rejected"),
        ("redirect", "provider_rejected"),
        ("malformed", "response_invalid"),
        ("wrong_model", "response_invalid"),
        ("extra", "response_invalid"),
        ("answer_extra", "response_invalid"),
        ("wrong_choice", "response_invalid"),
        ("wrong_question", "response_invalid"),
        ("nan", "response_invalid"),
        ("duplicate", "response_invalid"),
        ("oversize", "response_invalid"),
    ],
)
def test_provider_outcomes_are_terminal_and_never_retried(
    monkeypatch, caplog, behavior, outcome
) -> None:
    provider = Provider(behavior)
    app, _, _ = _app(provider, monkeypatch)
    with caplog.at_level(logging.DEBUG):
        response = _call(app)
    assert response.status_code == 200 and response.json()["outcome"] == outcome
    assert len(provider.calls) == 1
    assert response.json()["judgment"] is None
    assert FAKE_KEY not in response.text + caplog.text
    assert INTENT not in response.text + caplog.text


@pytest.mark.parametrize(
    "field",
    [
        "current_body",
        "title",
        "vault_path",
        "prior_turns",
        "model",
        "profile",
        "endpoint",
        "headers",
        "api_key",
        "parameters",
    ],
)
def test_request_allowlist_and_size_limit_fail_before_dispatch(monkeypatch, field) -> None:
    provider = Provider()
    app, lookups, _ = _app(provider, monkeypatch)
    payload = product_intent_request(INTENT).model_dump(mode="json")
    payload["state"][field] = "forbidden"
    assert _call(app, payload).status_code == 422
    payload = product_intent_request(INTENT).model_dump(mode="json")
    payload[field] = "forbidden"
    assert _call(app, payload).status_code == 422
    payload = product_intent_request(INTENT).model_dump(mode="json")
    payload["state"]["intent_text"] = "å" * 1001
    assert _call(app, payload).status_code == 422
    payload["state"]["intent_text"] = "x" * 4097
    assert _call(app, payload).status_code == 413
    payload = product_intent_request(INTENT).model_dump(mode="json")
    payload["questions"][0]["instructions"] = "A caller-provided prompt"
    assert _call(app, payload).status_code == 422
    assert provider.calls == lookups == []


def test_product_judgment_needs_no_tailscale_claim_over_vlan_ingress(monkeypatch) -> None:
    provider = Provider()
    app, lookups, _ = _app(provider, monkeypatch)
    assert _call(app, headers={}).status_code == 200
    with TestClient(app, client=("192.168.50.5", 12345)) as client:
        assert (
            client.post(
                "/v1/judgment",
                json=product_intent_request(INTENT).model_dump(mode="json"),
            ).status_code
            == 403
        )
    assert len(provider.calls) == len(lookups) == 1


def test_supported_model_profile_swap_keeps_request_contract(monkeypatch, tmp_path) -> None:
    provider = Provider()
    policy = json.loads(PRODUCT_TYPESAFE_PROFILE_PATH.read_text())
    path = tmp_path / "product-profile.json"
    path.write_text(json.dumps(policy))
    app, _, _ = _app(provider, monkeypatch, profile_path=path)
    before = _call(app).json()
    # Future exact release is deliberately fake-backed, not claimed as live support.
    policy["supported_models"].append("jev-1.14.0")
    policy["profiles"]["product.canvas_intent.v1"]["model"] = "jev-1.14.0"
    path.write_text(json.dumps(policy))
    after = _call(app).json()
    assert before["selection"]["model"] == "jev-1.13.0"
    assert after["selection"]["model"] == after["judgment"]["provenance"]["model"] == "jev-1.14.0"
    first, second = (json.loads(call.content) for call in provider.calls)
    assert first.pop("model") != second.pop("model")
    assert first == second
    assert before["selection"]["sdk_version"] == after["selection"]["sdk_version"]


@pytest.mark.parametrize(
    "fault", ["missing", "unknown", "unpinned", "unsupported", "owner", "endpoint", "duplicate"]
)
def test_unconfigured_model_profile_fails_before_dispatch(monkeypatch, tmp_path, fault) -> None:
    provider = Provider()
    policy = json.loads(PRODUCT_TYPESAFE_PROFILE_PATH.read_text())
    path = tmp_path / "product-profile.json"
    if fault == "unknown":
        policy["selected_profile"] = "not-configured"
    elif fault == "unpinned":
        policy["profiles"]["product.canvas_intent.v1"]["model"] = "jev-latest"
    elif fault == "unsupported":
        policy["profiles"]["product.canvas_intent.v1"]["model"] = "jev-8.0.0"
    elif fault == "owner":
        policy["owner"] = "builder"
    elif fault == "endpoint":
        policy["endpoint"] = "https://attacker.invalid"
    if fault != "missing":
        path.write_text(
            json.dumps(policy)
            if fault != "duplicate"
            else '{"owner":"builder",' + json.dumps(policy)[1:]
        )
    app, lookups, _ = _app(provider, monkeypatch, profile_path=path)
    assert _call(app).json()["outcome"] == "unavailable_before_send"
    assert provider.calls == lookups == []


@pytest.mark.parametrize(
    ("mode", "channel"),
    [("disabled", "dev"), ("invalid", "dev"), ("accepted_dev", "test"), ("accepted_dev", "prod")],
)
def test_runtime_acceptance_gate_precedes_secret_and_provider(monkeypatch, mode, channel) -> None:
    provider = Provider()
    app, lookups, _ = _app(provider, monkeypatch, mode=mode, runtime_channel=channel)
    assert _call(app).json()["outcome"] == "unavailable_before_send"
    assert provider.calls == lookups == []


def test_one_call_acceptance_is_consumed_atomically_even_on_timeout(monkeypatch, tmp_path) -> None:
    provider = Provider("read_timeout")
    _, lookups, executor = _app(
        provider,
        monkeypatch,
        mode="acceptance_once",
        acceptance_state_directory=tmp_path / "typesafe-acceptance",
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(executor.execute, [product_intent_request(INTENT)] * 2))
    assert sorted(r.outcome for r in results) == [
        "outcome_unknown_after_dispatch",
        "unavailable_before_send",
    ]
    assert len(provider.calls) == len(lookups) == 1


def test_acceptance_once_refuses_a_new_executor_after_restart(monkeypatch, tmp_path) -> None:
    state = tmp_path / "typesafe-acceptance"
    provider = Provider("read_timeout")
    first, first_lookups, _ = _app(
        provider, monkeypatch, mode="acceptance_once", acceptance_state_directory=state
    )
    assert _call(first).json()["outcome"] == "outcome_unknown_after_dispatch"

    second, second_lookups, _ = _app(
        provider, monkeypatch, mode="acceptance_once", acceptance_state_directory=state
    )
    assert _call(second).json()["outcome"] == "unavailable_before_send"
    assert len(first_lookups) == len(provider.calls) == 1
    assert second_lookups == []


def test_acceptance_once_is_atomic_across_executor_instances(monkeypatch, tmp_path) -> None:
    state = tmp_path / "typesafe-acceptance"
    provider = Provider()
    _, first_lookups, first_executor = _app(
        provider, monkeypatch, mode="acceptance_once", acceptance_state_directory=state
    )
    _, second_lookups, second_executor = _app(
        provider, monkeypatch, mode="acceptance_once", acceptance_state_directory=state
    )
    request = product_intent_request(INTENT)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda executor: executor.execute(request), (first_executor, second_executor)))
    assert sorted(result.outcome for result in results) == [
        "success", "unavailable_before_send",
    ]
    assert len(provider.calls) == len(first_lookups) + len(second_lookups) == 1


def test_acceptance_marker_corruption_fails_closed_before_bws_lookup(monkeypatch, tmp_path) -> None:
    state = tmp_path / "typesafe-acceptance"
    state.mkdir(mode=0o700)
    marker = state / "product.acceptance.json"
    marker.write_text('{"state":"consumed"}', encoding="ascii")
    marker.chmod(0o600)
    provider = Provider()
    app, lookups, _ = _app(
        provider, monkeypatch, mode="acceptance_once", acceptance_state_directory=state
    )
    assert _call(app).json()["outcome"] == "unavailable_before_send"
    assert lookups == [] and provider.calls == []


def test_sdk_environment_cannot_override_owned_profile_or_log_bodies(monkeypatch, caplog) -> None:
    for name, value in {
        "TYPESAFE_API_KEY": "wrong-key",
        "TYPESAFE_DEFAULT_MODEL": "jev-latest",
        "TYPESAFE_BASE_URL": "https://attacker.invalid",
        "TYPESAFE_LOG_LEVEL": "debug",
    }.items():
        monkeypatch.setenv(name, value)
    provider = Provider()
    app, _, _ = _app(provider, monkeypatch)
    logging.getLogger("typesafe_sdk").disabled = False
    with caplog.at_level(logging.DEBUG):
        response = _call(app)
    assert response.json()["outcome"] == "success"
    assert json.loads(provider.calls[0].content)["model"] == "jev-1.13.0"
    assert provider.calls[0].headers["authorization"] == "Bearer " + FAKE_KEY
    assert FAKE_KEY not in caplog.text and INTENT not in caplog.text


@pytest.mark.parametrize(
    "error", [httpx.ReadTimeout, httpx.WriteTimeout, httpx.RemoteProtocolError]
)
def test_product_client_never_retries_ambiguous_remote_outcome(error, monkeypatch) -> None:
    calls = []

    def fail(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise error(FAKE_KEY + INTENT)

    client = _vlan_remote_transport(monkeypatch, httpx.MockTransport(fail))
    assert client.judge_product_intent(INTENT).outcome == "outcome_unknown_after_dispatch"
    assert len(calls) == 1
    client.close()


def test_host_factory_remains_unavailable_without_explicit_dev_server_acceptance(
    monkeypatch,
) -> None:
    def forbidden(**kwargs):
        pytest.fail("disabled factory must not read credentials")

    monkeypatch.setattr(
        "app.model_access.typesafe_judgment_executor.resolve_host_secret_values", forbidden
    )
    for environment in (
        {},
        {"TYPESAFE_API_KEY": FAKE_KEY},
        {"MODEL_ACCESS_PRODUCT_TYPESAFE_MODE": "accepted_dev"},
        {
            "HOST_SECRET_BOOTSTRAP_CHANNEL": "dev",
            "HOST_SECRET_BOOTSTRAP_CONSUMER": "marr-server-dev",
        },
    ):
        executor = ProductTypeSafeExecutor.from_host_environment(environment)
        assert executor.execute(product_intent_request(INTENT)).outcome == "unavailable_before_send"
