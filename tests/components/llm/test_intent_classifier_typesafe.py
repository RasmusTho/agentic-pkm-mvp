"""Actual canvas -> Product client -> authenticated MARR -> pinned SDK, fake provider only."""
from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient
import httpx
import httpx2
import pytest
import yaml

import app.api.routes.canvas as canvas
import app.components.llm.intent_classifier as classifier
from app.api.app import app as product_app
from app.health_contract import WRITE_BLOCKED_STATES
from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.codex_executor_service import create_codex_executor_app
from app.model_access.codex_remote_transport import CodexRemoteTransport
from app.model_access.executor_network_policy import resolve_executor_paths
from app.model_access.product_judgment_contract import (
    ProductJudgmentResult, encode_product_request, product_intent_request,
)
from app.model_access.typesafe_adapter import TypeSafeAdapter
from app.model_access.typesafe_judgment_executor import ProductTypeSafeExecutor
from app.panel.confirmation import (
    ConfirmIdempotencyStore, ConfirmRequest, PanelConfirmationService, ProposalStore,
    SameTurnExecutionError,
)
from app.settings.models import InstanceSettings, LLMRoutingSettings, SettingsBundle
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard


class _FakeCheckOperation:
    operation_id = "fixture-component-judgment-check"

    def finish(self, _evidence) -> None:
        pass


class _FakeSecretController:
    @contextmanager
    def admit(self, _operation: str, _channel: str):
        yield _FakeCheckOperation()


