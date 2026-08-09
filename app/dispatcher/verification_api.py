"""BuilderOps API-backed durable adapter for the delivered verifier.

The review/repair algorithm remains in ``verification_consumer`` and
``verification_agent_loop``. This module replaces their durable port and
separates a review-only ``verified`` receipt from the host-fenced merge effect:
verification runs are BuilderOps tasks, attempts are BuilderOps attempts, and
pre-effect/merge-ready authority is committed through the shared task/outbox
transaction. It never opens dispatcher SQLite or PostgreSQL.
"""

from __future__ import annotations

import builtins
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Protocol

from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ControlPlaneClientError,
    ControlPlaneNotFoundError,
)
from app.dispatcher.verification_dispatch import (
    ACTIVE_STATES,
    REPAIR_ATTEMPT_LIMITS,
    REPAIR_BUDGET_POLICY_LEGACY,
    REPAIR_BUDGET_POLICY_MECHANISM,
    TERMINAL_STATES,
    VerificationBackoffPending,
    VerificationRun,
    VerificationSubscriptionBusy,
    _CanonicalVerificationChainToken,
    _LiveObservedVerificationRequest,
    _attempt_plan,
    _canonical_request_projection,
    _current_head_replay_authority_matches,
    _live_takeover_authority_matches,
    _projected_mechanism_id,
    _request_closing_authority,
    _request_final_review_rounds,
    _validate_request,
)

_TASK_PREFIX = "vrun-"
_PAYLOAD_CONTRACT = "builderops_verification_run.v1"
_ACTIVE_KERNEL_STATES = frozenset({"ready", "claimed"})


class VerificationEffectOutbox(Protocol):
    def claim(self, operation_key: str) -> Mapping[str, object]: ...

    def recover(self, operation_key: str) -> Mapping[str, object]: ...

    def status(self, operation_key: str) -> Mapping[str, object]: ...

    def mark_unknown(
        self, claim: Mapping[str, object], *, detail: str
    ) -> None: ...

    def reconcile(
        self,
        claim: Mapping[str, object],
        *,
        observed_applied: bool,
        terminal_unknown: bool = False,
        evidence: Mapping[str, object],
    ) -> Mapping[str, object]: ...


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(*parts: object) -> str:
    return hashlib.sha256(_canonical(list(parts)).encode()).hexdigest()


def _authority_digest(value: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical(dict(value)).encode()).hexdigest()


def _outbox_operation_key(
    repository: str, idempotency_key: str, effect_type: str
) -> str:
    return hashlib.sha256(
        _canonical(
            {
                "repository": repository,
                "idempotency_key": idempotency_key,
                "effect_type": effect_type,
            }
        ).encode()
    ).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _required_int(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"verification {field} is malformed")
    return value


def _snapshot_payload(snapshot: Mapping[str, object]) -> Mapping[str, object]:
    payload = snapshot.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("BuilderOps verification task payload is malformed")
    return payload


def _lease_id(lease: Mapping[str, object]) -> str:
    return "vlease-" + _digest(
        lease.get("resource_id"),
        lease.get("holder"),
        lease.get("fencing_token"),
    )[:16]


def _lease_json(snapshot: Mapping[str, object]) -> dict[str, object] | None:
    lease = snapshot.get("lease")
    if not isinstance(lease, Mapping):
        return None
    result = dict(lease)
    expires = result.get("expires_at")
    if isinstance(expires, datetime):
        result["expires_at"] = expires.isoformat()
    return result


def _run_document(run: VerificationRun) -> dict[str, object]:
    return {
        "contract_version": _PAYLOAD_CONTRACT,
        "run": asdict(run),
        "exceptions": [],
    }


def _run_from_snapshot(snapshot: Mapping[str, object]) -> VerificationRun:
    payload = snapshot.get("payload")
    if (
        not isinstance(payload, Mapping)
        or payload.get("contract_version") != _PAYLOAD_CONTRACT
        or not isinstance(payload.get("run"), Mapping)
    ):
        raise ValueError("BuilderOps verification task payload is malformed")
    raw = dict(payload["run"])
    request = raw.get("request")
    if not isinstance(request, dict):
        raise ValueError("BuilderOps verification request payload is malformed")
    _validate_request(request)
    for field in ("supporting_authority", "closing_authority"):
        value = raw.get(field)
        if not isinstance(value, (list, tuple)):
            raise ValueError(f"BuilderOps verification {field} is malformed")
        raw[field] = tuple(value)
    run = VerificationRun(**raw)
    lease = _lease_json(snapshot)
    if snapshot.get("state") == "claimed" and lease is not None:
        expires = lease.get("expires_at")
        return replace(
            run,
            claimed_by=str(lease["holder"]),
            lease_id=_lease_id(lease),
            lease_expires_at=str(expires) if expires is not None else None,
        )
    return replace(run, claimed_by=None, lease_id=None, lease_expires_at=None)


def _payload_for(
    snapshot: Mapping[str, object], run: VerificationRun
) -> dict[str, object]:
    payload = snapshot.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("BuilderOps verification task payload is malformed")
    result = dict(payload)
    result["run"] = asdict(run)
    return result


def project_verification_run(
    request: Mapping[str, object],
) -> VerificationRun:
    """Validate and project one request without creating durable authority."""
    projected = _canonical_request_projection(request)
    _validate_request(projected)
    repository = str(projected["repository"])
    supporting = projected["supporting_issues"]
    if not isinstance(supporting, builtins.list):
        raise ValueError("verification supporting_issues is malformed")
    run_id = "vrun-" + _digest(
        repository.lower(),
        projected["pr_number"],
        projected["stage"],
    )[:16]
    return VerificationRun(
        run_id=run_id,
        idempotency_key=str(projected["idempotency_key"]),
        repository=repository,
        pr_number=_required_int(projected["pr_number"], "pr_number"),
        requested_head_sha=str(projected["current_head_sha"]),
        current_head_sha=str(projected["current_head_sha"]),
        verified_head_sha=None,
        stage=str(projected["stage"]),
        status="queued",
        authority_state="canonical",
        claimed_by=None,
        lease_id=None,
        lease_expires_at=None,
        coordinator_session_id=None,
        request=dict(projected),
        supporting_authority=tuple(
            _required_int(value, "supporting issue") for value in supporting
        ),
        closing_authority=tuple(_request_closing_authority(projected)),
        repair_budget_policy=REPAIR_BUDGET_POLICY_MECHANISM,
        context_pack=None,
        terminal_receipt=None,
        stop_reason=None,
        retry_after=None,
    )


