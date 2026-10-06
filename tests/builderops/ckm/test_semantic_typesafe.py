from __future__ import annotations

from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import socket

from click.testing import CliRunner
from fastapi.testclient import TestClient
import httpx
import httpx2
import pytest

from app.builderops.cli import builderops
from app.builderops.ckm.judgment import BuilderCkmJudgmentClient, BuilderCkmJudgmentResolver
from app.builderops.ckm.semantic import associate_unlinked_artifacts, reapply_confirmation_receipts
from app.builderops.ckm.store import CkmStore
from app.model_access.adapter_factory import ModelAccessAdapterFactory
from app.model_access.ckm_judgment_contract import (
    CKM_JUDGMENT_REQUEST_BYTES, ckm_judgment_request,
)
from app.model_access.ckm_judgment_executor import BUILDER_TYPESAFE_PROFILE_PATH, BuilderTypeSafeExecutor
from app.model_access.codex_executor_service import create_codex_executor_app
from app.model_access.typesafe_adapter import TypeSafeAdapter
from app.ops.host_secret_bootstrap import create_marr_typesafe_bws_reader


CAPABILITY = "model-access.example/cap/complete"
FAKE_KEY = "synthetic-server-only-key-5768"
MARR_BWS_IDENTITY = ("marr-dev", "dev/typesafe.api-key")
ENV = {
    "PKM_ENVIRONMENT": "dev", "BUILDER_CKM_MARR_ENDPOINT": "https://ckm.example.internal",
    "BUILDER_CKM_MARR_CA_BUNDLE": "/synthetic/builder-ca.pem",
    "BUILDER_CKM_MARR_CLIENT_CERT": "/synthetic/builder-cert.pem",
    "BUILDER_CKM_MARR_CLIENT_KEY": "/synthetic/builder-key.pem",
}


class _FakeCheckOperation:
    operation_id = "fixture-typesafe-check"

    def finish(self, _evidence):
        pass


class _FakeSecretController:
    @contextmanager
    def admit(self, _operation, _channel):
        yield _FakeCheckOperation()


def _headers(channel="builder", action="ckm_judgment"):
    return {"Tailscale-App-Capabilities": json.dumps({CAPABILITY: [{"channel": channel, "actions": [action]}]})}


def _artifact(store, *, index=0, excerpt="Synthetic evidence for retrieval"):
    return store.upsert_artifact(
        source_ref=f"docs/private-synthetic-{index}.md", artifact_kind="document", source="repo_docs",
        watermark=f"synthetic:{index}",
        provenance=json.dumps({"payload_summary": excerpt, "source_ref": "must-never-leave",
                               "private_body": "PRIVATE-REPOSITORY-TEXT"}),
    )


def _capability(store, *, index=0):
    return store.upsert_capability(
        identity_key=f"fixture:typed:{index}", name=f"Retrieval {index}",
        definition="Find related evidence.", existence_provenance="synthetic fixture", lifecycle="confirmed",
    )


class Provider:
    def __init__(self, *, behavior="success", confidence=0.9, after_send=None):
        self.behavior, self.confidence, self.after_send = behavior, confidence, after_send
        self.calls = []

    def send(self, request):
        self.calls.append(request)
        if self.after_send:
            self.after_send()
        if self.behavior == "ambiguous":
            raise httpx2.ReadTimeout("sensitive provider diagnostic " + FAKE_KEY)
        if self.behavior == "rejected":
            return httpx2.Response(429, text=FAKE_KEY)
        if self.behavior == "malformed":
            return httpx2.Response(200, text=FAKE_KEY)
        payload = json.loads(request.content)
        answers = {}
        for question_id, question in payload["questions"].items():
            options = list(question["criteria"])
            choice = "no_match" if self.behavior == "no_match" else options[0]
            answers[question_id] = {
                "type": "choice", "choice": choice, "confidence": self.confidence,
                "probabilities": {option: float(option == choice) for option in options},
            }
        if self.behavior == "unknown_choice":
            answers[next(iter(answers))]["choice"] = "candidate_8"
        if self.behavior == "missing_answer":
            answers.pop(next(iter(answers)))
        if self.behavior == "extra_answer":
            answers["capability_8"] = next(iter(answers.values()))
        if self.behavior == "mixed_low_no_match":
            answer = answers[next(iter(answers))]
            answer.update(choice="no_match", confidence=0.59)
            answer["probabilities"] = {option: float(option == "no_match") for option in answer["probabilities"]}
        body = {"model": payload["model"], "answers": answers, "usage": {}}
        if self.behavior == "wrong_model":
            body["model"] = "jev-9.99.0"
        return httpx2.Response(200, json=body)


