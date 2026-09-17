"""Read-only FCA-07 evidence composition, never platform acceptance authority.

Callers supply authenticated source readers. This does not authenticate offline
JSON or issue commands: production readback owns delivery and FCA-09 owns human
outcomes. A complete evidence join still cannot qualify a live second repository.
"""

from collections.abc import Callable, Mapping
from copy import deepcopy
from datetime import datetime
from typing import Any

from app.builderops.issue_delivery_readback import read_issue_delivery_projection
from app.builderops.owner_fact_producers import (
    BINDING_FIELDS,
    digest,
    outcome_request_hash,
    receipt_hash,
    validate_current_binding,
    validate_outcome_request,
)

CONTRACT = "builder_owner_acceptance_evidence.v1"
HUB = "rasmustho/agentic-pkm-mvp"


def _fresh(value: Any, now: datetime, max_age_seconds: int) -> None:
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None or now.tzinfo is None:
        raise ValueError("unqualified time")
    if not 0 <= (now - stamp).total_seconds() <= max_age_seconds:
        raise ValueError("stale or future source")


def _outcomes(value: dict[str, Any], repository: str, subject: str, epoch: int) -> dict[str, Any]:
    binding = value["binding"]
    if (
        value["contract"] != "builder_owner_facts.v1"
        or value["repository"] != repository
        or value["subject_ref"] != subject
        or value["authority_epoch"] != epoch
        or binding["repository"] != repository
        or binding["subject_ref"] != subject
        or binding["authorization_ref"]["authority_epoch"] != epoch
        or binding["binding_hash"] != digest({key: binding[key] for key in BINDING_FIELDS})
        or binding["readiness_status"] != "current"
        or binding["owner_grant_status"] != "available"
        or value["facts"]["ready_to_try"] != binding
    ):
        raise ValueError("owner binding unavailable or contradictory")
    return binding


def _outcome(value: dict[str, Any], binding: dict[str, Any], kind: str) -> dict[str, Any]:
    receipt = value["facts"][kind]
    body = receipt["receipt_body"]
    confirmation = body["confirmation_ref"]
    request = validate_outcome_request(body["request"], confirmed_at=confirmation["confirmed_at"])
    validate_current_binding(request, binding)
    if (
        body["contract"] != "builder_owner_outcome.v1"
        or receipt["hash"] != receipt_hash(receipt)
        or receipt["binding_hash"] != binding["binding_hash"]
        or body["request_sha256"] != outcome_request_hash(request)
        or confirmation["request_sha256"] != body["request_sha256"]
        or confirmation["authorization_ref"] != binding["authorization_ref"]
        or confirmation["human_principal"] != binding["owner_actor"]["id"]
        or request["fact_kind"] != kind
        or request["owner_actor"]["actor_type"] != "human"
        or receipt not in value["history"]
    ):
        raise ValueError("owner receipt unavailable or contradictory")
    return receipt


def read_owner_acceptance(
    *,
    client: Any,
    task: Mapping[str, Any],
    github_reader: Callable[..., Mapping[str, Any]],
    outcome_reader: Callable[[], dict[str, Any]],
    connected: bool,
    now: Callable[[], datetime],
    max_age_seconds: int = 300,
) -> dict[str, Any]:
    """Join current source receipts; return explicit incomplete on a failed read.

    The freshness window is supplied by the caller's acceptance observation, not
    a durable validity extension. Neither this result nor its hashes authorize
    execution, owner confirmation, deployment, or live platform acceptance.
    """
    result: dict[str, Any] = {
        "contract": CONTRACT,
        "authority": "projection_only",
        "status": "incomplete",
        "platform_acceptance": "incomplete",
        "qualified_repository": HUB,
        "missing": [],
        "delivery": None,
        "owner_trial_ref": None,
        "owner_acceptance_ref": None,
        "live_outstanding": [
            "exact_vm102_identity_epoch",
            "real_second_consumer",
            "operator_acknowledgement",
            "live_workflow_effects",
            "explicit_live_owner_trial_acceptance",
        ],
    }
    if connected is not True:
        result["missing"].append("owner_client_disconnected")
        return result
    stage = "source_readback_unavailable"
    try:
        if task["repository"] != HUB or type(max_age_seconds) is not int or max_age_seconds <= 0:
            raise ValueError("unqualified repository or observation window")
        first = outcome_reader()
        _fresh(first["observed_at"], now(), max_age_seconds)
        subject = f"github:{HUB}#{task['payload']['issue_number']}"
        binding = _outcomes(first, HUB, subject, client.authority_epoch)

        def owner_binding_reader(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return deepcopy(binding)

        stage = "delivery_evidence_incomplete"
        delivery = read_issue_delivery_projection(
            client=client,
            task=task,
            github_reader=github_reader,
            owner_binding_reader=owner_binding_reader,
        )
        for evidence in delivery["evidence"]:
            _fresh(evidence["captured_at"], now(), max_age_seconds)
        if delivery["candidate"]["ready_to_try"] is not True:
            raise ValueError("candidate stale or unavailable")
        result["delivery"] = delivery
        for kind in ("owner_trial", "owner_acceptance"):
            stage = kind + "_invalid"
            if first["facts"][kind] is None:
                result["missing"].append(kind + "_missing")
                continue
            receipt = _outcome(first, binding, kind)
            request = receipt["receipt_body"]["request"]
            expected = "tried" if kind == "owner_trial" else "accepted"
            if request["outcome"] != expected:
                result["missing"].append(kind + "_" + request["outcome"])
            else:
                result[kind + "_ref"] = receipt["id"]
        stage = "owner_lineage_changed"
        decision = first["facts"]["owner_acceptance"]
        if decision is not None and decision["receipt_body"]["request"]["outcome"] == "accepted":
            if (
                not result["owner_trial_ref"]
                or decision["receipt_body"]["request"]["trial_receipt_ref"]
                != result["owner_trial_ref"]
            ):
                raise ValueError("acceptance trial is not current")
        last = outcome_reader()
        _fresh(last["observed_at"], now(), max_age_seconds)
        # Observation timestamps advance on reads; compare source identity and
        # selected receipts, not the timestamp, then recheck the authority epoch.
        current = _outcomes(last, HUB, subject, client.status()["authority_epoch"])
        if current["binding_hash"] != binding["binding_hash"] or any(
            last["facts"][kind] != first["facts"][kind]
            for kind in ("owner_trial", "owner_acceptance")
        ):
            raise ValueError("owner evidence changed during composition")
        # Source/status reads can consume the observation window. Freeze one
        # final clock only after all I/O, then revalidate the whole joined chain.
        stage = "evidence_expired_during_read"
        final_observed_at = now()
        for stamp in (first["observed_at"], last["observed_at"]):
            _fresh(stamp, final_observed_at, max_age_seconds)
        for evidence in delivery["evidence"]:
            _fresh(evidence["captured_at"], final_observed_at, max_age_seconds)
        if not result["missing"]:
            result["status"] = "evidence_complete"
    except Exception:
        # Do not leak transport errors or credentials through an owner view.
        result["missing"].append(stage)
        result["delivery"] = None
        result["owner_trial_ref"] = result["owner_acceptance_ref"] = None
    return result