class BuilderOpsVerificationLedger:
    """Verification ledger port implemented exclusively through the BCP API."""

    def __init__(
        self,
        client: BuilderOpsControlPlaneClient,
        *,
        repository: str,
        source_ref: str = "github-issue:3603",
        effect_outbox: VerificationEffectOutbox | None = None,
    ) -> None:
        self.client = client
        self.repository = repository.lower()
        self.effect_outbox = effect_outbox
        self._effect_claims: dict[str, Mapping[str, object]] = {}
        self._unknown_effects: set[str] = set()
        self.envelope = {
            "repository": self.repository,
            "scope": "verification",
            "stack": "builderops-control-plane",
            "source_refs": [source_ref],
            "schema_version": 1,
        }

    def _snapshot(self, run_id: str) -> dict[str, object]:
        try:
            return self.client.get_task(repository=self.repository, task_id=run_id)
        except ControlPlaneNotFoundError as exc:
            raise ValueError(f"verification run {run_id} not found") from exc

    def _snapshots(self) -> builtins.list[dict[str, object]]:
        return self.client.list_tasks(
            repository=self.repository, task_prefix=_TASK_PREFIX
        )

    def _chain(
        self, repository: str, pr_number: int, stage: str
    ) -> builtins.list[dict[str, object]]:
        result: builtins.list[dict[str, object]] = []
        for snapshot in self._snapshots():
            try:
                run = _run_from_snapshot(snapshot)
            except ValueError:
                continue
            if (
                run.repository.lower() == repository.lower()
                and run.pr_number == pr_number
                and run.stage == stage
            ):
                result.append(snapshot)
        return result

    def canonical_chain_token(
        self, request: Mapping[str, object]
    ) -> _CanonicalVerificationChainToken:
        projected_run = project_verification_run(request)
        projected = projected_run.request
        repository = str(projected["repository"])
        pr_number = _required_int(projected["pr_number"], "pr_number")
        stage = str(projected["stage"])
        linked_issue = _required_int(projected["linked_issue"], "linked_issue")
        snapshots = self._chain(repository, pr_number, stage)
        fingerprint = _digest(
            [
                {
                    "task_id": snapshot.get("task_id"),
                    "state": snapshot.get("state"),
                    "version": snapshot.get("version"),
                    "payload": snapshot.get("payload"),
                    "attempts": self.client.list_attempts(
                        repository=self.repository,
                        task_id=str(snapshot.get("task_id")),
                    ),
                }
                for snapshot in snapshots
            ]
        )
        return _CanonicalVerificationChainToken(
            repository=repository,
            pr_number=pr_number,
            stage=stage,
            linked_issue=linked_issue,
            fingerprint=fingerprint,
        )

    def ingest(self, request: Mapping[str, object]) -> VerificationRun:
        live_observation = (
            request.live_observation
            if isinstance(request, _LiveObservedVerificationRequest)
            else None
        )
        canonical_token = (
            request.canonical_chain_token
            if isinstance(request, _LiveObservedVerificationRequest)
            else None
        )
        projected_run = project_verification_run(request)
        projected = projected_run.request
        repository = str(projected["repository"])
        if repository.lower() != self.repository:
            raise ValueError("verification request does not match API ledger RepoRef")
        run_id = projected_run.run_id
        try:
            existing = self._snapshot(run_id)
        except ValueError:
            existing = None
        if existing is not None:
            run = _run_from_snapshot(existing)
            if run.request == projected:
                return run

        chain = self._chain(
            repository,
            _required_int(projected["pr_number"], "pr_number"),
            str(projected["stage"]),
        )
        if canonical_token is not None:
            current_token = self.canonical_chain_token(projected)
            if (
                canonical_token.repository != current_token.repository
                or canonical_token.pr_number != current_token.pr_number
                or canonical_token.stage != current_token.stage
                or canonical_token.linked_issue != current_token.linked_issue
                or canonical_token.fingerprint != current_token.fingerprint
            ):
                raise ValueError(
                    "verification canonical authority changed during live observation"
                )
        if existing is not None:
            candidate = _run_from_snapshot(existing)
            if candidate.status in TERMINAL_STATES:
                raise ValueError(
                    f"verification canonical chain is terminal: {candidate.status}"
                )
            if candidate.current_head_sha == projected["current_head_sha"]:
                if not _current_head_replay_authority_matches(
                    live_observation,
                    projected,
                    candidate.request,
                    candidate.supporting_authority,
                ):
                    raise ValueError(
                        "verification active replay authority does not match canonical run"
                    )
                return candidate
            if not _live_takeover_authority_matches(
                live_observation,
                projected,
                candidate.request,
                candidate.supporting_authority,
            ):
                raise ValueError(
                    "verification artifact head does not match canonical run"
                )
            incoming_supporting = projected["supporting_issues"]
            if not isinstance(incoming_supporting, builtins.list):
                raise ValueError("verification supporting_issues is malformed")
            takeover = replace(
                candidate,
                current_head_sha=str(projected["current_head_sha"]),
                verified_head_sha=None,
                supporting_authority=tuple(
                    _required_int(value, "supporting issue")
                    for value in incoming_supporting
                ),
                status="claimed",
                coordinator_session_id=None,
                context_pack=None,
                terminal_receipt=None,
                stop_reason=None,
                retry_after=None,
            )
            takeover_payload = _payload_for(existing, takeover)
            self._settle_prior_head_effect(
                candidate,
                takeover_head=str(projected["current_head_sha"]),
                payload=takeover_payload,
            )
            takeover_payload.pop("pending_privileged_effect", None)
            takeover_payload.pop("attempt_write_seal", None)
            takeover_payload.pop("merge_ready_receipt", None)
            claimed_response = self.client.claim_task(
                envelope=self.envelope,
                task_id=candidate.run_id,
                idempotency_key=(
                    f"verification-head-takeover-claim:{candidate.run_id}:"
                    f"{projected['current_head_sha']}:{existing['version']}"
                ),
                request=takeover_payload,
                ttl_seconds=60,
            )
            takeover_lease = claimed_response.get("lease")
            if not isinstance(takeover_lease, Mapping):
                raise ValueError("verification head takeover returned no lease")
            claimed_snapshot = self._snapshot(candidate.run_id)
            queued = replace(
                takeover,
                status="queued",
                claimed_by=None,
                lease_id=None,
                lease_expires_at=None,
            )
            self.client.release_task(
                envelope=self.envelope,
                lease=dict(takeover_lease),
                idempotency_key=(
                    f"verification-head-takeover-commit:{candidate.run_id}:"
                    f"{projected['current_head_sha']}:{existing['version']}"
                ),
                request=_payload_for(existing, queued),
                expected_version=_required_int(
                    claimed_snapshot.get("version"), "task version"
                ),
            )
            return queued
        executable = [
            _run_from_snapshot(snapshot)
            for snapshot in chain
            if snapshot.get("state") in _ACTIVE_KERNEL_STATES
        ]
        if executable:
            if len(executable) != 1:
                raise ValueError("verification canonical chain is ambiguous")
            current = executable[0]
            if (
                current.current_head_sha == projected["current_head_sha"]
                and current.request == projected
            ):
                return current
            # Head takeovers are deliberately fail-closed here. The existing
            # consumer can resume/rebind under its exact lease; an unrelated
            # artifact cannot create a second authority chain.
            raise ValueError("verification canonical chain already exists")
        if chain:
            raise ValueError("verification terminal chain requires lifecycle decision")

        run = projected_run
        try:
            self.client.transition_task(
                envelope=self.envelope,
                task_id=run_id,
                to_state="ready",
                idempotency_key=f"verification-ingest:{run.idempotency_key}",
                request=_run_document(run),
            )
        except ControlPlaneClientError:
            # A concurrent artifact for the same canonical PR/stage chain can
            # win after our optimistic live observation. Exact replay is safe;
            # divergent authority remains a hard conflict.
            concurrent = self.get(run_id)
            if concurrent is not None and concurrent.request == projected:
                return concurrent
            raise
        return self.get(run_id) or run

    def _settle_prior_head_effect(
        self,
        run: VerificationRun,
        *,
        takeover_head: str,
        payload: Mapping[str, object],
    ) -> None:
        """Terminalize a stale read-only model effect before head takeover.

        A GitHub effect is never safe to compensate without repository
        readback. Model coordinator output, however, is review-only and can be
        durably discarded when its head is superseded. The outbox operation is
        first fenced (or recovered), then reconciled as a successful terminal
        no-effect so it cannot later be replayed against either head.
        """

        pending = payload.get("pending_privileged_effect")
        if not isinstance(pending, Mapping):
            return
        if self.effect_outbox is None:
            raise ValueError(
                "verification head takeover cannot settle its pending effect"
            )
        operation_key = pending.get("operation_key")
        effect_type = pending.get("effect_type")
        pending_head = pending.get("head_sha")
        if (
            not isinstance(operation_key, str)
            or pending.get("task_id") != run.run_id
            or not isinstance(effect_type, str)
            or pending_head != run.current_head_sha
        ):
            raise ValueError(
                "verification head takeover found a malformed effect binding"
            )
        status = self.effect_outbox.status(operation_key).get("status")
        if status in {"succeeded", "dead_letter"}:
            return
        if effect_type != "model.verification_coordinator":
            raise ValueError(
                "verification head takeover requires GitHub effect readback"
            )
        if status == "pending":
            claim = self.effect_outbox.claim(operation_key)
            self._validate_effect_claim(
                claim,
                operation_key=operation_key,
                run_id=run.run_id,
                effect_type=effect_type,
                require_eligible=True,
            )
            self._effect_claims[operation_key] = claim
        elif status in {"claimed", "unknown"}:
            self.recover_effect(
                operation_key,
                run_id=run.run_id,
                effect_type=effect_type,
            )
        else:
            raise ValueError(
                "verification head takeover effect has no durable authority"
            )
        self.finish_effect(
            operation_key,
            observed_applied=True,
            evidence={
                "outcome": "terminal_no_effect",
                "reason": "head_superseded",
                "old_head_sha": run.current_head_sha,
                "new_head_sha": takeover_head,
                "model_output_applied": False,
            },
        )

    def get(self, run_id: str) -> VerificationRun | None:
        try:
            return _run_from_snapshot(self._snapshot(run_id))
        except ValueError as exc:
            if "not found" in str(exc):
                return None
            raise

    def list(
        self, *, limit: int = 20, status: str | None = None
    ) -> builtins.list[VerificationRun]:
        if limit <= 0:
            raise ValueError("verification status limit must be positive")
        runs = [_run_from_snapshot(snapshot) for snapshot in self._snapshots()]
        if status is not None:
            runs = [run for run in runs if run.status == status]
        return runs[:limit]

    @staticmethod
    def _assert_lease(
        snapshot: Mapping[str, object], holder: str, lease_id: str
    ) -> dict[str, object]:
        lease = _lease_json(snapshot)
        if (
            snapshot.get("state") != "claimed"
            or lease is None
            or _lease_id(lease) != lease_id
        ):
            raise ValueError("verification API lease ownership mismatch")
        expires = lease.get("expires_at")
        if not isinstance(expires, str):
            raise ValueError("verification API lease expiry is malformed")
        if datetime.fromisoformat(expires.replace("Z", "+00:00")) <= datetime.now(
            timezone.utc
        ):
            raise ValueError("verification API lease expired")
        return lease

    def claim(
        self, run_id: str, holder: str, ttl_seconds: int = 900
    ) -> VerificationRun:
        snapshot = self._snapshot(run_id)
        run = _run_from_snapshot(snapshot)
        if run.status == "backoff" and run.retry_after:
            retry = datetime.fromisoformat(run.retry_after.replace("Z", "+00:00"))
            if retry > datetime.now(timezone.utc):
                raise VerificationBackoffPending(
                    f"verification run {run_id} is deferred until {run.retry_after}"
                )
        if run.status not in {"queued", "backoff"}:
            if run.status in ACTIVE_STATES and run.lease_expires_at:
                expires = datetime.fromisoformat(
                    run.lease_expires_at.replace("Z", "+00:00")
                )
                if expires > datetime.now(timezone.utc):
                    raise VerificationSubscriptionBusy(
                        f"verification subscription occupied by {run_id}"
                    )
            elif run.status not in ACTIVE_STATES:
                raise ValueError(f"verification run {run_id} is not claimable")
        claimed = replace(run, status="claimed", claimed_by=holder)
        response = self.client.claim_task(
            envelope=self.envelope,
            task_id=run_id,
            idempotency_key=f"verification-claim:{run_id}:{snapshot['version']}",
            request=_payload_for(snapshot, claimed),
            ttl_seconds=ttl_seconds,
            require_new_fence=run.lease_id is not None,
        )
        lease = response.get("lease")
        if not isinstance(lease, Mapping):
            raise ValueError("BuilderOps claim returned no fenced lease")
        return replace(
            claimed,
            claimed_by=str(lease["holder"]),
            lease_id=_lease_id(lease),
            lease_expires_at=str(lease["expires_at"]),
        )

    def heartbeat(
        self, run_id: str, holder: str, lease_id: str, ttl_seconds: int = 900
    ) -> VerificationRun:
        snapshot = self._snapshot(run_id)
        lease = self._assert_lease(snapshot, holder, lease_id)
        response = self.client.heartbeat_task(
            envelope=self.envelope,
            lease=lease,
            idempotency_key=(
                f"verification-heartbeat:{run_id}:"
                f"{_digest(lease.get('fencing_token'), lease.get('expires_at'))[:20]}"
            ),
            request=dict(_snapshot_payload(snapshot)),
            ttl_seconds=ttl_seconds,
        )
        renewed = response.get("lease")
        if not isinstance(renewed, Mapping):
            raise ValueError("BuilderOps heartbeat returned no fenced lease")
        run = _run_from_snapshot(snapshot)
        return replace(
            run,
            claimed_by=str(renewed["holder"]),
            lease_id=_lease_id(renewed),
            lease_expires_at=str(renewed["expires_at"]),
        )

    def _transition_claimed(
        self,
        run_id: str,
        holder: str,
        lease_id: str,
        operation: str,
        update: Callable[[VerificationRun], VerificationRun],
        *,
        kernel_state: str = "claimed",
        release: bool = False,
        outbox: Mapping[str, object] | None = None,
    ) -> VerificationRun:
        snapshot = self._snapshot(run_id)
        lease = self._assert_lease(snapshot, holder, lease_id)
        run = update(_run_from_snapshot(snapshot))
        payload = _payload_for(snapshot, run)
        idempotency_key = (
            f"verification-{operation}:{run_id}:{snapshot['version']}:"
            f"{_digest(payload, outbox)[:16]}"
        )
        if release:
            if outbox is not None:
                raise ValueError("terminal task release cannot carry a new outbox intent")
            if kernel_state == "ready":
                self.client.release_task(
                    envelope=self.envelope,
                    lease=lease,
                    idempotency_key=idempotency_key,
                    request=payload,
                    expected_version=_required_int(
                        snapshot.get("version"), "task version"
                    ),
                )
            elif kernel_state == "completed":
                self.client.complete_task(
                    envelope=self.envelope,
                    lease=lease,
                    idempotency_key=idempotency_key,
                    request=payload,
                    expected_version=_required_int(
                        snapshot.get("version"), "task version"
                    ),
                )
            else:
                raise ValueError("unsupported released verification kernel state")
        else:
            self.client.transition_task(
                envelope=self.envelope,
                task_id=run_id,
                to_state=kernel_state,
                idempotency_key=idempotency_key,
                request=payload,
                outbox=outbox,
                lease=lease,
                expected_states=("claimed",),
                expected_version=_required_int(
                    snapshot.get("version"), "task version"
                ),
            )
        return replace(
            run,
            claimed_by=None if release else holder,
            lease_id=None if release else lease_id,
            lease_expires_at=None if release else str(lease["expires_at"]),
        )

    def start(
        self,
        run_id: str,
        holder: str,
        lease_id: str,
        session_id: str,
        context_pack: Mapping[str, object],
    ) -> VerificationRun:
        return self._transition_claimed(
            run_id,
            holder,
            lease_id,
            "start",
            lambda run: replace(
                run,
                status="running",
                coordinator_session_id=session_id,
                context_pack=dict(context_pack),
            ),
        )

    def terminal(
        self,
        run_id: str,
        status: str,
        receipt: Mapping[str, object],
        *,
        reason: str | None = None,
        holder: str,
        lease_id: str,
    ) -> VerificationRun:
        if status not in TERMINAL_STATES:
            raise ValueError("invalid verification terminal status")
        if status == "completed" and not self.closure_ready(run_id):
            raise ValueError("completed requires the required fresh clean review rounds")
        return self._transition_claimed(
            run_id,
            holder,
            lease_id,
            "terminal",
            lambda run: replace(
                run,
                status=status,
                terminal_receipt=dict(receipt),
                stop_reason=reason,
                verified_head_sha=(
                    run.current_head_sha
                    if status == "completed"
                    else run.verified_head_sha
                ),
            ),
            kernel_state="completed",
            release=True,
        )

    def rebind_head(
        self,
        run_id: str,
        new_head_sha: str,
        *,
        expected_head_sha: str,
        observed_repository: str,
        observed_pr_number: int,
        observed_head_sha: str,
        holder: str,
        lease_id: str,
    ) -> VerificationRun:
        if re.fullmatch(r"[0-9a-fA-F]{40}", new_head_sha) is None:
            raise ValueError("malformed verification rebind head")

        def update(run: VerificationRun) -> VerificationRun:
            if (
                run.current_head_sha != expected_head_sha
                or run.repository != observed_repository
                or run.pr_number != observed_pr_number
                or new_head_sha != observed_head_sha
            ):
                raise ValueError("verification rebind live PR identity mismatch")
            return replace(run, current_head_sha=new_head_sha, verified_head_sha=None)

        return self._transition_claimed(
            run_id, holder, lease_id, "rebind", update
        )

    def backoff(
        self,
        run_id: str,
        receipt: Mapping[str, object],
        retry_after: str,
        *,
        holder: str,
        lease_id: str,
    ) -> VerificationRun:
        datetime.fromisoformat(retry_after.replace("Z", "+00:00"))
        return self._transition_claimed(
            run_id,
            holder,
            lease_id,
            "backoff",
            lambda run: replace(
                run,
                status="backoff",
                terminal_receipt=dict(receipt),
                retry_after=retry_after,
            ),
            kernel_state="ready",
            release=True,
        )

    def _claim_for_unowned_mutation(self, run_id: str) -> tuple[str, str]:
        claimed = self.claim(run_id, "verification-api-transition", ttl_seconds=60)
        if claimed.claimed_by is None or claimed.lease_id is None:
            raise ValueError("verification unowned transition claim failed")
        return claimed.claimed_by, claimed.lease_id

    def defer_unclaimed(
        self, run_id: str, receipt: Mapping[str, object], retry_after: str
    ) -> VerificationRun:
        holder, lease_id = self._claim_for_unowned_mutation(run_id)
        return self.backoff(
            run_id,
            receipt,
            retry_after,
            holder=holder,
            lease_id=lease_id,
        )

    def supersede_unclaimed(
        self, run_id: str, receipt: Mapping[str, object], *, reason: str
    ) -> VerificationRun:
        holder, lease_id = self._claim_for_unowned_mutation(run_id)
        return self._transition_claimed(
            run_id,
            holder,
            lease_id,
            "supersede",
            lambda run: replace(
                run,
                status="superseded",
                terminal_receipt=dict(receipt),
                stop_reason=reason,
            ),
            kernel_state="completed",
            release=True,
        )

    def attempts(self, run_id: str) -> builtins.list[dict[str, object]]:
        rows = self.client.list_attempts(
            repository=self.repository, task_id=run_id
        )
        result: builtins.list[dict[str, object]] = []
        for row in rows:
            payload = row.get("payload")
            if not isinstance(payload, Mapping):
                raise ValueError("BuilderOps verification attempt is malformed")
            if isinstance(payload.get("batch_events"), builtins.list):
                for event in payload["batch_events"]:
                    if not isinstance(event, Mapping):
                        raise ValueError("BuilderOps verification attempt batch is malformed")
                    result.append(dict(event))
            else:
                result.append(dict(payload))
        return result

    def record_attempt(
        self,
        run_id: str,
        kind: str,
        session_id: str,
        capability: str,
        reasoning_effort: str,
        context: Mapping[str, object],
        outcome: str,
        receipt: Mapping[str, object] | None = None,
        *,
        holder: str,
        lease_id: str,
        idempotency_key: str | None = None,
    ) -> int:
        if kind not in {*REPAIR_ATTEMPT_LIMITS, "review", "verification"}:
            raise ValueError("invalid verification attempt kind")
        snapshot = self._snapshot(run_id)
        lease = self._assert_lease(snapshot, holder, lease_id)
        run = _run_from_snapshot(snapshot)
        attempts = self.attempts(run_id)
        if idempotency_key:
            replay_attempt_id = "vattempt-" + _digest(
                run_id, idempotency_key
            )[:16]
            replay = next(
                (
                    row
                    for row in attempts
                    if row.get("attempt_id") == replay_attempt_id
                ),
                None,
            )
            if replay is not None:
                expected_receipt = dict(receipt) if receipt is not None else None
                if (
                    replay.get("kind") != kind
                    or replay.get("session_id") != session_id
                    or replay.get("capability") != capability
                    or replay.get("reasoning_effort") != reasoning_effort
                    or replay.get("outcome") != outcome
                    or replay.get("receipt") != expected_receipt
                ):
                    raise ValueError("verification attempt replay conflicts")
                ordinal = replay.get("ordinal")
                if not isinstance(ordinal, int) or isinstance(ordinal, bool):
                    raise ValueError(
                        "verification attempt replay ordinal is malformed"
                    )
                return ordinal
        ordinal, finding_id, failure_domain, mechanism_id = _attempt_plan(
            attempts,
            kind=kind,
            outcome=outcome,
            receipt=receipt,
            policy=run.repair_budget_policy,
        )
        identity = idempotency_key or _digest(
            run_id, kind, session_id, ordinal, receipt, _now()
        )
        attempt_id = "vattempt-" + _digest(run_id, identity)[:16]
        document = {
            "attempt_id": attempt_id,
            "kind": kind,
            "ordinal": ordinal,
            "session_id": session_id,
            "capability": capability,
            "reasoning_effort": reasoning_effort,
            "context_hash": hashlib.sha256(
                _canonical(dict(context)).encode()
            ).hexdigest(),
            "outcome": outcome,
            "finding_id": finding_id,
            "failure_domain": failure_domain,
            "mechanism_id": mechanism_id,
            "receipt": dict(receipt) if receipt is not None else None,
        }
        self.client.commit_attempt(
            envelope=self.envelope,
            task_id=run_id,
            attempt_id=attempt_id,
            state=kind,
            payload=document,
            idempotency_key=f"verification-attempt:{run_id}:{identity}",
            lease=lease,
            expected_task_version=_required_int(
                snapshot.get("version"), "task version"
            ),
        )
        return ordinal

    def record_attempt_batch(
        self,
        run_id: str,
        batch_id: str,
        batch_size: int,
        expected_head_sha: str,
        planner: Callable[
            [builtins.list[dict[str, object]], Callable[[int], str]],
            Sequence[Mapping[str, object]],
        ],
        *,
        holder: str,
        lease_id: str,
    ) -> int:
        snapshot = self._snapshot(run_id)
        lease = self._assert_lease(snapshot, holder, lease_id)
        run = _run_from_snapshot(snapshot)
        if run.current_head_sha != expected_head_sha:
            raise ValueError("verification event batch head changed")
        prior = self.attempts(run_id)
        for row in prior:
            prior_receipt = row.get("receipt")
            if (
                isinstance(prior_receipt, Mapping)
                and prior_receipt.get("event_batch_id") == batch_id
            ):
                return 0

        def attempt_id(index: int) -> str:
            return "vattempt-" + _digest(run_id, batch_id, index)[:16]

        planned = [dict(item) for item in planner(prior, attempt_id)]
        if len(planned) != batch_size:
            raise ValueError("verification event batch plan size mismatch")
        working: builtins.list[dict[str, object]] = builtins.list(prior)
        for index, item in enumerate(planned):
            receipt = item.get("receipt")
            if not isinstance(receipt, Mapping):
                raise ValueError("verification event batch receipt is malformed")
            ordinal, finding_id, failure_domain, mechanism_id = _attempt_plan(
                working,
                kind=str(item["kind"]),
                outcome=str(item["outcome"]),
                receipt=receipt,
                policy=run.repair_budget_policy,
            )
            if item.get("ordinal") != ordinal:
                raise ValueError("verification event batch ordinal is malformed")
            item.update(
                {
                    "finding_id": finding_id,
                    "failure_domain": failure_domain,
                    "mechanism_id": mechanism_id,
                    "receipt": {
                        **dict(receipt),
                        "event_batch_id": batch_id,
                        "event_batch_index": index,
                        "event_batch_size": batch_size,
                    },
                }
            )
            working.append(item)
        self.client.commit_attempt(
            envelope=self.envelope,
            task_id=run_id,
            attempt_id="vbatch-" + _digest(run_id, batch_id)[:16],
            state="event_batch",
            payload={"batch_events": planned},
            idempotency_key=f"verification-attempt-batch:{run_id}:{batch_id}",
            lease=lease,
            expected_task_version=_required_int(
                snapshot.get("version"), "task version"
            ),
        )
        return len(planned)

    def repair_budget_projection(self, run_id: str) -> dict[str, object]:
        run = self.get(run_id)
        if run is None:
            raise ValueError("verification run not found")
        attempts = self.attempts(run_id)
        if run.repair_budget_policy == REPAIR_BUDGET_POLICY_LEGACY:
            keys = [("legacy_global", "legacy-global")]
        elif run.repair_budget_policy == REPAIR_BUDGET_POLICY_MECHANISM:
            last_seen: dict[tuple[str, str], int] = {}
            for index, row in enumerate(attempts):
                if (
                    row.get("kind") in REPAIR_ATTEMPT_LIMITS
                    and isinstance(row.get("failure_domain"), str)
                    and isinstance(row.get("mechanism_id"), str)
                ):
                    last_seen[
                        (str(row["failure_domain"]), str(row["mechanism_id"]))
                    ] = index
            keys = sorted(last_seen, key=lambda key: (-last_seen[key], key))
        else:
            raise ValueError("invalid verification repair budget policy")
        mechanisms: builtins.list[dict[str, object]] = []
        for domain, mechanism in keys[:32]:
            standard = sum(
                row.get("kind") == "standard_repair"
                and row.get("failure_domain") == domain
                and row.get("mechanism_id") == mechanism
                for row in attempts
            )
            escalated = sum(
                row.get("kind") == "escalated_repair"
                and row.get("failure_domain") == domain
                and row.get("mechanism_id") == mechanism
                for row in attempts
            )
            mechanisms.append(
                {
                    "failure_domain": domain,
                    "mechanism_id": _projected_mechanism_id(mechanism),
                    "standard_used": standard,
                    "standard_remaining": max(0, 2 - standard),
                    "escalated_used": escalated,
                    "escalated_remaining": max(0, 2 - escalated),
                }
            )
        return {
            "policy_version": run.repair_budget_policy,
            "mechanism_count": len(keys),
            "truncated": len(keys) > 32,
            "omitted_count": max(0, len(keys) - 32),
            "mechanisms": mechanisms,
        }

    @staticmethod
    def _required_clean_review_rounds(
        run: VerificationRun,
        attempts: Sequence[Mapping[str, object]],
    ) -> int:
        # Risk and low-convergence evidence select capability and the separate
        # mechanism-convergence gate; they no longer increase the number of
        # consecutive clean final reviews. The latest verification/repair
        # anchor still invalidates all older reviews in
        # `_selected_clean_review_rounds` below.
        del attempts
        return _request_final_review_rounds(run.request)

    def closure_ready(self, run_id: str) -> bool:
        run = self.get(run_id)
        if run is None:
            return False
        attempts = self.attempts(run_id)
        repairs = [
            row
            for row in attempts
            if row.get("kind") in {"standard_repair", "escalated_repair"}
        ]
        verifications = [
            row for row in attempts if row.get("kind") == "verification"
        ]
        if not repairs and not verifications:
            return False
        anchor = (repairs[-1] if repairs else verifications[-1]).get("attempt_id")
        try:
            self._selected_clean_review_rounds(
                run,
                attempts,
                anchor_id=anchor,
            )
        except ValueError:
            return False
        return True

    def _selected_clean_review_rounds(
        self,
        run: VerificationRun,
        attempts: Sequence[Mapping[str, object]],
        *,
        anchor_id: object,
    ) -> builtins.list[Mapping[str, object]]:
        """Return the final consecutive clean authority for one anchor.

        A blocking review remains authoritative until a repair creates a new
        anchor. Never recover merge authority by filtering that blocker out
        and reusing older clean rows.
        """
        required = self._required_clean_review_rounds(run, attempts)
        reviews: builtins.list[Mapping[str, object]] = []
        for row in attempts:
            review_receipt = row.get("receipt")
            if (
                row.get("kind") == "review"
                and isinstance(review_receipt, Mapping)
                and review_receipt.get("reviewed_attempt_id") == anchor_id
            ):
                reviews.append(row)
        selected = reviews[-required:]
        if (
            len(selected) != required
            or any(row.get("outcome") != "clean" for row in reviews)
            or any(
                not isinstance(row.get("attempt_id"), str)
                or not isinstance(row.get("session_id"), str)
                or not row.get("session_id")
                for row in selected
            )
            or len({row["session_id"] for row in selected}) != required
        ):
            raise ValueError(
                "merge readiness lacks final consecutive clean review rounds"
            )
        for row in selected:
            receipt = row.get("receipt")
            if (
                not isinstance(receipt, Mapping)
                or receipt.get("head_sha") != run.current_head_sha
            ):
                raise ValueError(
                    "merge readiness lacks final consecutive clean review rounds"
                )
        return selected

    def _merge_ready_authority(
        self, run: VerificationRun
    ) -> dict[str, object]:
        attempts = self.attempts(run.run_id)
        repairs = [
            row
            for row in attempts
            if row.get("kind") in {"standard_repair", "escalated_repair"}
        ]
        verifications = [
            row for row in attempts if row.get("kind") == "verification"
        ]
        if not repairs and not verifications:
            raise ValueError("merge readiness has no verification anchor")
        anchor = repairs[-1] if repairs else verifications[-1]
        anchor_id = anchor.get("attempt_id")
        required = self._required_clean_review_rounds(run, attempts)
        selected = self._selected_clean_review_rounds(
            run,
            attempts,
            anchor_id=anchor_id,
        )
        return {
            "governing_issue": run.request.get("linked_issue"),
            "closing_issues": list(run.closing_authority),
            "supporting_issues": list(run.supporting_authority),
            "verification_anchor_attempt_id": anchor_id,
            "review_attempt_ids": [row["attempt_id"] for row in selected],
            "final_review_rounds": required,
            "repair_budget": self.repair_budget_projection(run.run_id),
        }

    def mark_merge_ready(
        self,
        run_id: str,
        receipt: Mapping[str, object],
        *,
        holder: str,
        lease_id: str,
    ) -> VerificationRun:
        """Persist exact review-only authority before the host merge effect."""
        snapshot = self._snapshot(run_id)
        run = _run_from_snapshot(snapshot)
        if (
            receipt.get("verdict") != "verified"
            or receipt.get("head_sha") != run.current_head_sha
            or not self.closure_ready(run_id)
        ):
            raise ValueError(
                "host merge readiness requires the fresh verified review gate"
            )
        lease = self._assert_lease(snapshot, holder, lease_id)
        document = dict(_snapshot_payload(snapshot))
        document["merge_ready_receipt"] = {
            "contract": "builderops_merge_ready.v1",
            "run_id": run_id,
            "repository": self.repository,
            "pr_number": run.pr_number,
            "head_sha": run.current_head_sha,
            **self._merge_ready_authority(run),
            "coordinator_receipt": dict(receipt),
        }
        self.client.transition_task(
            envelope=self.envelope,
            task_id=run_id,
            to_state="claimed",
            idempotency_key=(
                f"verification-merge-ready:{run_id}:"
                f"{_digest(document['merge_ready_receipt'])[:20]}"
            ),
            request=document,
            lease=lease,
            expected_states=("claimed",),
            expected_version=_required_int(
                snapshot.get("version"), "task version"
            ),
        )
        ready = self.get(run_id)
        if ready is None:
            raise ValueError("host merge readiness was not durably readable")
        return ready

    def merge_ready_receipt(
        self, run_id: str
    ) -> Mapping[str, object] | None:
        snapshot = self._snapshot(run_id)
        return self._merge_ready_receipt_from_snapshot(run_id, snapshot)

    def _merge_ready_receipt_from_snapshot(
        self,
        run_id: str,
        snapshot: Mapping[str, object],
    ) -> Mapping[str, object] | None:
        run = _run_from_snapshot(snapshot)
        marker = _snapshot_payload(snapshot).get("merge_ready_receipt")
        if not isinstance(marker, Mapping):
            return None
        coordinator = marker.get("coordinator_receipt")
        expected = self._merge_ready_authority(run)
        observed = {
            key: marker.get(key)
            for key in expected
        }
        if (
            marker.get("contract") != "builderops_merge_ready.v1"
            or marker.get("run_id") != run_id
            or marker.get("repository") != self.repository
            or marker.get("pr_number") != run.pr_number
            or marker.get("head_sha") != run.current_head_sha
            or observed != expected
            or not isinstance(coordinator, Mapping)
            or coordinator.get("verdict") != "verified"
            or coordinator.get("head_sha") != run.current_head_sha
        ):
            raise ValueError("BuilderOps merge-ready receipt is malformed or stale")
        return dict(marker)

    def pending_effect_binding(
        self, run_id: str
    ) -> Mapping[str, object] | None:
        """Read the task-bound effect identity and current outbox state."""
        if self.effect_outbox is None:
            return None
        snapshot = self._snapshot(run_id)
        pending = _snapshot_payload(snapshot).get("pending_privileged_effect")
        if not isinstance(pending, Mapping):
            return None
        operation_key = pending.get("operation_key")
        if (
            not isinstance(operation_key, str)
            or pending.get("task_id") != run_id
            or not isinstance(pending.get("effect_type"), str)
        ):
            raise ValueError("pending verification effect binding is malformed")
        outbox = self.effect_outbox.status(operation_key)
        return {
            **dict(pending),
            "outbox_intent": {
                key: outbox.get(key)
                for key in (
                    "repository",
                    "operation_key",
                    "task_id",
                    "effect_type",
                    "payload",
                )
            },
            "outbox_status": outbox.get("status"),
            "reconciliation_evidence": outbox.get(
                "reconciliation_evidence"
            ),
            "reconciliation_receipt_sequence": outbox.get(
                "reconciliation_receipt_sequence"
            ),
        }

    def exception(
        self,
        run_id: str,
        failure_class: str,
        packet: Mapping[str, object],
        *,
        holder: str,
        lease_id: str,
    ) -> str:
        exception_id = "vexception-" + _digest(
            run_id, failure_class, self._snapshot(run_id).get("version")
        )[:16]

        snapshot = self._snapshot(run_id)
        payload = snapshot.get("payload")
        if not isinstance(payload, Mapping):
            raise ValueError("BuilderOps verification task payload is malformed")
        stored_exceptions = payload.get("exceptions", [])
        if not isinstance(stored_exceptions, builtins.list):
            raise ValueError("BuilderOps verification exceptions are malformed")
        exceptions: builtins.list[object] = builtins.list(stored_exceptions)
        exceptions = [
            item
            for item in exceptions
            if not (
                isinstance(item, Mapping)
                and item.get("failure_class") == failure_class
                and item.get("head_sha") == _run_from_snapshot(snapshot).current_head_sha
            )
        ]
        exceptions.append(
            {
                "exception_id": exception_id,
                "failure_class": failure_class,
                "head_sha": _run_from_snapshot(snapshot).current_head_sha,
                "packet": dict(packet),
            }
        )
        lease = self._assert_lease(snapshot, holder, lease_id)
        next_payload = dict(payload)
        next_payload["exceptions"] = exceptions
        self.client.transition_task(
            envelope=self.envelope,
            task_id=run_id,
            to_state="claimed",
            idempotency_key=f"verification-exception:{exception_id}",
            request=next_payload,
            lease=lease,
            expected_states=("claimed",),
            expected_version=_required_int(
                snapshot.get("version"), "task version"
            ),
        )
        return exception_id

    def commit_effect_intent(
        self,
        run_id: str,
        *,
        effect_type: str,
        payload: Mapping[str, object],
        holder: str,
        lease_id: str,
        idempotency_key: str,
        task_metadata: Mapping[str, object] | None = None,
        expected_task_version: int | None = None,
    ) -> str:
        """Commit the fenced eligibility receipt before a privileged effect."""
        snapshot = self._snapshot(run_id)
        lease = self._assert_lease(snapshot, holder, lease_id)
        request_document = dict(_snapshot_payload(snapshot))
        if task_metadata is not None:
            request_document.update(task_metadata)
        response = self.client.transition_task(
            envelope=self.envelope,
            task_id=run_id,
            to_state="claimed",
            idempotency_key=f"verification-effect:{idempotency_key}",
            request=request_document,
            outbox={"effect_type": effect_type, "payload": dict(payload)},
            lease=lease,
            expected_states=("claimed",),
            expected_version=(
                expected_task_version
                if expected_task_version is not None
                else _required_int(
                    snapshot.get("version"), "task version"
                )
            ),
        )
        result = response.get("result")
        operation_key = result.get("operation_key") if isinstance(result, Mapping) else None
        if not isinstance(operation_key, str) or not operation_key:
            raise ValueError("BuilderOps effect intent returned no operation key")
        return operation_key

    def begin_effect(
        self,
        run_id: str,
        *,
        effect_type: str,
        payload: Mapping[str, object],
        holder: str,
        lease_id: str,
        idempotency_key: str,
        merge_ready_receipt: Mapping[str, object] | None = None,
    ) -> str:
        if self.effect_outbox is None:
            raise ValueError(
                "privileged verification effect requires a configured outbox executor"
            )
        snapshot = self._snapshot(run_id)
        task_document = _snapshot_payload(snapshot)
        effect_seals_attempts = effect_type in {
            "github.merge",
            "github.merge.dry_run",
        }
        merge_ready_marker: Mapping[str, object] | None = None
        expected_task_version: int | None = None
        if effect_seals_attempts:
            merge_ready_marker = self._merge_ready_receipt_from_snapshot(
                run_id,
                snapshot,
            )
            if (
                not isinstance(merge_ready_marker, Mapping)
                or not isinstance(merge_ready_receipt, Mapping)
                or dict(merge_ready_marker) != dict(merge_ready_receipt)
            ):
                raise ValueError(
                    "merge effect requires the exact current review frontier"
                )
            expected_task_version = _required_int(
                snapshot.get("version"), "task version"
            )
        elif merge_ready_receipt is not None:
            raise ValueError(
                "merge-ready authority is valid only for a merge effect"
            )
        effect_payload = dict(payload)
        review_authority_digest: str | None = None
        if merge_ready_marker is not None:
            review_authority_digest = _authority_digest(
                merge_ready_marker
            )
            effect_payload["review_authority_sha256"] = review_authority_digest
        pending = task_document.get("pending_privileged_effect")
        operation_key: str
        existing: Mapping[str, object]
        if isinstance(pending, Mapping):
            pending_key = pending.get("operation_key")
            pending_type = pending.get("effect_type")
            pending_task = pending.get("task_id")
            pending_head = pending.get("head_sha")
            pending_payload = pending.get("payload")
            if (
                not isinstance(pending_key, str)
                or pending_task != run_id
            ):
                raise ValueError(
                    "pending verification effect binding is malformed or conflicting"
                )
            existing = self.effect_outbox.status(pending_key)
            existing_payload = existing.get("payload")
            if (
                existing.get("repository") != self.repository
                or existing.get("operation_key") != pending_key
                or existing.get("task_id") != run_id
                or existing.get("effect_type") != pending_type
                or not isinstance(existing_payload, Mapping)
                or not isinstance(pending_payload, Mapping)
                or dict(existing_payload) != dict(pending_payload)
            ):
                raise ValueError(
                    "pending verification effect conflicts with durable outbox intent"
                )
            if existing.get("status") in {"claimed", "unknown"}:
                raise ValueError(
                    "verification effect requires reconciliation before retry"
                )
            if existing.get("status") == "pending":
                if (
                    pending_type != effect_type
                    or pending_head != effect_payload.get("head_sha")
                    or not isinstance(pending_payload, Mapping)
                    or dict(pending_payload) != effect_payload
                ):
                    raise ValueError(
                        "pending verification effect binding is malformed or conflicting"
                    )
                if effect_seals_attempts:
                    attempt_write_seal = task_document.get(
                        "attempt_write_seal"
                    )
                    if (
                        not isinstance(attempt_write_seal, Mapping)
                        or attempt_write_seal.get("contract")
                        != "builderops_attempt_write_seal.v1"
                        or attempt_write_seal.get("operation_key")
                        != pending_key
                        or attempt_write_seal.get("effect_type")
                        != effect_type
                        or attempt_write_seal.get(
                            "review_authority_sha256"
                        )
                        != review_authority_digest
                    ):
                        raise ValueError(
                            "pending merge effect lacks its review-authority "
                            "seal"
                        )
                operation_key = pending_key
            elif existing.get("status") in {"succeeded", "dead_letter"}:
                pending = None
            else:
                raise ValueError(
                    "pending verification effect has no durable outbox authority"
                )
        if not isinstance(pending, Mapping):
            transition_key = f"verification-effect:{idempotency_key}"
            expected_operation_key = _outbox_operation_key(
                self.repository, transition_key, effect_type
            )
            existing = self.effect_outbox.status(expected_operation_key)
            if existing.get("status") != "missing":
                raise ValueError(
                    "new verification effect operation already exists without "
                    "a task binding"
                )
            operation_key = self.commit_effect_intent(
                run_id,
                effect_type=effect_type,
                payload=effect_payload,
                holder=holder,
                lease_id=lease_id,
                idempotency_key=idempotency_key,
                task_metadata={
                    "pending_privileged_effect": {
                        "operation_key": expected_operation_key,
                        "effect_type": effect_type,
                        "task_id": run_id,
                        "head_sha": effect_payload.get("head_sha"),
                        "payload": effect_payload,
                    },
                    **(
                        {
                            "attempt_write_seal": {
                                "contract": (
                                    "builderops_attempt_write_seal.v1"
                                ),
                                "operation_key": expected_operation_key,
                                "effect_type": effect_type,
                                "review_authority_sha256": (
                                    review_authority_digest
                                ),
                            }
                        }
                        if merge_ready_marker is not None
                        else {}
                    ),
                },
                expected_task_version=expected_task_version,
            )
            if operation_key != expected_operation_key:
                raise ValueError("BuilderOps effect operation identity is inconsistent")
        claim = self.effect_outbox.claim(operation_key)
        self._validate_effect_claim(
            claim,
            operation_key=operation_key,
            run_id=run_id,
            effect_type=effect_type,
            require_eligible=True,
            expected_payload=effect_payload,
        )
        self._effect_claims[operation_key] = claim
        return operation_key

    def _validate_effect_claim(
        self,
        claim: Mapping[str, object],
        *,
        operation_key: str,
        run_id: str,
        effect_type: str,
        require_eligible: bool,
        expected_payload: Mapping[str, object] | None = None,
    ) -> None:
        expires_at = claim.get("expires_at")
        fencing_token = claim.get("fencing_token")
        try:
            expires = datetime.fromisoformat(
                str(expires_at).replace("Z", "+00:00")
            )
        except ValueError as exc:
            raise ValueError(
                "verification outbox claim expiry is malformed"
            ) from exc
        claim_payload = claim.get("payload")
        payload_matches = (
            expected_payload is None
            or (
                isinstance(claim_payload, Mapping)
                and dict(claim_payload) == dict(expected_payload)
            )
        )
        if (
            claim.get("repository") != self.repository
            or claim.get("operation_key") != operation_key
            or claim.get("effect_type") != effect_type
            or claim.get("task_id") != run_id
            or not payload_matches
            or (
                require_eligible
                and claim.get("effect_eligible") is not True
            )
            or not isinstance(fencing_token, int)
            or isinstance(fencing_token, bool)
            or fencing_token < 1
            or expires.tzinfo is None
            or (
                require_eligible
                and expires <= datetime.now(timezone.utc)
            )
        ):
            raise ValueError(
                "verification outbox claim is not current fenced effect authority"
            )

    def finish_effect(
        self,
        operation_key: str,
        *,
        observed_applied: bool,
        terminal_unknown: bool = False,
        evidence: Mapping[str, object],
    ) -> None:
        if self.effect_outbox is None:
            raise ValueError("verification effect outbox is unavailable")
        try:
            claim = self._effect_claims[operation_key]
        except KeyError as exc:
            raise ValueError("verification effect claim is unavailable") from exc
        if operation_key not in self._unknown_effects:
            try:
                self.effect_outbox.mark_unknown(
                    claim, detail="effect returned; authoritative readback committed"
                )
            except Exception:
                status = self.effect_outbox.status(operation_key)
                if status.get("status") == "unknown":
                    self._unknown_effects.add(operation_key)
                elif status.get("status") in {"succeeded", "dead_letter"}:
                    self._effect_claims.pop(operation_key, None)
                    return
                else:
                    raise
            else:
                self._unknown_effects.add(operation_key)
        try:
            self.effect_outbox.reconcile(
                claim,
                observed_applied=observed_applied,
                terminal_unknown=terminal_unknown,
                evidence=evidence,
            )
        except Exception:
            status = self.effect_outbox.status(operation_key)
            if status.get("status") not in {"succeeded", "dead_letter"}:
                raise
        self._unknown_effects.discard(operation_key)
        self._effect_claims.pop(operation_key, None)

    def abandon_effect(self, operation_key: str, *, detail: str) -> None:
        if self.effect_outbox is None:
            return
        claim = self._effect_claims.pop(operation_key, None)
        if claim is not None:
            if operation_key not in self._unknown_effects:
                self.effect_outbox.mark_unknown(claim, detail=detail)
            self._unknown_effects.add(operation_key)

    def recover_effect(
        self,
        operation_key: str,
        *,
        run_id: str,
        effect_type: str,
        expected_payload: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        if self.effect_outbox is None:
            raise ValueError("verification effect outbox is unavailable")
        claim = self.effect_outbox.recover(operation_key)
        self._validate_effect_claim(
            claim,
            operation_key=operation_key,
            run_id=run_id,
            effect_type=effect_type,
            require_eligible=False,
            expected_payload=expected_payload,
        )
        self._effect_claims[operation_key] = claim
        self._unknown_effects.add(operation_key)
        return claim

    def effect_claim(self, operation_key: str) -> Mapping[str, object]:
        try:
            return dict(self._effect_claims[operation_key])
        except KeyError as exc:
            raise ValueError(
                "verification effect claim is unavailable"
            ) from exc


__all__ = [
    "BuilderOpsVerificationLedger",
    "VerificationEffectOutbox",
    "project_verification_run",
]