@contextmanager
def _rig(monkeypatch, tmp_path, *, provider=None, mode="accepted_dev", key=FAKE_KEY,
         profile_path=BUILDER_TYPESAFE_PROFILE_PATH, environment=None, mutate_reply=None,
         fail_bws_lookup=False):
    provider = provider or Provider()
    lookups, tls_calls, intent_calls, sent = [], [], [], []

    class FakeTLS:
        def load_cert_chain(self, **kwargs):
            tls_calls.append(kwargs)

    monkeypatch.setattr("app.builderops.ckm.judgment.ssl.create_default_context", lambda **kw: FakeTLS())
    monkeypatch.setattr("app.ops.host_secret_bootstrap.sys.platform", "darwin")
    monkeypatch.setattr(socket, "create_connection", lambda *a, **kw: pytest.fail("no sockets in fake proof"))

    class Reader:
        def lookup(self, project, identity):
            lookups.append((project, identity))
            if fail_bws_lookup:
                raise RuntimeError(FAKE_KEY + "Synthetic CKM input")
            return key

    executor = BuilderTypeSafeExecutor(
        mode=mode, profile_path=profile_path, bws_reader=Reader(),
        secret_controller=_FakeSecretController(),
        acceptance_state_directory=tmp_path / "typesafe-acceptance",
        adapter=TypeSafeAdapter(transport_factory=lambda: httpx2.MockTransport(provider.send),
                                max_request_bytes=CKM_JUDGMENT_REQUEST_BYTES),
    )
    root = Path(__file__).resolve().parents[3]
    app = create_codex_executor_app(
        codex_executor=object(), ollama_adapter=object(), serve_capability_name=CAPABILITY,
        adapter_factory=ModelAccessAdapterFactory.from_declared_sources(
            adapters_path=root / "docs/settings/models/adapters.yaml",
            provider_census_path=root / "docs/settings/models/providers.yaml",
        ),
        builder_judgment_executor=executor,
    )
    store = CkmStore(tmp_path / "ckm.sqlite3")
    store.ensure_schema()
    with TestClient(app, client=("127.0.0.1", 12345)) as server:
        def bridge(request):
            sent.append(request)
            response = server.post(request.url.path, content=request.content,
                                   headers={"Content-Type": "application/json", **_headers()})
            if mutate_reply:
                return httpx.Response(200, json=mutate_reply(response.json()))
            return httpx.Response(response.status_code, content=response.content)

        resolver = BuilderCkmJudgmentResolver(
            environment=ENV if environment is None else environment,
            client_factory=lambda env: BuilderCkmJudgmentClient(env, transport=httpx.MockTransport(bridge)),
        )
        resolve = resolver.resolve

        def record(request):
            intent_calls.append(request)
            return resolve(request)

        monkeypatch.setattr(resolver, "resolve", record)
        monkeypatch.setattr("app.builderops.ckm.semantic.BuilderCkmJudgmentResolver", lambda **kw: resolver)
        yield store, provider, lookups, tls_calls, intent_calls, sent, server, executor


