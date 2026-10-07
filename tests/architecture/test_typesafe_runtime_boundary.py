"""Production admission and key ownership for the two bounded MARR judgment callers."""

import ast
import json
from contextlib import contextmanager
from pathlib import Path
import socket

from fastapi.testclient import TestClient
import httpx2
import pytest

from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.ckm_judgment_contract import ckm_judgment_request
from app.model_access.ckm_judgment_executor import BUILDER_TYPESAFE_PROFILE_PATH, BuilderTypeSafeExecutor
from app.model_access.codex_executor_service import create_codex_executor_app
from app.model_access.product_judgment_contract import product_intent_request
from app.model_access.typesafe_adapter import TypeSafeAdapter
from app.model_access.typesafe_judgment_executor import PRODUCT_TYPESAFE_PROFILE_PATH, ProductTypeSafeExecutor
from app.ops.host_secret_contract import UndeclaredSecretConsumerError, load_host_secret_contract


MARR_BWS_IDENTITY = ("non-prod", "dev/typesafe.api-key")


class _FakeCheckOperation:
    operation_id = "fixture-typesafe-check"

    def finish(self, _evidence):
        pass


class _FakeSecretController:
    @contextmanager
    def admit(self, _operation, _channel):
        yield _FakeCheckOperation()


def _request():
    return ckm_judgment_request({
        "candidates": [{"id": "candidate_1", "kind": "document", "excerpt": "Synthetic evidence"}],
        "capabilities": [{"id": "capability_1", "kind": "capability", "excerpt": "Synthetic capability"}],
    })


def _executors(monkeypatch):
    monkeypatch.setattr("app.ops.host_secret_bootstrap.sys.platform", "darwin")
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("no live socket"))
    lookups, sent = [], []
    key = "synthetic-runtime-server-only-key"

    class Reader:
        def lookup(self, project, identity):
            lookups.append((project, identity))
            return key

    def provider(request):
        sent.append(request)
        payload = json.loads(request.content)
        answers = {}
        for question_id, question in payload["questions"].items():
            choices = list(question["criteria"])
            answers[question_id] = {"type": "choice", "choice": choices[0], "confidence": 0.9,
                                    "probabilities": {option: float(option == choices[0]) for option in choices}}
        return httpx2.Response(200, json={"model": payload["model"], "usage": {}, "answers": answers})

    builder = BuilderTypeSafeExecutor(
        mode="accepted_dev", bws_reader=Reader(),
        secret_controller=_FakeSecretController(),
        adapter=TypeSafeAdapter(transport_factory=lambda: httpx2.MockTransport(provider), max_request_bytes=12288),
    )
    product = ProductTypeSafeExecutor(
        mode="accepted_dev", bws_reader=Reader(),
        secret_controller=_FakeSecretController(),
        adapter=TypeSafeAdapter(transport_factory=lambda: httpx2.MockTransport(provider)),
    )
    return builder, product, lookups, sent, key


def test_runtime_key_stays_on_marr_and_callers_keep_separate_policy(monkeypatch):
    contract = load_host_secret_contract()
    for consumer in ("builderops-ckm-semantic", "codex", "claude"):
        with pytest.raises(UndeclaredSecretConsumerError):
            contract.require_declared(channel="dev", consumer=consumer, secret="typesafe.api-key")
    builder, _, lookups, sent, key = _executors(monkeypatch)
    result = builder.execute(_request())
    assert result.outcome == "success" and len(sent) == len(lookups) == 1
    assert lookups == [MARR_BWS_IDENTITY]
    assert key not in result.model_dump_json()
    assert result.selection.profile_id == "builder.ckm_association.v1"
    assert result.judgment.provenance.model == result.selection.model


def test_product_and_builder_keep_separate_typesafe_authorities(monkeypatch):
    builder, product, lookups, sent, _ = _executors(monkeypatch)
    # A policy file owned by the other consumer cannot reach credential lookup.
    wrong_builder = BuilderTypeSafeExecutor(mode="accepted_dev", profile_path=PRODUCT_TYPESAFE_PROFILE_PATH,
                                            keychain_lookup=lambda *_: pytest.fail("wrong owner reached key"))
    wrong_product = ProductTypeSafeExecutor(mode="accepted_dev", profile_path=BUILDER_TYPESAFE_PROFILE_PATH,
                                            keychain_lookup=lambda *_: pytest.fail("wrong owner reached key"))
    assert wrong_builder.execute(_request()).outcome == "unavailable_before_send"
    assert wrong_product.execute(product_intent_request("Synthetic")).outcome == "unavailable_before_send"
    root = Path(__file__).resolve().parents[2]
    capability = "model-access.example/cap/complete"
    app = create_codex_executor_app(
        codex_executor=object(), ollama_adapter=object(), serve_capability_name=capability,
        adapter_factory=ModelAccessAdapterFactory.from_declared_sources(
            adapters_path=root / "docs/settings/models/adapters.yaml",
            provider_census_path=root / "docs/settings/models/providers.yaml",
        ),
        builder_judgment_executor=builder, product_judgment_executor=product,
    )
    cases = [("builder", "ckm_judgment", "/v1/ckm-judgment", _request()),
             ("product", "judgment", "/v1/judgment", product_intent_request("Synthetic"))]
    with TestClient(app, client=("127.0.0.1", 12345)) as client:
        for channel, action, route, request in cases:
            for wrong_channel, wrong_action in (("product" if channel == "builder" else "builder", action),
                                                 (channel, "judgment" if action == "ckm_judgment" else "ckm_judgment")):
                headers = {"Tailscale-App-Capabilities": json.dumps({capability: [{"channel": wrong_channel, "actions": [wrong_action]}]})}
                response = client.post(route, json=request.model_dump(mode="json"), headers=headers)
                assert response.status_code == 403
        assert lookups == sent == []
        for channel, action, route, request in cases:
            headers = {"Tailscale-App-Capabilities": json.dumps({capability: [{"channel": channel, "actions": [action]}]})}
            result = client.post(route, json=request.model_dump(mode="json"), headers=headers).json()
            assert result["outcome"] == "success"
            assert result["selection"]["profile_id"].startswith(channel + ".")
    assert len(lookups) == len(sent) == 2


def test_builder_ckm_imports_no_product_judgment_policy_or_client():
    forbidden = ("app.components.llm", "app.model_access.product_judgment_contract",
                 "app.model_access.codex_remote_transport", "app.model_access.executor_network_policy",
                 "app.model_access.typesafe_judgment_executor", "app.model_access.typesafe_adapter")
    for path in (Path("app/builderops/ckm/semantic.py"), Path("app/builderops/ckm/judgment.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            imports = [node.module or ""] if isinstance(node, ast.ImportFrom) else (
                [item.name for item in node.names] if isinstance(node, ast.Import) else [])
            assert not any(name.startswith(forbidden) for name in imports), path
