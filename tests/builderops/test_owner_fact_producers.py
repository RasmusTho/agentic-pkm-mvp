"""FCA-05 proofs through the authenticated service and real PostgreSQL kernel."""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.builderops.control_plane.auth import CredentialRegistry
from app.builderops.control_plane.service import create_app
from app.builderops.owner_fact_producers import outcome_request_hash, read_owner_binding
from tests.builderops.control_plane.conftest import control_plane_store  # noqa: F401
from tests.ops.test_devui_vm102_runtime_receipts import _bundle, _chain, _component_evidence

pytestmark = pytest.mark.pg
REPO = "example/fixture"
SUBJECT = "github:example/fixture#5404"


class OwnerWriter:
    def __init__(self, root, store, monkeypatch):
        self.root, self.store = root, store
        self.profile = {
            "id": "profile:devui-trial", "version": "1", "repository": REPO,
            "subject_ref": SUBJECT, "source_owner": "builderops_vm102_receipt_source",
            "owner_actor": {"actor_type": "human", "id": "human:owner"},
            "authorization_ref": {"ref": "policy:owner", "version": "1", "authority_epoch": 1},
            "criterion_refs": [{"id": "AC1", "sha256": "a" * 64}, {"id": "AC2", "sha256": "b" * 64}],
            "limitation_refs": [],
            "retention_policy_ref": {"ref": "BuilderOpsReceipt", "version": "1"},
        }
        self.bundle = _bundle()
        self.write_sources()
        monkeypatch.setenv("DEVUI_VM102_RECEIPT_DIR", str(root))
        self.manifest = root / "credentials.json"
        self.credentials = [
            self.entry("owner", "human:owner", "human", ["records:write", "receipts:read", "owner_outcomes:confirm"]),
            self.entry("agent", "agent:builder", "agent", ["records:write", "receipts:read"]),
            self.entry("other", "human:other", "human", ["records:write", "receipts:read", "owner_outcomes:confirm"]),
        ]
        self.write_credentials()
        self.registry = CredentialRegistry(self.manifest)
        self.client = TestClient(create_app(store=store, credentials=self.registry))

    def entry(self, key, principal, kind, scopes):
        return {"id": key, "principal": principal, "principal_kind": kind,
                "secret_ref": "host-secret:" + key,
                "verifier_sha256": hashlib.sha256((key + "-test-only-key").encode()).hexdigest(),
                "token_length": len(key + "-test-only-key"), "scopes": scopes,
                "repositories": [REPO], "rotation_generation": 1}

    def write_credentials(self):
        self.manifest.write_text(json.dumps({"credentials": self.credentials}))

    def write_sources(self):
        self.root.mkdir(exist_ok=True)
        self.chain = _chain(self.bundle)
        self.bundle["prerequisites"]["owner_acceptance_profiles"] = [self.profile]
        for index, receipt in enumerate(self.chain):
            (self.root / f"{index}-runtime.json").write_text(json.dumps(receipt))
        (self.root / "devui-runtime-prerequisites.json").write_text(json.dumps(self.bundle["prerequisites"]))

    def binding(self):
        return read_owner_binding(REPO, SUBJECT, authority_epoch=1)

    def request(self, kind="owner_trial", outcome="tried", **changes):
        binding = self.binding()
        request = {key: copy.deepcopy(binding[key]) for key in (
            "repository", "subject_ref", "source_revision", "candidate_ref", "environment_ref",
            "readiness_receipt_ref", "acceptance_profile_ref", "criterion_refs", "owner_actor",
            "authorization_ref", "limitation_refs", "retention_policy_ref",
        )}
        stamp = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        request.update(fact_kind=kind, outcome=outcome,
                       observed_at=stamp if kind == "owner_trial" else None,
                       decided_at=stamp if kind == "owner_acceptance" else None,
                       observation=[{"criterion_ref": ref, "status": "observed"} for ref in request["criterion_refs"]] if kind == "owner_trial" else None,
                       trial_receipt_ref=None, expected_previous_receipt_id=None,
                       supersedes_receipt_id=None, correction_reason=None)
        request.update(changes)
        return request

    def submit(self, request, key="first", principal="owner", **changes):
        payload = {"contract": "builder_owner_outcome.v1", "request": request,
                   "request_sha256": outcome_request_hash(request), "confirm": "confirm"}
        payload.update(changes)
        return self.client.post("/v1/records", json={"record_type": "BuilderOpsReceipt",
                    "owner_outcome": payload, "idempotency_key": key},
                    headers={"Authorization": "Bearer " + principal + "-test-only-key", "X-BuilderOps-Authority-Epoch": "1"})

    def read(self, key=None):
        params = {"repository": REPO, "subject_ref": SUBJECT}
        if key is not None:
            params["idempotency_key"] = key
        return self.client.get("/v1/receipts/owner-outcomes/current", params=params,
            headers={"Authorization": "Bearer owner-test-only-key"})

    def count(self, table):
        assert table in {"builderops_records", "builderops_receipts", "builderops_idempotency", "builderops_outbox"}
        with self.store._connect() as conn:
            return conn.execute("SELECT count(*) AS n FROM " + table).fetchone()["n"]