def test_production_call_uses_builder_judgment_resolver(monkeypatch, tmp_path):
    with _rig(monkeypatch, tmp_path) as (store, provider, lookups, tls, intents, sent, *_):
        _artifact(store)
        _capability(store)
        result = associate_unlinked_artifacts(store)
        assert result.proposed == 1 and result.status == "ok"
        assert len(intents) == len(sent) == len(provider.calls) == len(lookups) == 1
        assert intents[0].intent.fallback_requirement == "fallback_forbidden"
        assert intents[0].intent.side_effect_class == "derived_candidate_evidence"
        assert intents[0].role_profile == "ckm_semantic"
        edge = store.list_evidence_edges()[0]
        assert (edge.provider, edge.model, edge.lifecycle, edge.extraction_method) == (
            "typesafe", "jev-1.13.0", "candidate", "inferred",
        )
        assert store.get_watermark("semantic_association")
        assert tls == [{"certfile": ENV["BUILDER_CKM_MARR_CLIENT_CERT"], "keyfile": ENV["BUILDER_CKM_MARR_CLIENT_KEY"]}]
        assert lookups == [MARR_BWS_IDENTITY]


@pytest.mark.parametrize("behavior", ["success", "no_match", "unknown_choice", "missing_answer", "extra_answer"])
def test_choice_is_limited_to_supplied_candidates(monkeypatch, tmp_path, behavior):
    with _rig(monkeypatch, tmp_path, provider=Provider(behavior=behavior)) as (store, provider, *_):
        _artifact(store)
        _capability(store)
        store.set_watermark("semantic_association", "prior")
        result = associate_unlinked_artifacts(store)
        assert result.proposed == int(behavior == "success")
        assert len(provider.calls) == 1
        wire = provider.calls[0].content.decode()
        assert "source_ref" not in wire and "PRIVATE-REPOSITORY-TEXT" not in wire
        assert "docs/private" not in wire and FAKE_KEY not in wire
        if behavior != "success":
            assert store.list_evidence_edges() == []
            assert store.get_watermark("semantic_association") == "prior"


@pytest.mark.parametrize("case", ["caller_missing", "disabled", "key_missing", "malformed", "wrong_model",
                                  "degraded", "low_confidence", "stale_artifact", "stale_capability", "ambiguous"])
def test_unavailable_or_stale_judgment_writes_zero_edges(monkeypatch, tmp_path, case):
    provider = Provider(behavior=case if case in {"malformed", "wrong_model", "ambiguous"} else "success",
                        confidence=0.59 if case == "low_confidence" else 0.9)
    with _rig(
        monkeypatch, tmp_path, provider=provider, key="" if case == "key_missing" else FAKE_KEY,
        mode="disabled" if case == "disabled" else "accepted_dev",
        environment={"PKM_ENVIRONMENT": "dev"} if case == "caller_missing" else None,
        mutate_reply=(lambda body: {**body, "degraded": True}) if case == "degraded" else None,
    ) as (store, _, lookups, *_):
        _artifact(store)
        _capability(store)
        store.set_watermark("semantic_association", "prior")
        if case == "stale_artifact":
            provider.after_send = lambda: _artifact(store, excerpt="Changed while inference was in flight")
        elif case == "stale_capability":
            provider.after_send = lambda: _capability(store, index=1)
        result = associate_unlinked_artifacts(store)
        assert result.proposed == 0
        assert store.list_evidence_edges() == []
        assert store.get_watermark("semantic_association") == "prior"
        assert len(provider.calls) == (0 if case in {"caller_missing", "disabled", "key_missing"} else 1)
        if case in {"caller_missing", "disabled"}:
            assert lookups == []
        assert FAKE_KEY not in repr(result)


def test_existing_candidate_confirmation_and_rebuild_contract(monkeypatch, tmp_path):
    with _rig(monkeypatch, tmp_path) as (store, *_):
        _artifact(store)
        _capability(store)
        assert associate_unlinked_artifacts(store).proposed == 1
        edge = store.list_evidence_edges()[0]
        result = CliRunner().invoke(builderops, ["--db-path", str(store.db_path), "ckm", "confirm-edge", edge.id])
        assert result.exit_code == 0, result.output
        assert len(store.list_builderops_receipts("ckm_edge_confirmed")) == 1
        store.rebuild(retained_public_ids=store.active_public_ids())
        _artifact(store)
        _capability(store)
        assert reapply_confirmation_receipts(store) == 1
        restored = store.list_evidence_edges()[0]
        assert restored.lifecycle == "confirmed" and restored.public_id == edge.public_id


