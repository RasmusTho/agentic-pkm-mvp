"""Authenticated source transport and derived FCA-05 Overview/Focus inputs."""

from __future__ import annotations

import copy
import os
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from app.builderops.control_plane.client import BuilderOpsControlPlaneClient, ClientConfig
from app.builderops.control_plane.models import canonical_repository
from app.builderops.devui_model_inquiry_command import canonical_hash
from app.builderops.owner_fact_producers import BINDING_FIELDS, digest, outcome_request_hash, receipt_hash


def read_owner_fact_transport(
    *, repository: str | None = None, environment: Mapping[str, str] | None = None,
    authority_epoch: int | None = None,
) -> dict[str, Any]:
    source = os.environ if environment is None else environment
    try:
        repo = canonical_repository(repository or source.get("DEVUI_REPOSITORY", ""))
        epoch = authority_epoch or int(source.get("DEVUI_BUILDEROPS_AUTHORITY_EPOCH", ""))
        if epoch <= 0:
            raise ValueError
        with BuilderOpsControlPlaneClient(ClientConfig.from_env(source), max_retries=0) as client:
            value = client.get_receipt(repository=repo, object_kind="owner-facts", object_id="current")
        if value.get("contract") != "builder_owner_fact_collection.v1" or value.get("repository") != repo or not isinstance(value.get("subjects"), list) or len(value["subjects"]) > 64 or not isinstance(value.get("owner_asks"), list) or len(value["owner_asks"]) > 64:
            raise ValueError
        items = []
        seen = set()
        for item in value["subjects"]:
            subject = item["subject_ref"]
            if subject in seen or not subject.startswith("github:" + repo + "#"):
                raise ValueError
            seen.add(subject)
            try:
                if item.get("contract") != "builder_owner_facts.v1" or item["repository"] != repo or item["authority_epoch"] != epoch:
                    raise ValueError
                binding = item["binding"]
                if binding["repository"] != repo or binding["subject_ref"] != subject or binding["binding_hash"] != digest({key: binding[key] for key in BINDING_FIELDS}):
                    raise ValueError
                for kind in ("owner_trial", "owner_acceptance"):
                    receipt = item["facts"][kind]
                    if receipt is None:
                        continue
                    request = receipt["receipt_body"]["request"]
                    if receipt["hash"] != receipt_hash(receipt) or receipt["receipt_body"]["request_sha256"] != outcome_request_hash(request) or receipt["binding_hash"] != binding["binding_hash"] or request["fact_kind"] != kind or request["subject_ref"] != subject:
                        raise ValueError
                items.append(item)
            except Exception:
                items.append({"subject_ref": subject, "status": "unavailable", "reason": "source_facts_unavailable_or_incompatible"})
        asks = []
        for ask in value["owner_asks"]:
            if ask.get("status") != "current":
                continue
            try:
                proposal = ask["proposal"]
                if proposal["repository"] != repo or proposal["subject_ref"]["stable_id"] != ask["subject_ref"] or proposal["proposal_hash"] != ask["proposal_hash"] or proposal["proposal_hash"] != canonical_hash({k: v for k, v in proposal.items() if k != "proposal_hash"}) or proposal["approval_rule"]["authority_epoch"] != epoch or ask["choices"] != ["start", "hold"] or ask["authority_class"] != "bounded_action_confirmation":
                    raise ValueError
                asks.append({**ask, "repository": repo})
            except Exception:
                continue
        return {"status": "available", "repository": repo, "subjects": items, "owner_asks": asks}
    except Exception:
        return {"status": "unavailable", "reason": "owner_facts_source_unavailable"}


def _source_ref(item: Mapping[str, Any], identity: str, version: str) -> dict[str, str]:
    repository = item["repository"]
    return {"source_type": "builderops_receipt", "source_id": identity, "version": version,
            "locator": identity if identity.startswith("receipt:") else f"/v1/receipts/records/{quote(identity, safe='')}?repository={quote(repository, safe='')}"}


def _claims(item: Mapping[str, Any]) -> list[tuple[str, str, dict[str, str], str | None]]:
    binding = item["binding"]
    readiness = binding["readiness_receipt_ref"]
    result: list[tuple[str, str, dict[str, str], str | None]] = []
    if item["facts"]["ready_to_try"] is not None:
        for kind, receipt_type, claim in (
            ("deployed_candidate", "devsystem_vm102_deploy.v1", "The deployment owner attests this exact candidate and environment."),
            ("verification", "devui_vm102_runtime_qualification.v1", "The qualification receipt verifies this exact candidate; it is no owner trial or decision."),
        ):
            identity = next(ref for ref in binding["source_refs"] if ref.startswith("receipt:" + receipt_type + ":"))
            result.append((kind, claim, _source_ref(item, identity, identity.rsplit(":", 1)[-1]), None))
        result.append(("ready_to_try", "Exact candidate is ready to try according to the current deployment and verification chain.",
                       _source_ref(item, readiness["id"], readiness["sha256"]), None))
    for kind, label in (("owner_trial", "Owner trial"), ("owner_acceptance", "Owner decision")):
        receipt = item["facts"][kind]
        if receipt is not None:
            outcome = receipt["receipt_body"]["request"]["outcome"]
            result.append((kind, f"{label}: {outcome}.", _source_ref(item, receipt["id"], receipt["hash"]), outcome))
    return result


