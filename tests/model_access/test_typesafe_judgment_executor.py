from __future__ import annotations

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


CAPABILITY = "model-access.example/cap/complete"
FAKE_KEY = "synthetic-typesafe-test-credential-5766"
INTENT = "Consider two possible plans without changing anything."


def _headers(channel: str = "product", action: str = "judgment") -> dict[str, str]:
    return {
        "Tailscale-App-Capabilities": json.dumps(
            {CAPABILITY: [{"channel": channel, "actions": [action]}]}
        )
    }


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
):
    monkeypatch.setattr("app.ops.host_secret_bootstrap.sys.platform", "darwin")
    lookups = []

    def lookup(service: str, account: str) -> str:
        lookups.append((service, account))
        return key

    executor = ProductTypeSafeExecutor(
        mode=mode,
        runtime_channel=runtime_channel,
        profile_path=profile_path,
        adapter=adapter or TypeSafeAdapter(
            transport_factory=lambda: httpx2.MockTransport(provider.handle)
        ),
        keychain_lookup=lookup,
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
        serve_capability_name=CAPABILITY,
        product_judgment_executor=executor,
    )
    return app, lookups, executor


def _call(app, payload: dict[str, Any] | None = None, **kwargs: Any):
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        return client.post(
            "/v1/judgment",
            json=payload or product_intent_request(INTENT).model_dump(mode="json"),
            headers=kwargs.pop("headers", _headers()),
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

        client = CodexRemoteTransport(
            endpoint="https://executor.example.ts.net", transport=httpx.MockTransport(bridge)
        )
        result = client.judge_product_intent(INTENT)
        client.close()
    assert result.outcome == "success"
    assert result.selection is not None and result.judgment is not None
    assert result.selection.model == result.judgment.provenance.model == "jev-1.13.0"
    assert result.selection.provider == result.judgment.provenance.provider == "typesafe"
    assert result.selection.sdk_version == TYPESAFE_SDK_VERSION == "0.7.2"
    assert len(sent) == len(provider.calls) == len(lookups) == 1
    assert lookups == [("yggdrasil.host-secrets", "dev:marr-server-dev:typesafe.api-key")]
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


@pytest.mark.parametrize("mode", ["accepted_dev", "acceptance_once"])
@pytest.mark.parametrize("stage", ["metadata", "factory", "tls", "http_client", "sdk_client"])
def test_adapter_setup_failure_is_presend_and_closes_owned_transport(
    monkeypatch, caplog, mode, stage
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
    app, lookups, _ = _app(provider, monkeypatch, mode=mode, adapter=adapter)
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


@pytest.mark.parametrize(
    ("channel", "action"),
    [
        ("builder", "judgment"),
        ("product", "complete"),
        ("product", "catalog"),
        ("product", "preflight"),
    ],
)
def test_product_judgment_requires_own_channel_and_action(monkeypatch, channel, action) -> None:
    provider = Provider()
    app, lookups, _ = _app(provider, monkeypatch)
    assert _call(app, headers=_headers(channel, action)).status_code == 403
    assert _call(app, headers={}).status_code == 403
    with TestClient(app, client=("192.168.50.5", 12345)) as client:
        assert (
            client.post(
                "/v1/judgment",
                json=product_intent_request(INTENT).model_dump(mode="json"),
                headers=_headers(),
            ).status_code
            == 403
        )
    assert provider.calls == lookups == []


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


def test_one_call_acceptance_is_consumed_atomically_even_on_timeout(monkeypatch) -> None:
    provider = Provider("read_timeout")
    _, lookups, executor = _app(provider, monkeypatch, mode="acceptance_once")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(executor.execute, [product_intent_request(INTENT)] * 2))
    assert sorted(r.outcome for r in results) == [
        "outcome_unknown_after_dispatch",
        "unavailable_before_send",
    ]
    assert len(provider.calls) == len(lookups) == 1


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
def test_product_client_never_retries_ambiguous_remote_outcome(error) -> None:
    calls = []

    def fail(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        raise error(FAKE_KEY + INTENT)

    client = CodexRemoteTransport(
        endpoint="https://executor.example.ts.net", transport=httpx.MockTransport(fail)
    )
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