def test_builder_caller_uses_dev_only_marr_binding_without_provider_key(monkeypatch, tmp_path):
    for index, environment in enumerate((
        {**ENV, "PKM_ENVIRONMENT": "test"}, {**ENV, "PKM_ENVIRONMENT": "prod"},
        {"PKM_ENVIRONMENT": "dev", "MODEL_ACCESS_CODEX_VLAN_CLIENT_KEY": "product-only",
         "TYPESAFE_API_KEY": FAKE_KEY},
    )):
        with _rig(monkeypatch, tmp_path / str(index), environment=environment) as (store, provider, lookups, *rest):
            _artifact(store)
            _capability(store)
            assert associate_unlinked_artifacts(store).proposed == 0
            assert provider.calls == lookups == []
            assert rest[2] == []  # no MARR request


def test_supported_model_profile_swap_preserves_candidate_contract(monkeypatch, tmp_path):
    bodies = []
    for index, model in enumerate(("jev-1.13.0", "jev-1.14.0")):
        policy = json.loads(BUILDER_TYPESAFE_PROFILE_PATH.read_text())
        policy["profiles"]["builder.ckm_association.v1"]["model"] = model
        policy["supported_models"] = [model]
        profile = tmp_path / f"profile-{index}.json"
        profile.write_text(json.dumps(policy))
        with _rig(monkeypatch, tmp_path / str(index), profile_path=profile) as (store, provider, _, _, _, sent, *_):
            _artifact(store)
            _capability(store)
            assert associate_unlinked_artifacts(store).proposed == 1
            bodies.append(sent[0].content)
            assert store.list_evidence_edges()[0].model == model
            assert json.loads(provider.calls[0].content)["model"] == model
    assert bodies[0] == bodies[1]


def test_bws_lookup_failure_fails_before_provider_dispatch(monkeypatch, tmp_path):
    with _rig(monkeypatch, tmp_path, fail_bws_lookup=True) as (store, provider, lookups, *_):
        _artifact(store)
        _capability(store)
        store.set_watermark("semantic_association", "prior")
        assert associate_unlinked_artifacts(store).proposed == 0
        assert lookups == [("marr-dev", "dev/typesafe.api-key")]
        assert provider.calls == []
        assert store.list_evidence_edges() == []
        assert store.get_watermark("semantic_association") == "prior"


def test_exact_marr_reader_malformed_keychain_token_stops_builder_adapter(
    monkeypatch, tmp_path
):
    monkeypatch.setattr("app.ops.host_secret_bootstrap.sys.platform", "darwin")
    provider = Provider()
    client_factory_calls = []

    def client_factory():
        client_factory_calls.append(True)
        return object()

    reader = create_marr_typesafe_bws_reader(
        environment={
            "BWS_READER_PROJECT": "marr-dev",
            "BWS_PROJECT_ID": "00000000-0000-4000-8000-000000000001",
            "BWS_ORGANIZATION_ID": "00000000-0000-4000-8000-000000000002",
        },
        keychain_lookup=lambda _service, _account: "malformed token",
        client_factory=client_factory,
    )
    request = ckm_judgment_request({
        "candidates": [{"id": "candidate_1", "kind": "document", "excerpt": "Synthetic"}],
        "capabilities": [{"id": "capability_1", "kind": "capability", "excerpt": "Synthetic"}],
    })
    executor = BuilderTypeSafeExecutor(
        mode="accepted_dev",
        bws_reader=reader,
        secret_controller=_FakeSecretController(),
        acceptance_state_directory=tmp_path / "typesafe-acceptance",
        adapter=TypeSafeAdapter(
            transport_factory=lambda: httpx2.MockTransport(provider.send),
            max_request_bytes=CKM_JUDGMENT_REQUEST_BYTES,
        ),
    )
    result = executor.execute(request)
    assert result.outcome == "unavailable_before_send"
    assert client_factory_calls == [] and provider.calls == []


