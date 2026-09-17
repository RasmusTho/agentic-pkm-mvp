"""Independent FCA-ID-C readback for one admitted Issue-delivery task.

The module composes existing authorities; it owns no queue, database, workflow
transition, deployment decision, or owner outcome.  Worker claims are retained
as diagnostics only and never establish a GitHub or deployment fact.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import hashlib
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Protocol

from app.builderops.control_plane.client_cli import (
    issue_source_task,
    same_json_value,
    validate_import_readback,
    validate_import_response,
)
from app.builderops.control_plane.models import canonical_repository
from app.builderops.control_plane.issue_delivery import delivery_source_pair, tracking_repository
from app.builderops.owner_fact_producers import OwnerFactRefusal, read_owner_binding
from app.builderops.devui_receipts import AUTHORITY as OWNER_BINDING_AUTHORITY


CONTRACT = "fca-issue-delivery-readback.v1"
TASK_CONTRACT = "fca-issue-delivery-task.v1"
_HEX_40 = re.compile(r"[0-9a-f]{40}\Z")
_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_AC = re.compile(r"^## Acceptance Criteria\s*\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)


class IssueDeliveryReadbackRefused(ValueError):
    """The exact source chain cannot support an Issue-delivery projection."""


class _AdmissionClient(Protocol):
    authority_epoch: int

    def issue_delivery_readback(self, *, repository: str, approval_id: str) -> dict[str, Any]: ...
    def status(self) -> dict[str, Any]: ...
    def transition_task(self, **request: Any) -> dict[str, Any]: ...
    def get_task(self, *, repository: str, task_id: str) -> dict[str, Any]: ...


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise IssueDeliveryReadbackRefused(f"{label} is unavailable or malformed")
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IssueDeliveryReadbackRefused(f"{label} is unavailable or malformed")
    return value


def _sha(value: Any, label: str, *, length: int = 64) -> str:
    result = _text(value, label).lower()
    pattern = _HEX_40 if length == 40 else _HEX_64
    if pattern.fullmatch(result) is None:
        raise IssueDeliveryReadbackRefused(f"{label} is unavailable or malformed")
    return result


def _timestamp(value: Any, label: str) -> str:
    result = _text(value, label)
    try:
        parsed = datetime.fromisoformat(result.replace("Z", "+00:00"))
    except ValueError as exc:
        raise IssueDeliveryReadbackRefused(f"{label} is malformed") from exc
    if parsed.tzinfo is None:
        raise IssueDeliveryReadbackRefused(f"{label} is malformed")
    return result


def _approval(value: Any) -> Mapping[str, Any]:
    readback = _mapping(value, "Issue-delivery approval readback")
    approval = _mapping(readback.get("approval"), "Issue-delivery approval")
    issue = _mapping(approval.get("issue"), "approved Issue")
    if (
        readback.get("state") not in {"approved", "invalidated"}
        or readback.get("approval_id") != approval.get("approval_id")
        or readback.get("manifest") != approval
        or _mapping(readback.get("receipt"), "approval receipt").get("approval_manifest_hash")
        != approval.get("approval_manifest_hash")
        or _mapping(readback.get("operation"), "approved operation").get("operation_key")
        != approval.get("operation_key")
        or type(issue.get("number")) is not int
        or issue["number"] < 1
    ):
        raise IssueDeliveryReadbackRefused("Issue-delivery approval readback changed")
    canonical_repository(_text(approval.get("repository"), "approved repository"))
    _sha(approval.get("approval_manifest_hash"), "approval manifest hash")
    _sha(_mapping(approval.get("source"), "approved source").get("revision"), "source revision", length=40)
    _sha(issue.get("body_hash"), "Issue body hash")
    _sha(issue.get("acceptance_criteria_hash"), "acceptance criteria hash")
    return approval


def _source_hashes(issue: Mapping[str, Any]) -> tuple[str, str]:
    body = issue.get("body")
    if not isinstance(body, str):
        return (
            _sha(issue.get("body_hash"), "GitHub Issue body hash"),
            _sha(issue.get("acceptance_criteria_hash"), "GitHub acceptance criteria hash"),
        )
    match = _AC.search(body)
    if match is None:
        raise IssueDeliveryReadbackRefused("GitHub evidence lacks Acceptance Criteria")
    body_hash = hashlib.sha256(body.encode()).hexdigest()
    ac_hash = hashlib.sha256(match[1].encode()).hexdigest()
    if issue.get("body_hash") not in (None, body_hash) or issue.get("acceptance_criteria_hash") not in (None, ac_hash):
        raise IssueDeliveryReadbackRefused("GitHub evidence source hashes contradict its body")
    return body_hash, ac_hash


def admit_issue_delivery_task(
    *,
    client: _AdmissionClient,
    repository: str,
    approval_id: str,
    issue_reader: Callable[[str, int], Mapping[str, Any]],
    observed_at: str,
) -> dict[str, Any]:
    """Admit and independently read back one immutable native TaskRecord."""

    repo = canonical_repository(repository)
    try:
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError
    except (AttributeError, ValueError) as exc:
        raise IssueDeliveryReadbackRefused("admission observation time is invalid") from exc
    readback = client.issue_delivery_readback(repository=repo, approval_id=approval_id)
    approval = _approval(readback)
    if readback.get("state") != "approved":
        raise IssueDeliveryReadbackRefused("withdrawn approval cannot admit a new native task")
    if approval.get("repository") != repo or approval.get("approval_id") != approval_id:
        raise IssueDeliveryReadbackRefused("approval address does not match admission request")
    issue_binding = _mapping(approval.get("issue"), "approved Issue")
    number = int(issue_binding["number"])
    issue_repository = tracking_repository(approval)
    issue = _mapping(issue_reader(issue_repository, number), "GitHub Issue source")
    body_hash, ac_hash = _source_hashes(issue)
    if (
        issue.get("number") != number
        or issue.get("node_id") != issue_binding.get("node_id")
        or issue.get("state") != issue_binding.get("state")
        or body_hash != issue_binding.get("body_hash")
        or ac_hash != issue_binding.get("acceptance_criteria_hash")
    ):
        raise IssueDeliveryReadbackRefused("GitHub Issue source does not match approval")

    try:
        payload = issue_source_task(
            dict(issue), repository=issue_repository, number=number,
            observed_at=observed_at, authority_epoch=client.authority_epoch,
        )
    except ValueError as exc:
        raise IssueDeliveryReadbackRefused("GitHub Issue source is not admission-ready") from exc
    source_payload = deepcopy(payload)
    task_id = f"issue-delivery-{approval_id}"
    payload.update(
        task_id=task_id,
        status="ready",
        why_now="An approved Issue delivery is ready for independent readback.",
        issue_delivery={
            "contract": TASK_CONTRACT,
            "task_record_version": 1,
            "approval_id": approval_id,
            "approval_manifest_hash": approval["approval_manifest_hash"],
            "operation_key": approval["operation_key"],
            "authority_epoch": approval["authority_epoch"],
            "issue_node_id": issue_binding["node_id"],
            "issue_body_hash": body_hash,
            "acceptance_criteria_hash": ac_hash,
            "source_revision": approval["source"]["revision"],
            **({"delivery_sources": delivery_source_pair(approval)} if delivery_source_pair(approval) else {}),
        },
    )
    envelope = {
        "repository": repo,
        "scope": f"issue:{number}",
        "stack": "builderops-issue-delivery",
        "source_refs": [
            f"github:issue:{number}",
            f"builderops:issue-delivery:{approval_id}",
            f"git:{approval['source']['revision']}",
        ],
    }
    identity = {
        "task_id": task_id,
        "approval_manifest_hash": approval["approval_manifest_hash"],
        "issue_version": issue.get("updated_at"),
        "authority_epoch": approval["authority_epoch"],
    }
    idempotency_key = "issue-delivery-admission:" + hashlib.sha256(
        repr(sorted(identity.items())).encode()
    ).hexdigest()
    request = {
        "envelope": envelope,
        "task_id": task_id,
        "to_state": "ready",
        "idempotency_key": idempotency_key,
        "request": payload,
        "outbox": None,
        "lease": None,
        "expected_states": None,
        "expected_version": None,
    }
    response = client.transition_task(**request)
    try:
        validate_import_response(response, request)
        row = client.get_task(repository=repo, task_id=task_id)
        validate_import_readback(row, request)
        fresh_readback = client.issue_delivery_readback(
            repository=repo, approval_id=approval_id
        )
        fresh_approval = _approval(fresh_readback)
        fresh_issue = issue_reader(issue_repository, number)
        fresh_payload = issue_source_task(
            dict(fresh_issue), repository=issue_repository, number=number,
            observed_at=observed_at, authority_epoch=client.authority_epoch,
        )
        if (
            fresh_readback.get("state") != "approved"
            or not same_json_value(fresh_approval, approval)
            or
            not same_json_value(fresh_payload, source_payload)
            or client.status().get("authority_epoch") != approval["authority_epoch"]
        ):
            raise ValueError("approval, Issue source, or authority changed during admission")
    except ValueError as exc:
        raise IssueDeliveryReadbackRefused("native task admission readback changed") from exc
    return deepcopy(row)


def _task_binding(task: Any, approval: Mapping[str, Any]) -> None:
    if task is None:
        return
    row = _mapping(task, "Issue-delivery task")
    payload = _mapping(row.get("payload"), "Issue-delivery task payload")
    binding = _mapping(payload.get("issue_delivery"), "Issue-delivery task binding")
    issue = _mapping(approval.get("issue"), "approved Issue")
    if delivery_source_pair(approval) and binding.get("delivery_sources") != delivery_source_pair(approval):
        raise IssueDeliveryReadbackRefused("native task source pair changed")
    if (
        row.get("repository") != approval.get("repository")
        or row.get("state") not in {"ready", "claimed", "completed"}
        or type(row.get("version")) is not int
        or row["version"] < 1
        or binding.get("contract") != TASK_CONTRACT
        or binding.get("task_record_version") != row["version"]
        or binding.get("approval_id") != approval.get("approval_id")
        or binding.get("approval_manifest_hash") != approval.get("approval_manifest_hash")
        or binding.get("operation_key") != approval.get("operation_key")
        or binding.get("issue_node_id") != issue.get("node_id")
        or binding.get("issue_body_hash") != issue.get("body_hash")
        or binding.get("acceptance_criteria_hash") != issue.get("acceptance_criteria_hash")
        or binding.get("source_revision") != approval["source"]["revision"]
    ):
        raise IssueDeliveryReadbackRefused("native Issue-delivery task binding changed")


def _targets(host_effects: Any, refs: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(host_effects, list) or not isinstance(refs, list):
        raise IssueDeliveryReadbackRefused("host effect evidence is unavailable")
    ref_by_operation: dict[str, Mapping[str, Any]] = {}
    for raw_ref in refs:
        ref = _mapping(raw_ref, "host effect reference")
        operation_key = ref.get("operation_key")
        if (
            not isinstance(operation_key, str)
            or operation_key in ref_by_operation
            or any(
                not isinstance(ref.get(key), str)
                or _HEX_64.fullmatch(str(ref[key])) is None
                for key in ("operation_key", "request_sha256", "effect_slot_sha256")
            )
        ):
            raise IssueDeliveryReadbackRefused("host effect reference is malformed")
        ref_by_operation[operation_key] = ref
    targets: dict[str, Mapping[str, Any]] = {}
    seen_operations: set[str] = set()
    for raw in host_effects:
        effect = _mapping(raw, "host effect evidence")
        payload = _mapping(effect.get("payload"), "host effect payload")
        operation_key = effect.get("operation_key")
        matched_ref = ref_by_operation.get(str(operation_key))
        kind = payload.get("effect_kind")
        target = _mapping(payload.get("target"), "host effect target")
        if (
            effect.get("status") != "succeeded"
            or matched_ref is None
            or operation_key in seen_operations
            or payload.get("request_sha256") != matched_ref.get("request_sha256")
            or payload.get("effect_slot_sha256") != matched_ref.get("effect_slot_sha256")
            or kind not in {"claim", "publication", "merge", "closure", "parent_evidence"}
            or target.get("kind") != kind
        ):
            raise IssueDeliveryReadbackRefused("host effect evidence is incomplete or contradictory")
        seen_operations.add(str(operation_key))
        if kind in {"publication", "merge", "closure"}:
            if kind in targets:
                raise IssueDeliveryReadbackRefused("host effect evidence is incomplete or contradictory")
            targets[str(kind)] = target
    if (
        seen_operations != set(ref_by_operation)
        or set(targets) != {"publication", "merge", "closure"}
    ):
        raise IssueDeliveryReadbackRefused("host effect evidence is incomplete or contradictory")
    return targets


def read_issue_delivery_projection(
    *,
    client: Any,
    task: Mapping[str, Any],
    github_reader: Callable[..., Mapping[str, Any]],
    owner_binding_reader: Callable[..., Mapping[str, Any]] = read_owner_binding,
) -> dict[str, Any]:
    """Read all existing authorities for one strict native delivery task."""

    # Keep the managed read-only DevUI boot independent of the dispatcher
    # package. The operation adapter is needed only when a strict delivery task
    # is actually projected, never while the standalone application imports.
    from app.builderops.issue_delivery_operation import observe_issue_delivery_operation

    payload = _mapping(task.get("payload"), "Issue-delivery task payload")
    binding = _mapping(payload.get("issue_delivery"), "Issue-delivery task binding")
    if binding.get("contract") != TASK_CONTRACT:
        raise IssueDeliveryReadbackRefused("task is not a native Issue-delivery task")
    repository = canonical_repository(_text(task.get("repository"), "task repository"))
    approval_id = _text(binding.get("approval_id"), "task approval")
    approval_readback = client.issue_delivery_readback(
        repository=repository, approval_id=approval_id
    )
    approval = _approval(approval_readback)
    context = _mapping(approval.get("context"), "approved dispatch context")
    plan = _mapping(context.get("dispatch_plan"), "approved dispatch plan")
    expected_plan_hash = _text(context.get("expected_plan_hash"), "approved plan hash")
    destination = _mapping(approval.get("destination"), "approved destination")
    root = destination.get("resolved_worktree") or destination.get("worktree")
    if not isinstance(root, str) or not root:
        raise IssueDeliveryReadbackRefused("approved destination worktree is unavailable")
    try:
        observed = observe_issue_delivery_operation(
            approval,
            client=client,
            plan=plan,
            expected_plan_hash=expected_plan_hash,
            repo_root=Path(root),
        )
    except Exception as exc:
        raise IssueDeliveryReadbackRefused("destination operation readback is unavailable") from exc
    if observed.state != "terminal":
        raise IssueDeliveryReadbackRefused(
            "destination operation is not terminal for independent readback"
        )
    operation = {**asdict(observed), "operation_key": approval["operation_key"]}
    host_effects: list[dict[str, Any]] = []
    for ref in observed.host_effect_refs or []:
        status = client.get_outbox_status(
            repository=repository, operation_key=ref["operation_key"]
        )
        value = _mapping(status, "host effect status")
        effect_payload = _mapping(value.get("payload"), "host effect payload")
        if (
            value.get("status") != "succeeded"
            or effect_payload.get("request_sha256") != ref["request_sha256"]
            or effect_payload.get("effect_slot_sha256") != ref["effect_slot_sha256"]
            or effect_payload.get("approval_id") != approval_id
            or effect_payload.get("approved_operation_key") != approval.get("operation_key")
            or effect_payload.get("repository") != repository
        ):
            raise IssueDeliveryReadbackRefused("host effect readback changed")
        host_effects.append(deepcopy(dict(value)))
    issue = _mapping(approval.get("issue"), "approved Issue")
    branch = _text(destination.get("branch"), "approved branch")
    github = github_reader(repository, int(issue["number"]), branch=branch,
                           **({"issue_repository": tracking_repository(approval),
                               "verification_checks": tuple(approval["target_policies"][repository]["required_checks"])}
                              if delivery_source_pair(approval) else {}))
    subject = f"github:{tracking_repository(approval)}#{issue['number']}"
    try:
        owner = owner_binding_reader(
            repository,
            subject,
            authority_epoch=int(approval["authority_epoch"]),
            allow_withdrawn_readiness=True,
        )
    except (OwnerFactRefusal, TypeError, ValueError):
        owner = None
    return compose_issue_delivery_readback(
        task=task,
        approval_readback=approval_readback,
        operation=operation,
        host_effects=host_effects,
        github_evidence=github,
        owner_binding=owner,
    )


def _candidate(owner_binding: Any, *, repository: str, subject: str, head_sha: str) -> dict[str, Any]:
    unavailable = {"ready_to_try": False, "reason": "exact FCA-09 candidate binding unavailable"}
    if not isinstance(owner_binding, Mapping):
        return unavailable
    if (
        owner_binding.get("repository") != repository
        or owner_binding.get("subject_ref") != subject
        or owner_binding.get("source_revision") != head_sha
        or owner_binding.get("readiness_status") != "current"
    ):
        return unavailable
    candidate_ref = _mapping(owner_binding.get("candidate_ref"), "candidate binding")
    profile_ref = _mapping(owner_binding.get("acceptance_profile_ref"), "acceptance profile")
    if (
        candidate_ref.get("source_sha") != head_sha
        or not isinstance(profile_ref.get("id"), str)
        or not profile_ref["id"]
        or not isinstance(profile_ref.get("version"), str)
        or not profile_ref["version"]
        or profile_ref.get("source_owner") != OWNER_BINDING_AUTHORITY
    ):
        return unavailable
    return {
        "ready_to_try": True,
        "source_revision": head_sha,
        "candidate_ref": deepcopy(dict(candidate_ref)),
        "environment_ref": deepcopy(dict(_mapping(owner_binding.get("environment_ref"), "candidate environment"))),
        "readiness_receipt_ref": deepcopy(dict(_mapping(owner_binding.get("readiness_receipt_ref"), "readiness receipt"))),
        "acceptance_profile_ref": deepcopy(dict(profile_ref)),
        "binding_hash": owner_binding.get("binding_hash"),
        "observed_at": owner_binding.get("observed_at"),
    }


def compose_issue_delivery_readback(
    *,
    task: Any,
    approval_readback: Any,
    operation: Any,
    host_effects: Any,
    github_evidence: Any,
    owner_binding: Any,
) -> dict[str, Any]:
    """Join independent exact evidence into a fail-closed delivery projection."""

    approval = _approval(approval_readback)
    _task_binding(task, approval)
    op = _mapping(operation, "destination operation")
    if op.get("state") != "terminal" or op.get("operation_key") != approval.get("operation_key"):
        raise IssueDeliveryReadbackRefused("destination operation is not terminal for this approval")
    # Deliberately do not consult op["worker_receipt"] for any outcome.
    targets = _targets(host_effects, op.get("host_effect_refs"))
    if delivery_source_pair(approval):
        for effect in host_effects:
            payload = effect["payload"]
            if (payload.get("delivery_sources") != delivery_source_pair(approval)
                or payload.get("approval_manifest_hash") != approval["approval_manifest_hash"]
                or payload.get("effect_repository") != (approval["repository"] if payload["effect_kind"] in {"publication", "merge"} else tracking_repository(approval))):
                raise IssueDeliveryReadbackRefused("host effect source pair changed")
    github = _mapping(github_evidence, "GitHub evidence")
    issue = _mapping(github.get("issue"), "GitHub Issue evidence")
    pull = _mapping(github.get("pull_request"), "GitHub pull-request evidence")
    gates = _mapping(github.get("required_gates"), "GitHub required-gate evidence")
    reviews = _mapping(github.get("reviews"), "GitHub review evidence")
    approved_issue = _mapping(approval.get("issue"), "approved Issue")
    publication, merge, closure = targets["publication"], targets["merge"], targets["closure"]
    body_hash, ac_hash = _source_hashes(issue)
    observed_at = _timestamp(github.get("observed_at"), "GitHub observation time")
    if (
        github.get("repository") != approval.get("repository")
        or issue.get("number") != approved_issue.get("number")
        or issue.get("node_id") != approved_issue.get("node_id")
        or body_hash != approved_issue.get("body_hash")
        or ac_hash != approved_issue.get("acceptance_criteria_hash")
    ):
        raise IssueDeliveryReadbackRefused("GitHub evidence does not match the approved Issue source")
    if delivery_source_pair(approval) and (
        github.get("issue_repository") != tracking_repository(approval)
        or pull.get("governing_issue_repository") != tracking_repository(approval)
        or issue.get("html_url", "").casefold() != approved_issue["url"].casefold()
    ):
        raise IssueDeliveryReadbackRefused("GitHub tracking Issue repository changed")
    head_sha = _sha(publication.get("head_sha"), "published head", length=40)
    if (
        merge.get("head_sha") != head_sha
        or pull.get("head_sha") != head_sha
        or gates.get("head_sha") != head_sha
        or reviews.get("head_sha") != head_sha
    ):
        raise IssueDeliveryReadbackRefused("GitHub head evidence drifted")
    if (
        pull.get("number") != merge.get("pr_number")
        or pull.get("number") != closure.get("pr_number")
        or not isinstance(pull.get("node_id"), str)
        or not pull["node_id"]
        or pull.get("governing_issue") != approved_issue.get("number")
        or pull.get("title_sha256") != publication.get("title_sha256")
        or pull.get("body_sha256") != publication.get("body_sha256")
        or pull.get("head_ref") != publication.get("branch")
        or pull.get("head_ref") != merge.get("branch")
        or pull.get("base_ref") != publication.get("base_ref")
        or pull.get("base_ref") != merge.get("base_ref")
        or pull.get("base_sha") != publication.get("base_sha")
        or pull.get("base_sha") != merge.get("base_sha")
        or pull.get("merged") is not True
        or pull.get("state") != "closed"
        or not isinstance(pull.get("merged_at"), str)
        or gates.get("state") != "success"
        or _HEX_64.fullmatch(str(gates.get("policy_sha256"))) is None
        or gates.get("observed_at") != observed_at
        or reviews.get("state") != "approved"
        or reviews.get("observed_at") != observed_at
    ):
        raise IssueDeliveryReadbackRefused("GitHub evidence does not prove the exact reviewed merge")
    merge_sha = _sha(closure.get("merge_commit_sha"), "closure merge commit", length=40)
    _timestamp(pull.get("merged_at"), "GitHub merge time")
    closed_by = issue.get("closed_by")
    if (
        pull.get("merge_commit_sha") != merge_sha
        or issue.get("state") != "closed"
        or not isinstance(issue.get("closed_at"), str)
        or not isinstance(closed_by, Mapping)
        or not isinstance(closed_by.get("login"), str)
        or not closed_by["login"]
    ):
        raise IssueDeliveryReadbackRefused("GitHub closure evidence is incomplete or contradictory")
    _timestamp(issue.get("closed_at"), "GitHub closure time")

    repository = str(approval["repository"])
    number = int(approved_issue["number"])
    subject = f"github:{tracking_repository(approval)}#{number}"
    evidence_id = f"issue-delivery:{number}:{head_sha}"
    evidence = {
        "evidence_id": evidence_id,
        "claim": "Independent GitHub evidence confirms the exact reviewed merge and Issue closure.",
        "source_ref": {
            "source_type": "github_issue_delivery_readback",
            "source_id": f"{repository}#{number}:pr-{pull['number']}",
            "locator": f"https://github.com/{repository}/pull/{pull['number']}",
            "version": head_sha,
        },
        "availability": "available",
        "freshness": "fresh",
        "completeness": "complete",
        "cardinality": "nonempty",
        "linkage": "linked",
        "captured_at": observed_at,
        "read_watermark": observed_at,
        "limitation": "Repository delivery is not deployment, trial, or owner acceptance.",
    }
    candidate = _candidate(
        owner_binding, repository=repository, subject=subject, head_sha=head_sha
    ) if not delivery_source_pair(approval) else {"ready_to_try": False, "reason": "FCA-09-BIFROST readiness is not implemented"}
    evidence_rows: list[dict[str, Any]] = [evidence]
    delivery_facts: dict[str, Any] = {
        "delivery": {
            "state": "evidenced",
            "evidence_id": evidence_id,
            "source_ref": evidence["source_ref"],
        }
    }
    if candidate["ready_to_try"] is True:
        receipt = _mapping(candidate.get("readiness_receipt_ref"), "readiness receipt")
        receipt_id = _text(receipt.get("id"), "readiness receipt id")
        receipt_sha = _sha(receipt.get("sha256"), "readiness receipt hash")
        readiness_observed_at = _timestamp(
            candidate.get("observed_at"), "candidate observation time"
        )
        readiness_ref = {
            "source_type": "builderops_vm102_receipt",
            "source_id": receipt_id,
            "locator": receipt_id,
            "version": receipt_sha,
        }
        readiness_evidence_id = f"issue-delivery-ready:{number}:{head_sha}"
        evidence_rows.append(
            {
                "evidence_id": readiness_evidence_id,
                "claim": "The deployment owner's current FCA-09 binding makes this exact delivered head ready to try.",
                "source_ref": readiness_ref,
                "availability": "available",
                "freshness": "fresh",
                "completeness": "complete",
                "cardinality": "nonempty",
                "linkage": "linked",
                "captured_at": readiness_observed_at,
                "read_watermark": readiness_observed_at,
                "limitation": "Ready to try is not an owner trial or acceptance outcome.",
            }
        )
        delivery_facts["ready_to_try"] = {
            "state": "evidenced",
            "source_ref": readiness_ref,
            "receipt_ref": readiness_ref,
            "evidence_id": readiness_evidence_id,
        }
    return {
        "contract": CONTRACT,
        "state": "delivered",
        "subject_ref": subject,
        "approval_id": approval["approval_id"],
        "approval_manifest_hash": approval["approval_manifest_hash"],
        "operation_key": approval["operation_key"],
        "task_record_version": None if task is None else task["version"],
        "repository": repository,
        **({"delivery_sources": delivery_source_pair(approval), "issue_repository": tracking_repository(approval)}
           if delivery_source_pair(approval) else {}),
        "issue_number": number,
        "pr_number": pull["number"],
        "head_sha": head_sha,
        "merge_commit_sha": merge_sha,
        "github_policy_sha256": gates["policy_sha256"],
        "evidence": evidence_rows,
        "delivery_facts": delivery_facts,
        "candidate": candidate,
        "limitations": ["Repository delivery does not establish deployment, owner trial, or owner acceptance."],
    }


__all__ = [
    "CONTRACT",
    "TASK_CONTRACT",
    "IssueDeliveryReadbackRefused",
    "admit_issue_delivery_task",
    "compose_issue_delivery_readback",
    "read_issue_delivery_projection",
]
