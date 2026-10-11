"""Synthetic external receipt responses; production Focus/transport stay real."""
from __future__ import annotations

import copy
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone

import httpx

from app.builderops import devui_owner_facts
from app.builderops.owner_fact_producers import digest, outcome_request_hash, receipt_hash
from tests.companion_ui.focus_jev_advisory import SUBJECT


def collection(case_id: str) -> dict:
    repository, subject = "example/fixture", SUBJECT
    if case_id == "mixed-unrelated-issue":
        subject = "github:example/fixture#502"
    elif case_id == "mixed-unrelated-repository":
        repository, subject = "foreign/fixture", "github:foreign/fixture#501"
    stamp = datetime.now(timezone.utc).isoformat()
    binding = {
        "repository": repository, "subject_ref": subject, "source_revision": "a" * 40,
        "candidate_ref": {"source_sha": "a" * 40, "devui_image_digest": "sha256:" + "b" * 64, "devui_config_fingerprint": "sha256:" + "c" * 64},
        "environment_ref": {"component_id": "devui_projection", "name": "fixture", "vmid": 102},
        "readiness_receipt_ref": {"id": "readiness-fixture", "sha256": "d" * 64, "source_owner": "builderops_vm102_receipt_source"},
        "acceptance_profile_ref": {"id": "profile:fixture", "sha256": "e" * 64, "source_owner": "builderops_vm102_receipt_source", "version": "1"},
        "criterion_refs": [{"id": "AC1", "sha256": "f" * 64}],
        "owner_actor": {"actor_type": "human", "id": "human:fixture"},
        "authorization_ref": {"authority_epoch": 7, "ref": "policy:fixture", "version": "1"},
        "limitation_refs": [], "retention_policy_ref": {"ref": "BuilderOpsReceipt", "version": "1"},
    }
    binding["binding_hash"] = digest(binding)
    binding.update(owner_grant_status="available", source_refs=[
        "receipt:devsystem_vm102_deploy.v1:" + "1" * 64,
        "receipt:devui_vm102_runtime_qualification.v1:" + "2" * 64,
    ])
    facts = {"ready_to_try": copy.deepcopy(binding), "owner_trial": None, "owner_acceptance": None}
    for kind, outcome in (("owner_trial", "tried"), ("owner_acceptance", "accepted")):
        request = {"fact_kind": kind, "subject_ref": subject, "outcome": outcome}
        receipt = {"id": kind + "-fixture", "binding_hash": binding["binding_hash"],
            "receipt_body": {"request": request, "request_sha256": outcome_request_hash(request)}}
        receipt["hash"] = receipt_hash(receipt)
        facts[kind] = receipt
    row = {"contract": "builder_owner_facts.v1", "repository": repository, "subject_ref": subject,
        "binding": binding, "facts": facts, "authority_epoch": 7, "observed_at": stamp}
    proposal = {"repository": repository, "subject_ref": {"kind": "issue", "stable_id": subject},
        "approval_rule": {"authority_epoch": 7}}
    proposal["proposal_hash"] = digest(proposal)
    ask = {"subject_ref": subject, "receipt_id": "ask-fixture", "proposal_hash": proposal["proposal_hash"],
        "status": "current", "choices": ["start", "hold"], "authority_class": "bounded_action_confirmation",
        "proposal": proposal, "observed_at": stamp}
    value = {"contract": "builder_owner_fact_collection.v1", "repository": repository,
        "subjects": [row], "owner_asks": [ask], "owner_outcomes_status": "available"}
    if case_id == "mixed-readiness-only":
        facts.update(owner_trial=None, owner_acceptance=None)
        value["owner_asks"] = []
    elif case_id == "mixed-ask-only":
        value.update(subjects=[], owner_outcomes_status="unavailable")
    elif case_id == "mixed-invalid-receipt":
        facts["owner_trial"]["hash"] = "0" * 64
    return value


@contextmanager
def owner_source(monkeypatch, case_id: str):
    """Replace only external source I/O, never the reader/composer or browser API."""
    value, calls = collection(case_id), []

    def response(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET"
        assert request.url.path == "/v1/receipts/owner-facts/current"
        assert request.url.params["repository"] == "example/fixture"
        assert request.headers["authorization"] == "Bearer fixture-secret-never-export"
        if case_id == "mixed-unavailable":
            raise httpx.ReadTimeout("synthetic source unavailable", request=request)
        return httpx.Response(200, json=value)

    original = devui_owner_facts.BuilderOpsControlPlaneClient
    with ExitStack() as stack:
        def client(config, **kwargs):
            http = stack.enter_context(httpx.Client(base_url=config.base_url, transport=httpx.MockTransport(response)))
            return original(config, http_client=http, max_retries=0)
        monkeypatch.setattr(devui_owner_facts, "BuilderOpsControlPlaneClient", client)
        yield value, calls