@pytest.mark.parametrize("case", ["unknown", "unpinned", "unsupported", "wrong_owner"])
def test_unconfigured_model_profile_fails_before_dispatch(monkeypatch, tmp_path, case):
    policy = json.loads(BUILDER_TYPESAFE_PROFILE_PATH.read_text())
    if case == "unknown": policy["selected_profile"] = "unknown"
    if case == "unpinned": policy["profiles"]["builder.ckm_association.v1"]["model"] = "jev-latest"
    if case == "unsupported": policy["supported_models"] = ["jev-0.0.1"]
    if case == "wrong_owner": policy["owner"] = "product"
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps(policy))
    with _rig(monkeypatch, tmp_path, profile_path=profile) as (store, provider, lookups, *_):
        _artifact(store)
        _capability(store)
        store.set_watermark("semantic_association", "prior")
        assert associate_unlinked_artifacts(store).proposed == 0
        assert provider.calls == lookups == []
        assert store.get_watermark("semantic_association") == "prior"


def test_bounded_projection_sends_only_curated_eight_by_eight(monkeypatch, tmp_path):
    with _rig(monkeypatch, tmp_path) as (store, provider, *_):
        for index in range(10):
            _artifact(store, index=index, excerpt="å" * 500)
            _capability(store, index=index)
        assert associate_unlinked_artifacts(store).proposed == 8
        wire = json.loads(provider.calls[0].content)
        assert len(wire["state"]["candidates"]) == len(wire["state"]["capabilities"]) == 8
        assert all(set(record) == {"id", "kind", "excerpt"} for record in wire["state"]["candidates"])
        assert all(len(record["excerpt"].encode()) <= 500 for record in wire["state"]["candidates"])
        assert 4096 < len(provider.calls[0].content) <= CKM_JUDGMENT_REQUEST_BYTES


@pytest.mark.parametrize("case", ["source_ref", "prompt", "unknown", "oversize_excerpt", "ninth", "questions", "request_bytes"])
def test_request_allowlist_and_size_limit_fail_before_dispatch(monkeypatch, tmp_path, case):
    state = {"candidates": [{"id": "candidate_1", "kind": "document", "excerpt": "Synthetic"}],
             "capabilities": [{"id": "capability_1", "kind": "capability", "excerpt": "Synthetic"}]}
    request = ckm_judgment_request(state).model_dump(mode="json")
    if case in {"source_ref", "prompt", "unknown"}: request["state"]["candidates"][0][case] = "FORBIDDEN"
    if case == "oversize_excerpt": request["state"]["candidates"][0]["excerpt"] = "å" * 251
    if case == "ninth": request["state"]["candidates"] *= 9
    if case == "questions": request["questions"][0]["instructions"] = "Arbitrary prompt"
    if case == "request_bytes": request["padding"] = "x" * 13000
    with _rig(monkeypatch, tmp_path) as (_, provider, lookups, _, _, _, server, _):
        response = server.post("/v1/ckm-judgment", json=request, headers=_headers())
        assert response.status_code in {413, 422}
        assert lookups == provider.calls == []


def test_mixed_uncertain_abstention_writes_zero_edges(monkeypatch, tmp_path):
    with _rig(monkeypatch, tmp_path, provider=Provider(behavior="mixed_low_no_match")) as (store, provider, *_):
        _artifact(store)
        _capability(store)
        _capability(store, index=1)
        store.set_watermark("semantic_association", "prior")
        result = associate_unlinked_artifacts(store)
        assert result.proposed == 0 and result.discarded == 1
        assert len(provider.calls) == 1
        assert store.list_evidence_edges() == []
        assert store.get_watermark("semantic_association") == "prior"