@pytest.fixture
def owner_writer(tmp_path, control_plane_store, monkeypatch):  # noqa: F811
    return OwnerWriter(tmp_path, control_plane_store, monkeypatch)


def test_production_writer_is_authorized_version_bound_and_idempotent(owner_writer, monkeypatch):
    w = owner_writer
    request = w.request()
    for principal in ("agent", "other"):
        assert w.submit(request, principal=principal).status_code == 403
    assert w.submit(request, confirm=None).status_code == 400
    assert w.submit(request, confirmation_ref={"principal": "human:owner"}).status_code == 400
    forged = {**request, "recorded_at": datetime.now(timezone.utc).isoformat()}
    assert w.submit(forged).status_code == 400
    stale = copy.deepcopy(request)
    stale["authorization_ref"]["version"] = "stale"
    assert w.submit(stale).status_code == 409
    # The raw production parser must reject duplicate keys before admission.
    raw = json.dumps({"record_type": "BuilderOpsReceipt", "owner_outcome": {"contract": "builder_owner_outcome.v1", "request": request,
        "request_sha256": outcome_request_hash(request), "confirm": "confirm"}, "idempotency_key": "first"})
    raw = raw.replace('"confirm": "confirm"', '"confirm": "confirm", "confirm": "confirm"')
    assert w.client.post("/v1/records", content=raw, headers={"Content-Type": "application/json", "Authorization": "Bearer owner-test-only-key", "X-BuilderOps-Authority-Epoch": "1"}).status_code == 400
    for field, value in (("owner_actor", "human:owner"), ("outcome", {}), ("observed_at", "2030-01-01T00:00:00Z")):
        assert w.submit({**request, field: value}).status_code == 400
    original_now = w.store._database_now
    monkeypatch.setattr(w.store, "_database_now", lambda conn: datetime.now(timezone.utc) - timedelta(seconds=10))
    assert w.submit(request).json()["detail"] == "owner_confirmation_clock_unavailable"
    monkeypatch.setattr(w.store, "_database_now", original_now)
    assert w.count("builderops_records") == 0
    response = w.submit(request)
    assert response.status_code == 200, response.text
    receipt = response.json()["receipt"]
    assert receipt["receipt_body"]["request"] == request
    assert receipt["receipt_body"]["request_sha256"] == outcome_request_hash(request)
    confirmation = receipt["receipt_body"]["confirmation_ref"]
    assert confirmation["request_sha256"] == outcome_request_hash(request)
    assert confirmation["confirmed_at"] <= receipt["receipt_body"]["recorded_at"]
    assert w.submit(request).json()["receipt"] == receipt
    assert w.count("builderops_records") == w.count("builderops_receipts") == w.count("builderops_idempotency") == w.count("builderops_outbox") == 1
    generic = {"envelope": {"repository": REPO, "scope": "owner-outcome", "stack": "builderops", "source_refs": [SUBJECT]},
        "record_id": "ordinary-record", "record_type": "BuilderOpsReceipt", "state": "active", "payload": {}, "idempotency_key": "ordinary-record"}
    assert w.client.post("/v1/records", json=generic, headers={"Authorization": "Bearer agent-test-only-key", "X-BuilderOps-Authority-Epoch": "1"}).status_code == 403
    generic["envelope"]["scope"] = "ordinary"
    generic["idempotency_key"] = "owner-outcome:reserved"
    assert w.client.post("/v1/records", json=generic, headers={"Authorization": "Bearer agent-test-only-key", "X-BuilderOps-Authority-Epoch": "1"}).status_code == 403
    assert w.read("first").json()["receipt"] == receipt
    accepted = w.submit(w.request("owner_acceptance", "accepted", trial_receipt_ref=receipt["id"]), "accepted").json()["receipt"]
    w.credentials[0]["scopes"].remove("owner_outcomes:confirm")
    w.write_credentials()
    withdrawn = w.read("accepted").json()
    assert withdrawn["receipt"] == accepted
    assert withdrawn["facts"]["owner_trial"] is withdrawn["facts"]["owner_acceptance"] is None
    assert withdrawn["projection"]["reason"] == "owner_grant_unavailable"
    w.credentials.append(w.entry("replacement", "human:owner", "human", ["records:write", "receipts:read", "owner_outcomes:confirm"]))
    w.write_credentials()
    recovered = w.read("accepted").json()
    assert recovered["facts"]["owner_acceptance"] == accepted
    assert recovered["projection"]["status"] == "current"