def owner_fact_candidates(provider: Any) -> dict[str, list[dict[str, Any]]]:
    """Only admitted source facts can contribute owner outcome/readiness claims."""
    if not isinstance(provider, dict) or provider.get("status") != "available":
        return {}
    candidates: dict[str, list[dict[str, Any]]] = {"ready_to_try": [], "now": [], "needs_you": []}
    for item in provider["subjects"]:
        if item.get("status") == "unavailable":
            continue
        binding = item["binding"]
        subject = item["subject_ref"]
        repo, number = subject.removeprefix("github:").rsplit("#", 1)
        candidate: dict[str, Any] = {
            "subject_ref": {"source_type": "github_issue", "source_id": subject, "version": binding["source_revision"], "locator": f"https://github.com/{repo}/issues/{number}"},
            "display_label": "Candidate trial and owner decision", "reason": "Current source receipts bind this candidate, environment and acceptance profile.",
            "evidence": [], "delivery_facts": {}, "navigation_refs": [], "limitations": [],
        }
        for kind, claim, reference, outcome in _claims(item):
            evidence_id = kind + ":" + reference["source_id"]
            candidate["evidence"].append({"evidence_id": evidence_id, "claim": claim, "source_ref": reference,
                "availability": "available", "freshness": "fresh", "completeness": "complete", "cardinality": "nonempty",
                "linkage": "linked", "captured_at": item["observed_at"], "read_watermark": item["observed_at"], "limitation": None})
            fact = {"state": "evidenced", "source_ref": reference, "receipt_ref": reference, "evidence_id": evidence_id}
            if outcome is not None:
                fact["outcome"] = outcome
            candidate["delivery_facts"][kind] = fact
        if candidate["evidence"]:
            candidates["ready_to_try" if item["facts"]["ready_to_try"] is not None else "now"].append(candidate)
    for ask in provider.get("owner_asks", []):
        proposal = ask["proposal"]
        reference = _source_ref(ask, ask["receipt_id"], ask["proposal_hash"])
        evidence_id = "owner_ask:" + ask["proposal_hash"]
        candidates["needs_you"].append({
            "subject_ref": {"source_type": "builderops_proposal", "source_id": ask["subject_ref"], "version": ask["proposal_hash"], "locator": reference["locator"]},
            "display_label": "Owner choice: Start or Hold inquiry",
            "reason": "Explicit confirmation is required before the sanctioned inquiry can use model access.",
            "owner_authority": {"category": "security_privacy_cost_commitment", "governing_source": reference, "evidence_id": evidence_id},
            "evidence": [{"evidence_id": evidence_id, "claim": f"Canonical owner ask: Start or Hold. Authority class: {ask['authority_class']}. Proposal: {proposal['proposal_hash']}.",
                "source_ref": reference, "availability": "available", "freshness": "fresh", "completeness": "complete", "cardinality": "nonempty", "linkage": "linked",
                "captured_at": ask["observed_at"], "read_watermark": ask["observed_at"], "limitation": None}],
            "navigation_refs": [], "limitations": [],
        })
    return copy.deepcopy(candidates)


def append_focus_owner_facts(inputs: dict[str, Any], provider: dict[str, Any]) -> dict[str, Any]:
    subject = inputs["subject"]["stable_id"]
    for ask in provider.get("owner_asks", []):
        if ask["subject_ref"] == subject:
            reference = _source_ref(ask, ask["receipt_id"], ask["proposal_hash"])
            inputs["evidence"].append({"claim_id": "owner_ask:" + ask["proposal_hash"],
                "claim": f"Canonical owner ask: Start or Hold. Authority class: {ask['authority_class']}. Proposal: {ask['proposal_hash']}.",
                "source_ref": reference, "availability": "available", "freshness": "fresh", "coverage": "complete", "cardinality": "nonempty", "linkage": "linked", "captured_at": ask["observed_at"], "limitation": None})
    item = next((row for row in provider.get("subjects", []) if row["subject_ref"] == subject), None)
    if provider.get("status") != "available" or item is None or item.get("status") == "unavailable":
        inputs["limitations"].append({"kind": "owner_facts_unavailable", "reason": "Owner outcome source is unavailable or unadmitted; no trial or decision is inferred.", "evidence_state": "unavailable"})
        return inputs
    for kind, claim, reference, _outcome in _claims(item):
        inputs["evidence"].append({"claim_id": kind + ":" + reference["source_id"], "claim": claim,
            "source_ref": reference, "availability": "available", "freshness": "fresh", "coverage": "complete",
            "cardinality": "nonempty", "linkage": "linked", "captured_at": item["observed_at"], "limitation": None})
        inputs["receipts"].append({"receipt_ref": reference["source_id"], "source_ref": reference,
            "correlation": {"status": "linked", "method": "explicit_receipt", "authority_ref": inputs["subject"]["authority_ref"]}})
    return inputs
