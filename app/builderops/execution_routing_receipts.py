"""Append-only evidence for one bounded execution-routing canary.

The adapter deliberately uses the existing ``BuilderOpsReceipt`` store.  It
records launch intent, launch outcome, and the later verification observation;
it does not own worker lifecycle, verification, merge, or closure authority.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol

from app.builderops.delivery_orchestration_contracts import canonical_hash
from app.builderops.execution_routing import (
    ExecutionAttemptObservation,
    ExecutionRouteDecision,
    ExecutionRouteRequest,
)
from app.builderops.models import BuilderOpsValidationError, utc_now

CHAIN_VERSION = "builder_execution_routing_canary_chain.v1"
_EVENT_TYPE = "execution_routing_canary"
_ACTOR = {"actor_type": "agent", "id": "epic_dispatch"}
_HEX64 = re.compile(r"[0-9a-f]{64}")
_SAFE_REASON = re.compile(r"[a-z][a-z0-9_]{2,63}")


class ReceiptStore(Protocol):
    """The narrow existing BuilderOps store surface used by this adapter."""

    def append_receipt(self, **fields: Any) -> dict[str, Any]: ...

    def list_records(
        self, object_type: str | None = None
    ) -> list[dict[str, Any]]: ...


class CanaryReceiptEvidenceError(BuilderOpsValidationError):
    """Raised when canary evidence is absent, stale, or contradictory."""


@dataclass(frozen=True)
class CanaryReceiptChain:
    """Provenance needed to append a child of one attempt intent."""

    intent_receipt_id: str
    intent_event_hash: str
    repository: str
    issue_number: int
    route_lineage_id: str
    route_decision_id: str
    route_decision_hash: str
    context_pack_hash: str
    authority_hash: str
    verification_profile_hash: str
    attempt_id: str
    intent_attempt_hash: str


def _canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _attempt_payload(
    attempt: ExecutionAttemptObservation, *, repository: str | None
) -> dict[str, object]:
    return {
        "attempt_id": attempt.attempt_id,
        "attempt_hash": attempt.content_hash,
        "repository": repository,
        "attempt_number": attempt.attempt_number,
        "mode": attempt.mode,
        "requested_capability": attempt.requested_capability,
        "actual_capability": attempt.actual_capability,
        "provider": attempt.provider,
        "model": attempt.model,
        "reasoning_effort": attempt.reasoning_effort,
        "transition_kind": attempt.transition_kind,
        "transition_reason": attempt.transition_reason,
        "triggering_attempt_id": attempt.triggering_attempt_id,
        "triggering_attempt_hash": attempt.triggering_attempt_hash,
        "context_pack_hash": attempt.context_pack_hash,
        "authority_hash": attempt.authority_hash,
        "verification_profile_hash": attempt.verification_profile_hash,
        "outcome": attempt.outcome,
        "observed_at": attempt.observed_at,
    }


def _chain_payload(
    request: ExecutionRouteRequest,
    decision: ExecutionRouteDecision,
    attempt: ExecutionAttemptObservation,
    *,
    event: str,
    predecessor: Mapping[str, str] | None = None,
    acceptance: Mapping[str, object] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": CHAIN_VERSION,
        "event": event,
        "repository": request.repository,
        "issue_number": request.issue_number,
        "route_request": request.model_dump(mode="json"),
        "route_decision": decision.model_dump(mode="json"),
        "route_lineage_id": decision.route_lineage_id,
        "route_decision_id": decision.decision_id,
        "route_decision_hash": decision.content_hash,
        "semantic_hashes": {
            "context_pack_hash": decision.context_pack_hash,
            "authority_hash": decision.authority_hash,
            "verification_profile_hash": decision.verification_profile_hash,
        },
        "attempt": _attempt_payload(attempt, repository=request.repository),
        "predecessor": dict(predecessor) if predecessor is not None else None,
        "acceptance": dict(acceptance) if acceptance is not None else None,
        "lifecycle_authority": "none",
        "verification_waiver_authority": "none",
        "merge_authority": "none",
        "closure_authority": "none",
    }


def _body(record: Mapping[str, object]) -> Mapping[str, object] | None:
    raw = record.get("receipt_body")
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, Mapping) else None


def _same_event_attempt(
    record: Mapping[str, object], *, action: str, attempt_id: str
) -> bool:
    if record.get("event_type") != _EVENT_TYPE or record.get("action") != action:
        return False
    body = _body(record)
    attempt = body.get("attempt") if body is not None else None
    return isinstance(attempt, Mapping) and attempt.get("attempt_id") == attempt_id


def _append(
    store: ReceiptStore,
    payload: Mapping[str, object],
    *,
    action: str,
) -> dict[str, Any]:
    """Append exactly one immutable event, with read-before-write recovery."""

    body = _canonical_json(payload)
    event_hash = canonical_hash(payload)
    attempt = payload.get("attempt")
    if not isinstance(attempt, Mapping) or not isinstance(attempt.get("attempt_id"), str):
        raise CanaryReceiptEvidenceError("canary receipt attempt identity is malformed")
    attempt_id = str(attempt["attempt_id"])
    records = store.list_records("BuilderOpsReceipt")
    for record in records:
        if record.get("idempotency_key") == f"canary:{action}:{event_hash}":
            if record.get("receipt_body") != body:
                raise CanaryReceiptEvidenceError("canary receipt idempotency payload mismatch")
            return dict(record)
        if _same_event_attempt(record, action=action, attempt_id=attempt_id):
            if record.get("receipt_body") != body:
                raise CanaryReceiptEvidenceError(
                    "canary receipt has a contradictory event for the same attempt"
                )
            return dict(record)

    try:
        record = store.append_receipt(
            id=f"receipt_canary_{event_hash[:24]}",
            summary=f"Phase 2 canary {action.replace('_', ' ')}",
            event_type=_EVENT_TYPE,
            actor=_ACTOR,
            occurred_at=utc_now(),
            target_refs=[
                {
                    "ref_type": "builderops_object",
                    "ref": attempt_id,
                    "authority_surface": "builderops",
                }
            ],
            action=action,
            receipt_body=body,
            idempotency_key=f"canary:{action}:{event_hash}",
            source_refs=[
                {
                    "ref_type": "github_issue",
                    "ref": f"#{payload['issue_number']}",
                    "authority_surface": "github",
                }
            ],
            created_by=_ACTOR,
        )
    except (BuilderOpsValidationError, OSError) as exc:
        raise CanaryReceiptEvidenceError(
            "canary receipt was not durably appended"
        ) from exc
    if record.get("receipt_body") != body:
        raise CanaryReceiptEvidenceError("canary receipt readback does not match append payload")
    return record


def append_attempt_intent(
    store: ReceiptStore,
    request: ExecutionRouteRequest,
    decision: ExecutionRouteDecision,
    attempt: ExecutionAttemptObservation,
) -> CanaryReceiptChain:
    """Persist launch intent before any external launcher call."""

    if attempt.mode != "canary":
        raise CanaryReceiptEvidenceError("canary intent must use canary mode")
    if request.repository is None:
        raise CanaryReceiptEvidenceError(
            "canary intent requires a canonical originating repository"
        )
    payload = _chain_payload(request, decision, attempt, event="attempt_intent")
    record = _append(store, payload, action="canary_attempt_intent")
    return CanaryReceiptChain(
        intent_receipt_id=str(record["id"]),
        intent_event_hash=canonical_hash(payload),
        repository=request.repository,
        issue_number=request.issue_number,
        route_lineage_id=decision.route_lineage_id,
        route_decision_id=decision.decision_id,
        route_decision_hash=decision.content_hash,
        context_pack_hash=decision.context_pack_hash,
        authority_hash=decision.authority_hash,
        verification_profile_hash=decision.verification_profile_hash,
        attempt_id=attempt.attempt_id,
        intent_attempt_hash=attempt.content_hash,
    )


def attempt_intent_exists(
    store: ReceiptStore,
    request: ExecutionRouteRequest,
    decision: ExecutionRouteDecision,
    attempt: ExecutionAttemptObservation,
) -> bool:
    """Return whether the exact intent exists; callers must refuse relaunch."""

    payload = _chain_payload(request, decision, attempt, event="attempt_intent")
    body = _canonical_json(payload)
    for record in store.list_records("BuilderOpsReceipt"):
        if record.get("action") != "canary_attempt_intent":
            continue
        if record.get("receipt_body") == body:
            return True
        if _same_event_attempt(
            record, action="canary_attempt_intent", attempt_id=attempt.attempt_id
        ):
            raise CanaryReceiptEvidenceError(
                "canary attempt identity is already bound to different intent evidence"
            )
    return False


def _validate_chain(
    chain: CanaryReceiptChain,
    request: ExecutionRouteRequest,
    decision: ExecutionRouteDecision,
    attempt: ExecutionAttemptObservation,
) -> None:
    expected = (
        request.repository,
        request.issue_number,
        decision.route_lineage_id,
        decision.decision_id,
        decision.content_hash,
        decision.context_pack_hash,
        decision.authority_hash,
        decision.verification_profile_hash,
    )
    actual = (
        chain.repository,
        chain.issue_number,
        chain.route_lineage_id,
        chain.route_decision_id,
        chain.route_decision_hash,
        chain.context_pack_hash,
        chain.authority_hash,
        chain.verification_profile_hash,
    )
    if actual != expected:
        raise CanaryReceiptEvidenceError(
            "canary receipt chain provenance or semantic hashes do not match"
        )
    if (
        attempt.attempt_id != chain.attempt_id
        or request.repository != chain.repository
        or attempt.route_lineage_id != chain.route_lineage_id
        or attempt.route_decision_id != chain.route_decision_id
        or attempt.route_decision_hash != chain.route_decision_hash
        or attempt.context_pack_hash != chain.context_pack_hash
        or attempt.authority_hash != chain.authority_hash
        or attempt.verification_profile_hash != chain.verification_profile_hash
    ):
        raise CanaryReceiptEvidenceError(
            "canary receipt child is outside the intended attempt lineage"
        )


def append_attempt_outcome(
    store: ReceiptStore,
    chain: CanaryReceiptChain,
    request: ExecutionRouteRequest,
    decision: ExecutionRouteDecision,
    attempt: ExecutionAttemptObservation,
) -> dict[str, Any]:
    """Append one terminal launch outcome for an already-intended attempt."""

    _validate_chain(chain, request, decision, attempt)
    payload = _chain_payload(
        request,
        decision,
        attempt,
        event="attempt_outcome",
        predecessor={
            "receipt_id": chain.intent_receipt_id,
            "event_hash": chain.intent_event_hash,
        },
    )
    return _append(store, payload, action="canary_attempt_outcome")


def _validated_public_attempt(
    value: object,
    *,
    repository: str,
    route_lineage_id: str,
    route_decision_id: str,
    route_decision_hash: str,
    semantic_hashes: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise CanaryReceiptEvidenceError("canary receipt attempt is malformed")
    required = {
        "attempt_id",
        "attempt_hash",
        "repository",
        "attempt_number",
        "mode",
        "requested_capability",
        "actual_capability",
        "provider",
        "model",
        "reasoning_effort",
        "transition_kind",
        "transition_reason",
        "triggering_attempt_id",
        "triggering_attempt_hash",
        "context_pack_hash",
        "authority_hash",
        "verification_profile_hash",
        "outcome",
        "observed_at",
        "route_lineage_id",
        "route_decision_id",
        "route_decision_hash",
        "semantic_hashes",
    }
    if set(value) != required:
        raise CanaryReceiptEvidenceError("canary receipt attempt has an invalid field set")
    if (
        not isinstance(value.get("attempt_id"), str)
        or not isinstance(value.get("attempt_hash"), str)
        or _HEX64.fullmatch(str(value["attempt_hash"])) is None
        or not isinstance(value.get("attempt_number"), int)
        or isinstance(value.get("attempt_number"), bool)
        or value["attempt_number"] <= 0
        or value.get("repository") != repository
        or value.get("route_lineage_id") != route_lineage_id
        or value.get("route_decision_id") != route_decision_id
        or value.get("route_decision_hash") != route_decision_hash
        or value.get("semantic_hashes") != dict(semantic_hashes)
    ):
        raise CanaryReceiptEvidenceError("canary receipt attempt provenance is malformed")
    return dict(value)


def _canary_attempts(
    canary_receipt: Mapping[str, object],
) -> tuple[str, int, str, str, str, dict[str, str], list[dict[str, object]]]:
    if canary_receipt.get("schema_version") != "builder_execution_routing_canary.v1":
        raise CanaryReceiptEvidenceError("unsupported canary receipt schema")
    candidate = canary_receipt.get("candidate")
    route = canary_receipt.get("route")
    semantic_hashes = canary_receipt.get("semantic_hashes")
    raw_attempts = canary_receipt.get("attempts")
    candidate_repository = (
        candidate.get("repository") if isinstance(candidate, Mapping) else None
    )
    issue_number = candidate.get("issue_number") if isinstance(candidate, Mapping) else None
    work_class = candidate.get("work_class") if isinstance(candidate, Mapping) else None
    route_decision_id = route.get("route_decision_id") if isinstance(route, Mapping) else None
    repository = (
        candidate_repository.casefold()
        if isinstance(candidate_repository, str)
        else None
    )
    if (
        not isinstance(candidate, Mapping)
        or set(candidate) != {"repository", "issue_number", "work_class"}
        or not isinstance(repository, str)
        or re.fullmatch(r"[a-z0-9_.-]+/[a-z0-9_.-]+", repository) is None
        or not isinstance(issue_number, int)
        or isinstance(issue_number, bool)
        or issue_number <= 0
        or not isinstance(route, Mapping)
        or set(route)
        != {
            "route_lineage_id",
            "route_decision_id",
            "route_decision_hash",
            "requested_capability",
            "selected_capability",
            "allocation_state",
        }
        or work_class != "bounded_fast"
        or not isinstance(route_decision_id, str)
        or not route_decision_id
        or route.get("requested_capability") != "spark"
        or route.get("allocation_state")
        not in {
            "fresh_bonus_available",
            "allocation_observation_missing",
            "allocation_observation_stale",
            "allocation_economically_unavailable",
            "allocation_unknown",
        }
        or not isinstance(semantic_hashes, Mapping)
        or set(semantic_hashes) != {"context_pack_hash", "authority_hash", "verification_profile_hash"}
        or any(
            not isinstance(semantic_hashes[key], str)
            or _HEX64.fullmatch(str(semantic_hashes[key])) is None
            for key in semantic_hashes
        )
        or not isinstance(route.get("route_lineage_id"), str)
        or not route.get("route_lineage_id")
        or not isinstance(route.get("route_decision_hash"), str)
        or _HEX64.fullmatch(str(route["route_decision_hash"])) is None
        or not isinstance(raw_attempts, list)
        or canary_receipt.get("attempt_count") != len(raw_attempts)
        or not 1 <= len(raw_attempts) <= 2
    ):
        raise CanaryReceiptEvidenceError("canary receipt identity is malformed")
    normalized_hashes = {
        key: str(semantic_hashes[key])
        for key in ("context_pack_hash", "authority_hash", "verification_profile_hash")
    }
    attempts = [
        _validated_public_attempt(
            value,
            repository=repository,
            route_lineage_id=str(route["route_lineage_id"]),
            route_decision_id=route_decision_id,
            route_decision_hash=str(route["route_decision_hash"]),
            semantic_hashes=normalized_hashes,
        )
        for value in raw_attempts
    ]
    for expected_number, attempt in enumerate(attempts, start=1):
        if (
            attempt["attempt_number"] != expected_number
            or attempt["mode"] != "canary"
            or attempt["repository"] != repository
            or attempt["route_decision_id"] != route_decision_id
        ):
            raise CanaryReceiptEvidenceError(
                "canary receipt attempts are not in canonical order"
            )
    selected_capability = route.get("selected_capability")
    if selected_capability not in {"spark", "luna"}:
        raise CanaryReceiptEvidenceError("canary receipt route capability is malformed")
    first = attempts[0]
    if (
        first["transition_kind"] != "none"
        or first["transition_reason"] != "initial_route"
        or first["triggering_attempt_id"] is not None
        or first["triggering_attempt_hash"] is not None
        or first["actual_capability"] != selected_capability
    ):
        raise CanaryReceiptEvidenceError("canary receipt primary attempt is not canonical")
    if len(attempts) == 2:
        fallback = attempts[1]
        if (
            selected_capability != "spark"
            or first["actual_capability"] != "spark"
            or first["outcome"] != "allocation_unavailable"
            or fallback["actual_capability"] != "luna"
            or fallback["requested_capability"] != "spark"
            or fallback["transition_kind"] != "capacity_fallback"
            or fallback["transition_reason"]
            != "spark_allocation_unavailable_at_launch"
            or fallback["triggering_attempt_id"] != first["attempt_id"]
            or fallback["triggering_attempt_hash"] != first["attempt_hash"]
        ):
            raise CanaryReceiptEvidenceError(
                "canary receipt fallback sequence is not canonical"
            )
    return (
        repository,
        issue_number,
        str(route["route_lineage_id"]),
        route_decision_id,
        str(route["route_decision_hash"]),
        normalized_hashes,
        attempts,
    )


def _find_intent(
    store: ReceiptStore,
    *,
    repository: str,
    issue_number: int,
    route_lineage_id: str,
    route_decision_id: str,
    route_decision_hash: str,
    semantic_hashes: Mapping[str, str],
    attempt: Mapping[str, object],
) -> CanaryReceiptChain:
    attempt_id = attempt.get("attempt_id")
    attempt_hash = attempt.get("attempt_hash")
    if not isinstance(attempt_id, str) or not isinstance(attempt_hash, str):
        raise CanaryReceiptEvidenceError("canary attempt identity is malformed")
    for record in store.list_records("BuilderOpsReceipt"):
        if record.get("action") != "canary_attempt_intent":
            continue
        body = _body(record)
        if body is None:
            continue
        body_attempt = body.get("attempt")
        hashes = body.get("semantic_hashes")
        if not isinstance(body_attempt, Mapping) or body_attempt.get("attempt_id") != attempt_id:
            continue
        if (
            body.get("repository") != repository
            or body.get("issue_number") != issue_number
            or body.get("route_lineage_id") != route_lineage_id
            or body.get("route_decision_id") != route_decision_id
            or body.get("route_decision_hash") != route_decision_hash
            or hashes != dict(semantic_hashes)
        ):
            raise CanaryReceiptEvidenceError(
                "canary receipt does not match durable intent provenance"
            )
        decision_id = body.get("route_decision_id")
        if not isinstance(decision_id, str):
            raise CanaryReceiptEvidenceError("canary durable intent is malformed")
        return CanaryReceiptChain(
            intent_receipt_id=str(record["id"]),
            intent_event_hash=canonical_hash(body),
            repository=repository,
            issue_number=issue_number,
            route_lineage_id=route_lineage_id,
            route_decision_id=decision_id,
            route_decision_hash=route_decision_hash,
            context_pack_hash=semantic_hashes["context_pack_hash"],
            authority_hash=semantic_hashes["authority_hash"],
            verification_profile_hash=semantic_hashes["verification_profile_hash"],
            attempt_id=attempt_id,
            intent_attempt_hash=str(body_attempt.get("attempt_hash")),
        )
    raise CanaryReceiptEvidenceError("canary durable launch intent is unavailable")


def append_acceptance_observation(
    store: ReceiptStore,
    chain: CanaryReceiptChain,
    request: ExecutionRouteRequest,
    decision: ExecutionRouteDecision,
    attempt: ExecutionAttemptObservation,
    *,
    status: Literal["passed", "failed", "not_accepted"],
    reason: str | None = None,
    verification: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Append one evidence-only acceptance observation; never grants authority."""

    _validate_chain(chain, request, decision, attempt)
    if status == "not_accepted":
        if reason is None or _SAFE_REASON.fullmatch(reason) is None:
            raise CanaryReceiptEvidenceError("non-acceptance requires a typed reason")
    elif reason is not None:
        raise CanaryReceiptEvidenceError("accepted delivery result cannot carry a reason")
    safe_verification: dict[str, object] | None = None
    if verification is not None:
        safe_verification = {
            "receipt_hash": canonical_hash(dict(verification)),
            "verdict": verification.get("verdict"),
            "head_sha": verification.get("head_sha"),
            "run_id": verification.get("run_id"),
            "repository": verification.get("repository"),
            "pr_number": verification.get("pr_number"),
        }
    acceptance: dict[str, object] = {"status": status}
    if reason is not None:
        acceptance["reason"] = reason
    if safe_verification is not None:
        acceptance["verification"] = safe_verification
    payload = _chain_payload(
        request,
        decision,
        attempt,
        event="acceptance_observation",
        predecessor={
            "receipt_id": chain.intent_receipt_id,
            "event_hash": chain.intent_event_hash,
        },
        acceptance=acceptance,
    )
    return _append(store, payload, action="canary_acceptance_observation")