@pytest.mark.parametrize("outcomes", [("accepted", "rejected"), ("accepted", "accepted")])
def test_conflicting_submissions_require_explicit_correction(owner_writer, outcomes):
    w = owner_writer
    trial = w.submit(w.request(), "trial").json()["receipt"]
    requests = [w.request("owner_acceptance", outcome, trial_receipt_ref=trial["id"]) for outcome in outcomes]
    with ThreadPoolExecutor(2) as pool:
        responses = list(pool.map(lambda pair: w.submit(pair[1], pair[0]), zip(("a", "b"), requests)))
    assert sorted(r.status_code for r in responses) == [200, 409]
    loser = next(r for r in responses if r.status_code == 409)
    assert loser.json()["detail"] == "current_receipt_conflict"
    winner_index = next(i for i, r in enumerate(responses) if r.status_code == 200)
    key, request = ("a", "b")[winner_index], requests[winner_index]
    assert w.submit(request, key).json()["receipt"] == responses[winner_index].json()["receipt"]
    assert w.submit({**request, "decided_at": "2026-01-01T00:00:00Z"}, key).json()["detail"] == "idempotency_conflict"
    previous = responses[winner_index].json()["receipt"]["id"]
    correction = w.request("owner_acceptance", "rejected", expected_previous_receipt_id=previous,
        supersedes_receipt_id=previous, correction_reason="owner_correction")
    assert w.submit(correction, "correction", confirm=None).status_code == 400
    assert w.submit(correction, "correction").status_code == 200


@pytest.mark.parametrize("correction_first", [True, False])
def test_acceptance_and_trial_correction_share_serialization(owner_writer, correction_first, monkeypatch):
    from app.builderops.control_plane import owner_outcomes

    w = owner_writer
    old = w.submit(w.request(), "trial").json()["receipt"]["id"]
    acceptance = w.request("owner_acceptance", "accepted", trial_receipt_ref=old)
    correction = w.request(expected_previous_receipt_id=old, supersedes_receipt_id=old, correction_reason="owner_correction")
    held, attempted, release = threading.Event(), threading.Event(), threading.Event()
    lock, fault = owner_outcomes._lock, w.store._fault
    calls = []
    def observed_lock(*args):
        calls.append(args[-1])
        if len(calls) == 2:
            attempted.set()
        return lock(*args)
    def hold_first(_requested, point):
        if point == "before_owner_outcome_commit" and not held.is_set():
            held.set()
            assert release.wait(5)
        return fault(_requested, point)
    monkeypatch.setattr(owner_outcomes, "_lock", observed_lock)
    monkeypatch.setattr(w.store, "_fault", hold_first)
    first, second = ((correction, "correction"), (acceptance, "acceptance")) if correction_first else ((acceptance, "acceptance"), (correction, "correction"))
    with ThreadPoolExecutor(2) as pool:
        a = pool.submit(w.submit, *first)
        assert held.wait(5)
        b = pool.submit(w.submit, *second)
        assert attempted.wait(5)
        release.set()
        responses = [a.result(), b.result()]
    assert calls[0] == calls[1]
    assert responses[0].status_code == 200
    if correction_first:
        assert responses[1].json()["detail"] == "trial_receipt_conflict"
    else:
        accepted = responses[0].json()["receipt"]
        assert responses[1].status_code == 200
        evidence = w.read("acceptance").json()
        assert evidence["receipt"]["id"] == accepted["id"]
        assert evidence["projection"]["status"] == "withdrawn"
        # A delayed rebuild of the actual acceptance intent reads the current
        # production source/chain. The old intent carries no projection state.
        with w.store._connect() as conn:
            intent = conn.execute("SELECT payload FROM builderops_outbox WHERE task_id=%s", (accepted["id"],)).fetchone()["payload"]
        delayed = w.store.get_owner_outcomes(REPO, intent["subject_ref"], idempotency_key="acceptance", grant_reader=w.registry.has_owner_outcome_grant)
        assert delayed["projection"]["status"] == "withdrawn"
    assert w.read().json()["facts"]["owner_acceptance"] is None