@pytest.mark.parametrize("behavior", ["success", "ambiguous", "rejected"])
def test_acceptance_once_never_rearms_after_possible_send(monkeypatch, tmp_path, behavior):
    with _rig(monkeypatch, tmp_path, mode="acceptance_once", provider=Provider(behavior=behavior)) as (store, provider, lookups, *_):
        _artifact(store)
        _capability(store)
        associate_unlinked_artifacts(store)
        _artifact(store, index=1)
        assert associate_unlinked_artifacts(store).proposed == 0
        assert len(provider.calls) == len(lookups) == 1


def test_acceptance_once_is_atomic_for_competing_calls(monkeypatch, tmp_path):
    request = ckm_judgment_request({
        "candidates": [{"id": "candidate_1", "kind": "document", "excerpt": "Synthetic"}],
        "capabilities": [{"id": "capability_1", "kind": "capability", "excerpt": "Synthetic"}],
    })
    with _rig(monkeypatch, tmp_path, mode="acceptance_once") as (_, provider, lookups, _, _, _, _, executor):
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: executor.execute(request).outcome, range(2)))
        assert sorted(outcomes) == ["success", "unavailable_before_send"]
        assert len(provider.calls) == len(lookups) == 1


def test_acceptance_once_refuses_a_new_executor_after_restart(monkeypatch, tmp_path):
    request = ckm_judgment_request({
        "candidates": [{"id": "candidate_1", "kind": "document", "excerpt": "Synthetic"}],
        "capabilities": [{"id": "capability_1", "kind": "capability", "excerpt": "Synthetic"}],
    })
    state = tmp_path / "typesafe-acceptance"
    with _rig(monkeypatch, tmp_path, mode="acceptance_once") as (
        _, provider, lookups, _, _, _, _, first_executor
    ):
        assert first_executor.execute(request).outcome == "success"
        assert len(provider.calls) == len(lookups) == 1

        second_lookups = []

        class Reader:
            def lookup(self, project, identity):
                second_lookups.append((project, identity))
                return FAKE_KEY

        second_provider = Provider()
        second_executor = BuilderTypeSafeExecutor(
            mode="acceptance_once",
            bws_reader=Reader(),
            secret_controller=_FakeSecretController(),
            acceptance_state_directory=state,
            adapter=TypeSafeAdapter(
                transport_factory=lambda: httpx2.MockTransport(second_provider.send),
                max_request_bytes=CKM_JUDGMENT_REQUEST_BYTES,
            ),
        )
        assert second_executor.execute(request).outcome == "unavailable_before_send"
        assert second_lookups == [] and second_provider.calls == []


@pytest.mark.parametrize("case", ["unknown_key", "oversize", "kind", "duplicate_id", "prompt"])
def test_builder_client_rejects_invalid_request_before_marr(monkeypatch, tmp_path, case):
    from llm_contract import SystemOneJudgmentRequest

    request = ckm_judgment_request({
        "candidates": [{"id": "candidate_1", "kind": "document", "excerpt": "Synthetic"}],
        "capabilities": [{"id": "capability_1", "kind": "capability", "excerpt": "Synthetic"}],
    }).model_dump(mode="json")
    if case == "unknown_key": request["state"]["candidates"][0]["source_ref"] = "private-file"
    if case == "oversize": request["state"]["candidates"][0]["excerpt"] = "å" * 251
    if case == "kind": request["state"]["candidates"][0]["kind"] = "prompt"
    if case == "duplicate_id": request["state"]["candidates"] *= 2
    if case == "prompt": request["questions"][0]["instructions"] = "Unexpected prompt"
    with _rig(monkeypatch, tmp_path) as (_, provider, lookups, _, _, sent, *_):
        client = BuilderCkmJudgmentClient(ENV, transport=httpx.MockTransport(
            lambda _: pytest.fail("invalid candidate payload reached MARR")
        ))
        try:
            assert client.judge(SystemOneJudgmentRequest.model_validate(request)).outcome == "unavailable_before_send"
        finally:
            client.close()
        assert provider.calls == lookups == sent == []