def record_acceptance_observation(
    store: ReceiptStore,
    canary_receipt: Mapping[str, object],
    verification_receipt: Mapping[str, object] | None,
    *,
    repository: str,
    pr_number: int,
    head_sha: str,
    governing_issue: int,
    run_id: str,
    verification_request: Mapping[str, object],
    not_accepted_reason: str | None = None,
) -> dict[str, Any]:
    """Consume a validated verifier result into the canary receipt chain.

    The verifier's full receipt is hashed, never copied into BuilderOps.  A
    passed observation requires exact repository, PR, issue, and head binding;
    absent or non-success verification becomes typed ``not_accepted`` evidence.
    """

    (
        originating_repository,
        issue_number,
        lineage,
        decision_id,
        decision_hash,
        semantic_hashes,
        public_attempts,
    ) = _canary_attempts(canary_receipt)
    _validate_canary_request_binding(
        canary_receipt,
        verification_request,
        repository=originating_repository,
        issue_number=issue_number,
        pr_number=pr_number,
        head_sha=head_sha,
        run_id=run_id,
    )
    if issue_number != governing_issue or pr_number <= 0 or not isinstance(head_sha, str):
        raise CanaryReceiptEvidenceError("canary and verification issue identity do not match")
    if (
        not isinstance(repository, str)
        or not repository.strip()
        or repository.casefold() != originating_repository
        or not run_id.strip()
    ):
        raise CanaryReceiptEvidenceError("verification repository identity is malformed")

    # The final bounded carrier is the only attempt eligible for the later
    # verification observation.  Its durable intent must predate acceptance.
    final_public_attempt = public_attempts[-1]
    chain = _find_intent(
        store,
        repository=originating_repository,
        issue_number=issue_number,
        route_lineage_id=lineage,
        route_decision_id=decision_id,
        route_decision_hash=decision_hash,
        semantic_hashes=semantic_hashes,
        attempt=final_public_attempt,
    )
    intent_body: Mapping[str, object] | None = None
    records = store.list_records("BuilderOpsReceipt")
    for record in records:
        if record.get("id") == chain.intent_receipt_id:
            intent_body = _body(record)
            break
    if intent_body is None:
        raise CanaryReceiptEvidenceError("canary durable launch intent is malformed")
    try:
        request = ExecutionRouteRequest.model_validate(intent_body["route_request"])
        decision = ExecutionRouteDecision.model_validate(intent_body["route_decision"])
        attempt_data = dict(final_public_attempt)
        public_attempt_hash = attempt_data.pop("attempt_hash")
        attempt_data.pop("semantic_hashes", None)
        attempt_data.pop("repository", None)
        attempt = ExecutionAttemptObservation.model_validate(attempt_data)
    except (KeyError, TypeError, ValueError) as exc:
        raise CanaryReceiptEvidenceError("canary route-bound attempt is malformed") from exc
    if not isinstance(public_attempt_hash, str) or attempt.content_hash != public_attempt_hash:
        raise CanaryReceiptEvidenceError("canary public attempt hash does not verify")
    _validate_chain(chain, request, decision, attempt)

    outcome_found = False
    for record in records:
        body = _body(record)
        if body is None or body.get("event") != "attempt_outcome":
            continue
        body_attempt = body.get("attempt")
        if not isinstance(body_attempt, Mapping):
            continue
        if (
            body_attempt.get("attempt_id") == attempt.attempt_id
            and body_attempt.get("attempt_hash") == attempt.content_hash
            and body.get("repository") == originating_repository
            and body.get("issue_number") == issue_number
            and body.get("route_lineage_id") == lineage
            and body.get("route_decision_id") == decision_id
            and body.get("route_decision_hash") == decision_hash
            and body.get("semantic_hashes") == semantic_hashes
            and body.get("predecessor") == {
                "receipt_id": chain.intent_receipt_id,
                "event_hash": chain.intent_event_hash,
            }
        ):
            outcome_found = True
            break
    if not outcome_found:
        raise CanaryReceiptEvidenceError("canary attempt outcome is unavailable")

    status: Literal["passed", "failed", "not_accepted"]
    reason: str | None = None
    verdict: object = (
        verification_receipt.get("verdict")
        if verification_receipt is not None
        else None
    )
    if verdict in {"verified", "delivered"}:
        assert verification_receipt is not None
        if any(
            verification_receipt.get(key) != expected
            for key, expected in (
                ("repository", repository),
                ("pr_number", pr_number),
                ("head_sha", head_sha),
                ("run_id", run_id),
            )
        ):
            status = "not_accepted"
            reason = (
                "verification_head_mismatch"
                if verification_receipt.get("head_sha") != head_sha
                else "verification_identity_mismatch"
            )
        elif attempt.outcome not in {"started", "succeeded"}:
            status = "not_accepted"
            reason = f"canary_attempt_{attempt.outcome}"
        else:
            status = "passed"
    else:
        status = "not_accepted"
        reason = not_accepted_reason
        if reason is None:
            if verification_receipt is None:
                reason = "verification_not_reached"
            elif isinstance(verdict, str) and _SAFE_REASON.fullmatch(
                f"verification_verdict_{verdict}"
            ):
                reason = f"verification_verdict_{verdict}"
            else:
                reason = "verification_result_malformed"

    verification_for_storage = dict(verification_receipt or {})
    verification_for_storage.setdefault("repository", repository)
    verification_for_storage.setdefault("pr_number", pr_number)
    verification_for_storage.setdefault("head_sha", head_sha)
    verification_for_storage.setdefault("run_id", run_id)
    return append_acceptance_observation(
        store,
        chain,
        request,
        decision,
        attempt,
        status=status,
        reason=reason,
        verification=verification_for_storage,
    )