@pytest.mark.parametrize("field", ["candidate_ref", "environment_ref", "readiness_receipt_ref", "readiness_expiry"])
def test_changed_candidate_cannot_inherit_trial_or_acceptance(owner_writer, field, monkeypatch):
    w = owner_writer
    trial = w.submit(w.request(), "trial").json()["receipt"]["id"]
    accepted = w.submit(w.request("owner_acceptance", "accepted", trial_receipt_ref=trial), "accepted").json()["receipt"]
    if field == "readiness_expiry":
        from app.builderops import devui_receipts
        from app.builderops.control_plane import owner_outcomes

        observed = datetime.fromisoformat(w.chain[-1]["observed_at"])
        monkeypatch.setenv("DEVUI_VM102_RECEIPT_MAX_AGE_SECONDS", "1")
        monkeypatch.setattr(devui_receipts, "_utc_now", lambda: observed)
        original_lock = owner_outcomes._lock
        def expires_while_waiting(*args):
            original_lock(*args)
            monkeypatch.setattr(devui_receipts, "_utc_now", lambda: observed + timedelta(seconds=2))
        monkeypatch.setattr(owner_outcomes, "_lock", expires_while_waiting)
        result = w.read("accepted").json()
        assert result["facts"]["ready_to_try"] is None
        assert result["facts"]["owner_acceptance"] is None
        assert result["receipt"] == accepted and result["projection"]["status"] == "withdrawn"
        return
    changed = w.request()
    changed[field] = {**changed[field], "changed": "new-source-binding"}
    assert w.submit(changed, "changed").status_code in {400, 409}
    if field == "environment_ref":
        # This source owns only VM102. A foreign target is unavailable, never
        # an admitted E2 carrying the old owner's consent.
        for index, receipt in enumerate(copy.deepcopy(w.chain)):
            receipt["target_vm"]["vmid"] = 103
            (w.root / f"{index}-runtime.json").write_text(json.dumps(receipt))
        assert w.read().status_code == 503
        history = w.read("accepted").json()
        assert history["receipt"] == accepted and history["projection"]["status"] == "unavailable"
        return
    if field == "candidate_ref":
        w.bundle["evidence"]["candidate_identity"]["devui_config_fingerprint"] = "sha256:" + "9" * 64
        for row in w.bundle["evidence"]["topology"]:
            if row["component_id"] == "devui_projection":
                row["source_identity"]["config_fingerprint"] = "sha256:" + "9" * 64
    else:
        w.bundle["evidence"]["observed_at"] = datetime.now(timezone.utc).isoformat()
        for row in w.bundle["evidence"]["topology"]:
            row["observed_at"] = w.bundle["evidence"]["observed_at"]
    _component_evidence(w.bundle["evidence"], w.bundle["prerequisites"], "qualification")
    w.write_sources()
    current = w.read().json()
    assert current["facts"]["owner_trial"] is current["facts"]["owner_acceptance"] is None
    assert w.read("accepted").json()["receipt"] == accepted
    assert w.read("accepted").json()["projection"]["status"] == "withdrawn"


def test_changed_profile_and_trial_correction_withdraw_acceptance(owner_writer, monkeypatch):
    from app.builderops import devui_receipts

    w = owner_writer
    rejected = w.submit(w.request("owner_acceptance", "rejected"), "rejected")
    assert rejected.status_code == 200
    assert w.read().json()["facts"]["owner_trial"] is None
    w.profile["limitation_refs"] = [{"id": "limit:unavailable", "sha256": "c" * 64}]
    w.write_sources()
    unable = w.request(outcome="unable_to_try", observation=[])
    trial = w.submit(unable, "unable").json()["receipt"]["id"]
    assert w.submit(w.request("owner_acceptance", "accepted", trial_receipt_ref=trial), "accept").status_code == 409
    w.profile["criterion_refs"][0]["sha256"] = "d" * 64
    w.write_sources()
    assert w.read().json()["facts"]["owner_trial"] is None
    unable = w.request(outcome="unable_to_try", observation=[])
    # Advance only the source freshness clock; retained typed bytes still prove
    # which candidate was attempted, without proving current readiness.
    observed = datetime.fromisoformat(w.chain[-1]["observed_at"])
    monkeypatch.setenv("DEVUI_VM102_RECEIPT_MAX_AGE_SECONDS", "1")
    monkeypatch.setattr(devui_receipts, "_utc_now", lambda: observed + timedelta(seconds=2))
    result = w.submit(unable, "unable-after-withdrawal")
    assert result.status_code == 200, result.text
    current = w.read().json()
    assert current["facts"]["ready_to_try"] is None
    assert current["facts"]["owner_trial"]["receipt_body"]["request"]["outcome"] == "unable_to_try"
    assert current["facts"]["owner_acceptance"] is None