@pytest.fixture
def judgment_path(monkeypatch, tmp_path):
    calls, sent, lookups, bws_lookups = [], [], [], []
    state = {"intent_class": "exploratory", "action_type": "unknown", "failure": None,
             "intent_confidence": 0.9, "action_confidence": 0.9, "probability": 0.9}

    def provider(request):
        calls.append(request)
        if state["failure"] == "timeout":
            raise httpx2.ReadTimeout("private provider details")
        if state["failure"] == "rejected":
            return httpx2.Response(429, text="private provider details")
        if state["failure"] == "malformed":
            return httpx2.Response(200, text="private provider details")
        payload = json.loads(request.content)
        answers = {}
        for key, question in payload["questions"].items():
            choice = state[key]
            probability = state.get("action_probability", state["probability"]) if key == "action_type" else state["probability"]
            answers[key] = {
                "type": "choice", "choice": choice,
                "confidence": state["intent_confidence" if key == "intent_class" else "action_confidence"],
                "probabilities": {
                    k: probability if k == choice else (1 - probability) / (len(question["criteria"]) - 1)
                    for k in question["criteria"]
                },
            }
        result = {"model": payload["model"], "answers": answers,
                  "usage": {"input_tokens": 10, "output_tokens": 2}}
        failure = state["failure"]
        if failure == "wrong_model":
            result["model"] = "jev-9.99.0"
        elif failure == "missing":
            del answers["action_type"]
        elif failure == "foreign":
            answers["other"] = answers.pop("intent_class")
        elif failure == "wrong_kind":
            answers["intent_class"] = {"type": "noul", "noul": 0.9}
        elif failure == "extra":
            answers["intent_class"]["private"] = "private provider details"
        elif failure == "nan":
            answers["intent_class"]["confidence"] = float("nan")
        elif failure == "bad_distribution":
            answers["intent_class"]["probabilities"] = {"exploratory": 0.9}
        elif failure == "duplicate":
            return httpx2.Response(200, content='{"model":"jev-0.0.0",' + json.dumps(result)[1:])
        return httpx2.Response(200, content=json.dumps(result))

    monkeypatch.setattr(
        "app.ops.host_secret_bootstrap.sys", SimpleNamespace(platform="darwin")
    )

    def lookup(service, account):
        lookups.append((service, account))
        return "synthetic-test-credential"

    class SyntheticBwsReader:
        def lookup(self, project, identity):
            bws_lookups.append((project, identity))
            if (project, identity) != ("non-prod", "dev/typesafe.api-key"):
                raise AssertionError("unexpected synthetic BWS identity")
            return "synthetic-test-api-key"

    profile = tmp_path / "profile.json"
    profile.write_bytes(Path("config/model_access/product_typesafe_profile.json").read_bytes())
    executor = ProductTypeSafeExecutor(
        mode="accepted_dev", runtime_channel="dev", profile_path=profile,
        adapter=TypeSafeAdapter(transport_factory=lambda: httpx2.MockTransport(provider)),
        keychain_lookup=lookup,
        bws_reader=SyntheticBwsReader(),
        secret_controller=_FakeSecretController(),
    )
    factory = ModelAccessAdapterFactory.from_declared_sources(
        adapters_path=Path("docs/settings/models/adapters.yaml"),
        provider_census_path=Path("docs/settings/models/providers.yaml"),
    )
    server_app = create_codex_executor_app(
        codex_executor=object(), ollama_adapter=object(), adapter_factory=factory,
        product_judgment_executor=executor,
    )
    policy = tmp_path / "network.yaml"
    policy.write_text(yaml.safe_dump({
        "version": 1,
        "endpoint_references": {"test_endpoint": {"endpoint_env": "TEST_PRODUCT_ENDPOINT"}},
        "authentication_profiles": {"test_auth": {
            "mode": "mutual_tls",
            "ca_bundle_env": "TEST_CA_BUNDLE",
            "client_certificate_env": "TEST_CLIENT_CERT",
            "client_key_env": "TEST_CLIENT_KEY",
        }},
        "path_profiles": {"test_path": {"adapter": "private_https_ingress",
            "endpoint_ref": "host_config.test_endpoint", "authentication_profile_ref": "host_config.test_auth",
            "caller_policy_ref": "policy.vlan_mtls_authenticated_caller"}},
        "executor_path_policies": {"profile.codex_remote_host": {"order": ["test_path"]}},
    }))
    ca_bundle = tmp_path / "test-ca.pem"
    client_certificate = tmp_path / "test-client.pem"
    client_key = tmp_path / "test-client.key"
    for fixture_file in (ca_bundle, client_certificate, client_key):
        fixture_file.write_text("synthetic mTLS test material")
    monkeypatch.setattr(
        "app.model_access.codex_remote_transport._private_ingress_ssl_context",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(classifier, "resolve_executor_paths", lambda profile: resolve_executor_paths(
        profile,
        policy_path=policy,
        environment={
            "TEST_PRODUCT_ENDPOINT": "https://10.42.42.10:8443",
            "TEST_CA_BUNDLE": str(ca_bundle),
            "TEST_CLIENT_CERT": str(client_certificate),
            "TEST_CLIENT_KEY": str(client_key),
        },
    ))
    with TestClient(server_app, client=("127.0.0.1", 12345)) as server:
        def bridge(request):
            sent.append(request)
            if state["failure"] == "unauthorized":
                return httpx.Response(403, json={"error": "mTLS admission rejected"})
            response = server.post(
                request.url.path,
                content=request.content,
                headers={"Content-Type": "application/json"},
            )
            return httpx.Response(response.status_code, content=response.content)

        monkeypatch.setattr(classifier, "CodexRemoteTransport", lambda **kwargs: CodexRemoteTransport(
            **kwargs, transport=httpx.MockTransport(bridge),
        ))
        yield SimpleNamespace(
            state=state,
            calls=calls,
            sent=sent,
            lookups=lookups,
            bws_lookups=bws_lookups,
            profile=profile,
        )


@pytest.fixture
def canvas_path(monkeypatch, tmp_path):
    note = tmp_path / "note.md"
    original = "---\nuuid: synthetic-canvas\n---\n\nPrivate body stays local.\n"
    note.write_text(original)
    monkeypatch.setenv("CANVAS_ENABLED", "1")
    monkeypatch.setattr(canvas, "_get_vault_root_or_picker", lambda **_: tmp_path)
    monkeypatch.setattr(canvas, "_get_vault_root", lambda: tmp_path)
    store = ProposalStore()
    monkeypatch.setattr(canvas, "_panel_proposal_store", store)
    monkeypatch.setattr(canvas, "_coauthor_facade_factory", lambda: pytest.fail("unexpected generation"))
    canvas._sessions.clear()
    canvas._edit_history.clear()
    canvas._undone_history.clear()
    with TestClient(product_app) as client:
        opened = client.post("/api/canvas/sessions", json={"note_path": "note.md"})
        assert opened.status_code == 200, opened.text
        yield SimpleNamespace(client=client, note=note, original=original, store=store,
                              url=f'/api/canvas/sessions/{opened.json()["session_id"]}/coauthor')
    canvas._sessions.clear()
    canvas._edit_history.clear()
    canvas._undone_history.clear()


@pytest.mark.parametrize("clone_profile", ["default", "alternate"])
def test_production_classifier_uses_marr_and_minimal_state(
    monkeypatch, judgment_path, canvas_path, clone_profile,
):
    bundle = SettingsBundle(
        instance=InstanceSettings(llm_routing_profile=clone_profile),
        llm_routing=LLMRoutingSettings(profiles={"alternate": {"default_chat": {"model_id": "gpt-5.6-sol"}}}),
    )
    monkeypatch.setattr("app.components.llm.router.get_settings_bundle", lambda: bundle)
    monkeypatch.setattr("app.components.llm.fabric.get_chat_client", lambda *a, **k: pytest.fail("generic chat"))
    response = canvas_path.client.post(canvas_path.url, json={"intent": "Compare two plans."})
    assert response.status_code == 200 and response.json()["status"] == "exploratory_no_edit"
    assert len(judgment_path.sent) == len(judgment_path.calls) == 1
    assert judgment_path.bws_lookups == [("non-prod", "dev/typesafe.api-key")]
    assert judgment_path.lookups == []
    assert judgment_path.sent[0].url.path == "/v1/judgment"
    neutral = json.loads(judgment_path.sent[0].content)
    wire = json.loads(judgment_path.calls[0].content)
    assert neutral == product_intent_request("Compare two plans.").model_dump(mode="json")
    assert neutral["state"] == wire["state"] == {"intent_text": "Compare two plans."}
    assert set(wire["questions"]) == {"intent_class", "action_type"}
    assert wire["model"] == "jev-1.13.0"
    assert len(judgment_path.sent[0].content) <= 4096 and len(judgment_path.calls[0].content) <= 4096
    assert canvas_path.note.read_text() == canvas_path.original
    assert "Private body" not in judgment_path.sent[0].content.decode()
    assert "authorization" not in judgment_path.sent[0].headers


def test_intent_fixture_uses_synthetic_bws_reader(judgment_path, canvas_path):
    response = canvas_path.client.post(canvas_path.url, json={"intent": "Compare two plans."})

    assert response.status_code == 200
    assert response.json()["status"] == "exploratory_no_edit"
    assert judgment_path.bws_lookups == [("non-prod", "dev/typesafe.api-key")]
    assert judgment_path.lookups == []


def test_typesafe_input_allowlist_and_size_limit(judgment_path, canvas_path):
    cognition = classifier.IntentClassifierCognition()
    for key in ("current_body", "note_title", "vault_path", "prior_turns", "unexpected", "model", "profile"):
        with pytest.raises(TypeError):
            cognition.classify(intent="Compare plans", **{key: "private"})
        response = canvas_path.client.post(canvas_path.url, json={"intent": "Compare plans", key: "private"})
        assert response.status_code == 422
    for value in (None, 1, True, {}, "", "  ", "x" * 2001, "å" * 1001, "\ud800", "\0" * 1000):
        result = cognition.classify(intent=value)
        assert result.intent_class is classifier.IntentClass.UNKNOWN and not result.classified
    assert judgment_path.sent == judgment_path.calls == judgment_path.lookups == []
    # Exact consumer admission limits, including JSON escaping. No networking is
    # necessary to distinguish admission from the SDK's additional wire bound.
    admitted = []
    probe = classifier.IntentClassifierCognition(judgment_client=SimpleNamespace(
        judge_product_intent=lambda text: admitted.append(text) or ProductJudgmentResult(outcome="unavailable_before_send"),
    ))
    overhead = len(encode_product_request(product_intent_request("x"))) - 1
    remaining = 4096 - overhead
    exact = "\0" * (remaining // 6) + "x" * (remaining % 6)
    assert len(encode_product_request(product_intent_request(exact))) == 4096
    for value in ("x" * 2000, "å" * 1000, exact):
        probe.classify(intent=value)
    probe.classify(intent=exact + "x")
    assert admitted == ["x" * 2000, "å" * 1000, exact]


@pytest.mark.parametrize("failure", [
    "timeout", "rejected", "malformed", "wrong_model", "missing", "foreign", "wrong_kind",
    "extra", "nan", "bad_distribution", "duplicate", "unauthorized", "unknown_profile",
    "unknown_intent", "uncertain_action", "low_intent", "low_action", "low_probability", "low_action_probability", "conflict",
])
def test_uncertain_judgment_remains_unknown_without_authorizing_write(
    judgment_path, canvas_path, caplog, failure,
):
    state = judgment_path.state
    state.update(intent_class="governance_bearing", action_type="maturity_transition", failure=failure)
    if failure == "unknown_profile":
        profile = json.loads(judgment_path.profile.read_text())
        profile["selected_profile"] = "unconfigured"
        judgment_path.profile.write_text(json.dumps(profile))
    elif failure == "unknown_intent":
        state["intent_class"] = "unknown"
    elif failure == "uncertain_action":
        state["action_type"] = "unknown"
    elif failure == "low_intent":
        state["intent_confidence"] = 0.799999
    elif failure == "low_action":
        state["action_confidence"] = 0.799999
    elif failure == "low_probability":
        state["probability"] = 0.2
    elif failure == "low_action_probability":
        state["action_probability"] = 0.2
    elif failure == "conflict":
        state["intent_class"] = "co_authoring"
    response = canvas_path.client.post(canvas_path.url, json={"intent": "Change note maturity."})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "unknown_intent_reask" and response.json()["reask"]
    assert canvas_path.note.read_text() == canvas_path.original
    assert canvas_path.store.count_for_artifact("synthetic-canvas") == 0
    assert len(judgment_path.sent) == 1
    assert len(judgment_path.calls) == (0 if failure in {"unknown_profile", "unauthorized"} else 1)
    assert "private provider details" not in caplog.text


def test_governance_judgment_still_requires_confirmation_and_write_guard(
    monkeypatch, judgment_path, canvas_path,
):
    judgment_path.state.update(intent_class="governance_bearing", action_type="maturity_transition",
                               intent_confidence=0.8, action_confidence=0.8, probability=0.8)
    executed = []
    monkeypatch.setattr("app.panel.confirmation.execute_panel_intent", lambda event: executed.append(event))
    response = canvas_path.client.post(canvas_path.url, json={"intent": "Promote this note."})
    assert response.status_code == 409, response.text
    proposal_id = response.json()["intent_id"]
    proposal = canvas_path.store.get(proposal_id)
    assert proposal is not None
    assert proposal.intent_event.payload.actions[0].mapping.trust_verb == "APPLY"
    assert executed == [] and canvas_path.note.read_text() == canvas_path.original
    snapshot = {"state": sorted(WRITE_BLOCKED_STATES)[0], "reason": "maintenance"}
    service = PanelConfirmationService(canvas_path.store, ConfirmIdempotencyStore(),
                                       write_guard=WriteGuard(snapshot_fn=lambda: snapshot))
    request = ConfirmRequest(proposal_id=proposal_id, artifact_id=proposal.artifact_id,
                             action="confirm", idempotency_key="synthetic-confirm")
    with pytest.raises(SameTurnExecutionError):
        service.confirm(request)
    proposal.proposed_at = 0.0
    blocked = service.confirm(request)
    assert blocked.status == "blocked" and canvas_path.store.get(proposal_id) is not None
    assert executed == [] and canvas_path.note.read_text() == canvas_path.original
    # Closing the real staging guard also prevents even a typed governance
    # judgment from creating a second proposal; response remains retryable.
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: snapshot)
    response = canvas_path.client.post(canvas_path.url, json={"intent": "Promote this note."})
    assert response.status_code == 409 and response.json()["detail"]["error"] == "writeguard_blocked"
    assert executed == [] and canvas_path.note.read_text() == canvas_path.original


def test_missing_configuration_and_injected_result_revalidation(monkeypatch, caplog):
    from app.model_access.executor_network_policy import ExecutorNetworkConfigurationError
    from app.eval.classification import ClassificationReplayClient

    def unavailable(*args):
        raise ExecutorNetworkConfigurationError("path_configuration_missing")

    monkeypatch.setattr(classifier, "resolve_executor_paths", unavailable)
    monkeypatch.setattr(classifier, "CodexRemoteTransport", lambda **kw: pytest.fail("dispatch"))
    assert classifier.IntentClassifierCognition().classify(intent="Compare").intent_class is classifier.IntentClass.UNKNOWN
    valid = ClassificationReplayClient('{"intent_class":"co_authoring","action_type":null}').judge_product_intent("Rewrite")
    for failure in ("duplicate", "extra", "identity"):
        raw = valid.model_dump(mode="json")
        if failure == "duplicate":
            raw["judgment"]["answers"].append(raw["judgment"]["answers"][0])
        elif failure == "extra":
            raw["unrequested"] = "private source"
        else:
            raw["judgment"]["provenance"]["model"] = "jev-99.0.0"
        client = SimpleNamespace(judge_product_intent=lambda _: SimpleNamespace(model_dump=lambda **kw: raw))
        result = classifier.IntentClassifierCognition(judgment_client=client).classify(intent="Rewrite")
        assert result.intent_class is classifier.IntentClass.UNKNOWN and not result.classified
    assert "private source" not in caplog.text