_CANARY_IDENTITY_FIELDS = {
    "schema_version",
    "repository",
    "issue_number",
    "pr_number",
    "head_sha",
    "verification_run_id",
    "route_lineage_id",
    "route_decision_id",
    "route_decision_hash",
    "semantic_hashes",
    "attempts",
    "receipt_hash",
}
_CANARY_ATTEMPT_IDENTITY_FIELDS = {
    "attempt_id",
    "attempt_hash",
    "attempt_number",
    "repository",
    "route_lineage_id",
    "route_decision_id",
    "route_decision_hash",
    "semantic_hashes",
}


def _canary_identity(
    canary_receipt: Mapping[str, object],
    request: Mapping[str, object],
) -> dict[str, object]:
    (
        repository,
        issue_number,
        lineage,
        decision_id,
        decision_hash,
        semantic_hashes,
        attempts,
    ) = _canary_attempts(canary_receipt)
    request_repository = request.get("repository")
    linked_issue = request.get("linked_issue")
    pr_number = request.get("pr_number")
    head_sha = request.get("current_head_sha")
    idempotency_key = request.get("idempotency_key")
    stage = request.get("stage", "verification")
    if (
        not isinstance(request_repository, str)
        or request_repository.casefold() != repository
        or not isinstance(linked_issue, int)
        or isinstance(linked_issue, bool)
        or linked_issue != issue_number
        or not isinstance(pr_number, int)
        or isinstance(pr_number, bool)
        or pr_number <= 0
        or not isinstance(head_sha, str)
        or not isinstance(idempotency_key, str)
        or len(idempotency_key) < 16
        or stage != "verification"
    ):
        raise CanaryReceiptEvidenceError(
            "canary receipt does not match verification request identity"
        )
    identity_attempts = [
        {
            key: attempt[key]
            for key in _CANARY_ATTEMPT_IDENTITY_FIELDS
        }
        for attempt in attempts
    ]
    return {
        "schema_version": "builder_execution_routing_canary.v1",
        "repository": repository,
        "issue_number": issue_number,
        "pr_number": pr_number,
        "head_sha": head_sha,
        "verification_run_id": (
            f"vrun-{canonical_hash([repository, pr_number, stage])[:16]}"
        ),
        "route_lineage_id": lineage,
        "route_decision_id": decision_id,
        "route_decision_hash": decision_hash,
        "semantic_hashes": dict(semantic_hashes),
        "attempts": identity_attempts,
        "receipt_hash": canonical_hash(dict(canary_receipt)),
    }