def test_unavailable_writer_does_not_create_owner_outcome(owner_writer, monkeypatch):
    w = owner_writer
    request = w.request()
    (w.root / "devui-runtime-prerequisites.json").unlink()
    assert w.submit(request).status_code == 503
    assert w.count("builderops_records") == 0
    response = w.read()
    assert response.status_code == 503
    assert "facts" not in response.json()
    w.write_sources()
    w.credentials[0]["scopes"].remove("owner_outcomes:confirm")
    w.write_credentials()
    assert w.submit(request).status_code == 403
    assert w.count("builderops_outbox") == 0
    w.credentials[0]["scopes"].append("owner_outcomes:confirm")
    w.write_credentials()
    fault = w.store._fault
    def revoke(_requested, point):
        if point == "before_owner_outcome_commit":
            w.credentials[0]["scopes"].remove("owner_outcomes:confirm")
            w.write_credentials()
        return fault(_requested, point)
    monkeypatch.setattr(w.store, "_fault", revoke)
    assert w.submit(request).status_code == 403
    assert w.count("builderops_receipts") == 0


@pytest.mark.parametrize("missing_record", ["all", "terminal"])
def test_restart_reconciles_written_fact_before_projection(owner_writer, monkeypatch, missing_record):
    w = owner_writer
    request = w.request()
    original_fault = w.store._fault
    def fault(_requested, point):
        if point == "after_owner_outcome_receipt":
            raise RuntimeError("precommit interruption")
        return original_fault(_requested, point)
    monkeypatch.setattr(w.store, "_fault", fault)
    assert w.submit(request).status_code == 503
    for table in ("builderops_records", "builderops_receipts", "builderops_idempotency", "builderops_outbox"):
        assert w.count(table) == 0
    def lost_response(_requested, point):
        if point == "after_owner_outcome_commit":
            raise RuntimeError("response lost")
        return original_fault(_requested, point)
    monkeypatch.setattr(w.store, "_fault", lost_response)
    assert w.submit(request).status_code == 503
    assert w.count("builderops_records") == 1
    monkeypatch.setattr(w.store, "_fault", original_fault)
    original_read = w.store.get_owner_outcomes
    monkeypatch.setattr(w.store, "get_owner_outcomes", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("projection unavailable")))
    unavailable = w.submit(request).json()
    assert unavailable["projection"]["status"] == "unavailable"
    original_receipt = unavailable["receipt"]
    monkeypatch.setattr(w.store, "get_owner_outcomes", original_read)
    restarted = type(w.store)(w.store.dsn)
    w.client = TestClient(create_app(store=restarted, credentials=w.registry))
    receipt = w.submit(request).json()["receipt"]
    assert receipt == original_receipt
    assert w.read("first").json()["receipt"] == receipt
    assert w.count("builderops_records") == 1
    terminal = None
    if missing_record == "terminal":
        accepted = w.submit(w.request("owner_acceptance", "accepted", trial_receipt_ref=receipt["id"]), "accepted").json()["receipt"]
        terminal = w.submit(w.request("owner_acceptance", "rejected", expected_previous_receipt_id=accepted["id"], supersedes_receipt_id=accepted["id"], correction_reason="owner_correction"), "terminal").json()["receipt"]["id"]
    with w.store._connect() as conn:
        if terminal is not None:
            conn.execute("DELETE FROM builderops_records WHERE repository = %s AND record_id = %s", (REPO, terminal))
        else:
            conn.execute("DELETE FROM builderops_records WHERE repository = %s", (REPO,))
    assert w.read().status_code == 503
    assert w.submit(request).status_code == 503
    assert w.read("first").status_code == 503