def bind_canary_receipt_to_verification_request(
    request: Mapping[str, object], canary_receipt: Mapping[str, object]
) -> dict[str, object]:
    """Attach exact canary lineage to the authenticated verification request."""

    result = dict(request)
    identity = _canary_identity(canary_receipt, result)
    existing = result.get("canary_identity")
    if existing is not None and existing != identity:
        raise CanaryReceiptEvidenceError(
            "verification request canary identity does not match receipt"
        )
    result["canary_identity"] = identity
    return result


def validate_canary_receipt_request_binding(
    canary_receipt: Mapping[str, object],
    verification_request: Mapping[str, object],
) -> None:
    """Fail closed unless the request carries the exact receipt identity."""

    expected = _canary_identity(canary_receipt, verification_request)
    if verification_request.get("canary_identity") != expected:
        raise CanaryReceiptEvidenceError(
            "canary receipt is not bound to the verification request lineage"
        )


def _validate_canary_request_binding(
    canary_receipt: Mapping[str, object],
    verification_request: Mapping[str, object],
    *,
    repository: str,
    issue_number: int,
    pr_number: int,
    head_sha: str,
    run_id: str,
) -> None:
    expected = _canary_identity(canary_receipt, verification_request)
    if (
        verification_request.get("canary_identity") != expected
        or expected["repository"] != repository
        or expected["issue_number"] != issue_number
        or expected["pr_number"] != pr_number
        or expected["head_sha"] != head_sha
        or expected["verification_run_id"] != run_id
    ):
        raise CanaryReceiptEvidenceError(
            "canary receipt is not bound to the verification request lineage"
        )


__all__ = [
    "CHAIN_VERSION",
    "CanaryReceiptChain",
    "CanaryReceiptEvidenceError",
    "ReceiptStore",
    "append_acceptance_observation",
    "append_attempt_intent",
    "append_attempt_outcome",
    "attempt_intent_exists",
    "record_acceptance_observation",
    "bind_canary_receipt_to_verification_request",
    "validate_canary_receipt_request_binding",
]
