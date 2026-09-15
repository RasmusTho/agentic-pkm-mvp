"""Authenticated destination adapter for the first Issue-delivery operation.

FCA-ID-A owns admission.  This module owns only the destination side of the
same operation: it records a reservation, one pre-launch attempt, and the
separate observed Codex entry through the existing BuilderOps receipt owner.
It never creates a worker, queue, store, or fallback route of its own.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Protocol

from app.builderops.control_plane.client import (
    BuilderOpsControlPlaneClient,
    ClientConfig,
    ControlPlaneClientError,
    ControlPlaneNotFoundError,
)
from app.builderops.control_plane.issue_delivery import (
    CONTRACT_VERSION,
    OPERATION_TYPE,
    PERMITTED_EFFECTS,
    canonical_hash,
    manifest_hash,
)
from app.builderops.control_plane.models import canonical_repository
from app.builderops.epic_dispatch import (
    CodexIssueSessionLauncher,
    IssueSessionLauncher,
)


class IssueDeliveryOperationError(RuntimeError):
    """A destination operation is unavailable or must remain unresolved."""

    def __init__(self, message: str, *, session_id: str | None = None) -> None:
        self.session_id = session_id
        super().__init__(message)


class IssueDeliveryOperationRefused(IssueDeliveryOperationError):
    """A stale, changed, or unsupported operation cannot cross an effect gate."""


class _OperationClient(Protocol):
    def issue_delivery_authority(
        self, *, manifest: Mapping[str, Any], purpose: str
    ) -> dict[str, Any]: ...

    def issue_delivery_operation_record(self, **kwargs: Any) -> dict[str, Any]: ...

    def issue_delivery_operation_record_read(
        self, *, repository: str, record_id: str
    ) -> dict[str, Any]: ...

    def get_receipt(self, **kwargs: Any) -> dict[str, Any]: ...


_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@-]{0,255}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_RECORD_KINDS = {
    "reservation": "reserved",
    "attempt": "attempted",
    "entry": "active",
    "terminal": "terminal",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
            "utf-8"
        )
    ).hexdigest()


def _text(value: Any, name: str, *, limit: int = 512) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise IssueDeliveryOperationRefused(f"{name} is required")
    return value.strip()


def _record_hash(record: Mapping[str, Any]) -> str:
    payload = record.get("payload")
    if not isinstance(payload, Mapping):
        raise IssueDeliveryOperationRefused("destination receipt payload is malformed")
    declared = payload.get("receipt_hash")
    if not isinstance(declared, str) or not _SHA256.fullmatch(declared):
        raise IssueDeliveryOperationRefused("destination receipt hash is missing")
    without_hash = {key: value for key, value in payload.items() if key != "receipt_hash"}
    if _json_hash(without_hash) != declared:
        raise IssueDeliveryOperationRefused("destination receipt hash is corrupt")
    return declared


class IssueDeliveryOperationAdapter:
    """Run exactly one approved Issue through the existing Codex launcher.

    The adapter is intentionally a launcher-shaped object, so
    ``dispatch_issue_sessions`` can use it without growing another execution
    engine.  ``launcher`` remains the existing ``CodexIssueSessionLauncher``;
    only the destination receipts and current effect gates are added around
    it.
    """

    def __init__(
        self,
        approval: Mapping[str, Any],
        *,
        client: _OperationClient,
        launcher: IssueSessionLauncher | None = None,
        repo_root: Path | None = None,
        now: Callable[[], str] = _utc_now,
    ) -> None:
        self.approval = self._validate_approval(approval)
        self.client = client
        self.launcher = launcher or CodexIssueSessionLauncher(
            repo_root=(repo_root or Path.cwd())
        )
        self.repo_root = (repo_root or getattr(self.launcher, "repo_root", Path.cwd())).resolve()
        destination = self.approval["destination"]
        if self.repo_root != Path(destination["checkout"]).resolve():
            raise IssueDeliveryOperationRefused(
                "launcher repository root differs from approved destination checkout"
            )
        context = self.approval["context"]
        dispatch_plan = context["dispatch_plan"]
        context_pack = dispatch_plan["context_packs"][0]
        worktree_plan = context_pack["branch_worktree_plan"]
        if (
            dispatch_plan["run_id"] != destination["run_id"]
            or worktree_plan["branch"] != destination["branch"]
            or Path(worktree_plan["worktree"]).resolve()
            != Path(destination["worktree"]).resolve()
        ):
            raise IssueDeliveryOperationRefused(
                "approved context and destination are not bound to one run"
            )
        self.now = now
        self.repository = canonical_repository(self.approval["repository"])
        self.approval_id = self.approval["approval_id"]
        self.operation_key = self.approval["operation_key"]
        self.approval_manifest_hash = self.approval["approval_manifest_hash"]
        self.destination_identity = destination["identity"]
        self.run_id = destination["run_id"]

    @classmethod
    def from_env(
        cls,
        approval: Mapping[str, Any],
        *,
        launcher: IssueSessionLauncher | None = None,
        repo_root: Path | None = None,
    ) -> "IssueDeliveryOperationAdapter":
        return cls(
            approval,
            client=BuilderOpsControlPlaneClient(ClientConfig.from_env(), max_retries=0),
            launcher=launcher,
            repo_root=repo_root,
        )

    @staticmethod
    def _validate_approval(approval: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(approval, Mapping):
            raise IssueDeliveryOperationRefused("committed Issue-delivery approval is required")
        value = dict(approval)
        if value.get("contract_version") != CONTRACT_VERSION or value.get("operation_type") != OPERATION_TYPE:
            raise IssueDeliveryOperationRefused("unsupported Issue-delivery approval")
        for name in ("repository", "approval_id", "operation_key", "approval_manifest_hash"):
            _text(value.get(name), name)
        if not _ID.fullmatch(str(value["approval_id"])) or not _ID.fullmatch(str(value["operation_key"])):
            raise IssueDeliveryOperationRefused("Issue-delivery identity is malformed")
        try:
            canonical_repository(str(value["repository"]))
        except (TypeError, ValueError) as exc:
            raise IssueDeliveryOperationRefused(
                "Issue-delivery repository identity is malformed"
            ) from exc
        if not _SHA256.fullmatch(str(value["approval_manifest_hash"])):
            raise IssueDeliveryOperationRefused("Issue-delivery approval hash is malformed")
        if manifest_hash(value) != value["approval_manifest_hash"]:
            raise IssueDeliveryOperationRefused("Issue-delivery approval hash is corrupt")
        destination = value.get("destination")
        if not isinstance(destination, Mapping):
            raise IssueDeliveryOperationRefused("Issue-delivery destination is missing")
        for name in ("identity", "run_id", "checkout", "worktree", "branch", "base_ref"):
            _text(destination.get(name), f"destination {name}", limit=1024)
        if destination.get("branch", "").removeprefix("refs/heads/") == destination.get("base_ref", "").removeprefix("refs/heads/"):
            raise IssueDeliveryOperationRefused("destination branch must be isolated from base ref")
        context = value.get("context")
        if not isinstance(context, Mapping):
            raise IssueDeliveryOperationRefused("Issue-delivery context is missing")
        dispatch_plan = context.get("dispatch_plan")
        packs = dispatch_plan.get("context_packs") if isinstance(dispatch_plan, Mapping) else None
        if (
            not isinstance(dispatch_plan, Mapping)
            or not isinstance(dispatch_plan.get("run_id"), str)
            or not isinstance(packs, list)
            or len(packs) != 1
            or not isinstance(packs[0], Mapping)
            or not isinstance(packs[0].get("branch_worktree_plan"), Mapping)
        ):
            raise IssueDeliveryOperationRefused(
                "approval does not bind one complete context pack"
            )
        worktree_plan = packs[0]["branch_worktree_plan"]
        for name in ("branch", "worktree"):
            _text(worktree_plan.get(name), f"context worktree plan {name}", limit=1024)
        if set(value.get("permitted_effects", ())) != set(PERMITTED_EFFECTS):
            raise IssueDeliveryOperationRefused("Issue-delivery effect grant is incomplete")
        return value

    def _authority(self, effect: str) -> dict[str, Any]:
        if effect not in PERMITTED_EFFECTS:
            raise IssueDeliveryOperationRefused(
                f"effect is not permitted by the approved Issue operation: {effect}"
            )
        try:
            reply = self.client.issue_delivery_authority(
                manifest=self.approval, purpose="execute"
            )
        except ControlPlaneClientError as exc:
            raise IssueDeliveryOperationRefused(
                "current Issue-delivery authority is unavailable"
            ) from exc
        if (
            reply.get("approval") != self.approval
            or reply.get("purpose") != "execute"
            or reply.get("operation_key") != self.operation_key
            or type(reply.get("authority_epoch")) is not int
            or not isinstance(reply.get("observed_at"), str)
        ):
            raise IssueDeliveryOperationRefused(
                "current Issue-delivery authority does not match approval"
            )
        return {
            "effect": effect,
            "authority_epoch": reply["authority_epoch"],
            "observed_at": reply["observed_at"],
            "approval_manifest_hash": self.approval_manifest_hash,
        }

    def authorize_effect(self, effect: str) -> dict[str, Any]:
        """Recheck fresh permission before a real repository effect."""

        return self._authority(effect)

    # Alias used by effect owners that call this a gate rather than an
    # authorization check.
    effect_gate = authorize_effect
    recheck_authority = authorize_effect

    def bind_dispatch_plan(
        self,
        plan: Mapping[str, Any],
        *,
        expected_plan_hash: str | None = None,
    ) -> None:
        """Require dispatch to consume the plan frozen by FCA-ID-A.

        The launcher receives only a context pack, so checking that pack at
        launch time is not sufficient to prevent a caller from replacing the
        surrounding run or selected Issue.  Compare the complete plan before
        any reservation or attempt receipt is written.
        """

        approved_context = self.approval.get("context")
        approved_plan = (
            approved_context.get("dispatch_plan")
            if isinstance(approved_context, Mapping)
            else None
        )
        if not isinstance(approved_plan, Mapping):
            raise IssueDeliveryOperationRefused(
                "approval does not contain one frozen dispatch plan"
            )
        if canonical_hash(plan) != canonical_hash(approved_plan):
            raise IssueDeliveryOperationRefused(
                "dispatch plan differs from approved Issue-delivery plan"
            )
        approved_plan_hash = (
            approved_context.get("expected_plan_hash")
            if isinstance(approved_context, Mapping)
            else None
        )
        if (
            not isinstance(approved_plan_hash, str)
            or canonical_hash(approved_plan) != approved_plan_hash
        ):
            raise IssueDeliveryOperationRefused(
                "approved dispatch plan hash is missing or corrupt"
            )
        if expected_plan_hash is not None and expected_plan_hash != approved_plan_hash:
            raise IssueDeliveryOperationRefused(
                "dispatch plan hash differs from approved Issue-delivery plan"
            )

    def _record_id(self, kind: str) -> str:
        if kind not in _RECORD_KINDS:
            raise IssueDeliveryOperationRefused("unsupported destination receipt kind")
        return f"issue-delivery-{kind}:{self.operation_key}"

    def _read_record(self, kind: str) -> dict[str, Any] | None:
        record_id = self._record_id(kind)
        try:
            record = self.client.issue_delivery_operation_record_read(
                repository=self.repository, record_id=record_id
            )
        except ControlPlaneNotFoundError:
            return None
        except ControlPlaneClientError as exc:
            # A missing response is not a negative lookup.  Preserve
            # reconciliation-needed state so a retry cannot launch twice.
            raise IssueDeliveryOperationRefused(
                "destination receipt lookup is unavailable"
            ) from exc
        if not isinstance(record, dict):
            raise IssueDeliveryOperationRefused("destination receipt lookup is malformed")
        self._assert_record_binding(record, kind)
        return record

    def _assert_record_binding(self, record: Mapping[str, Any], kind: str) -> None:
        payload = record.get("payload")
        if (
            record.get("record_type") != "BuilderOpsReceipt"
            or record.get("state") not in {
                _RECORD_KINDS[kind],
                "launch_unknown" if kind == "terminal" else _RECORD_KINDS[kind],
            }
            or not isinstance(payload, Mapping)
            or payload.get("repository") != self.repository
            or payload.get("operation_key") != self.operation_key
            or payload.get("approval_id") != self.approval_id
            or payload.get("approval_manifest_hash") != self.approval_manifest_hash
        ):
            raise IssueDeliveryOperationRefused(
                "destination receipt is bound to a different operation"
            )
        _record_hash(record)

    def _write_record(
        self,
        kind: str,
        state: str,
        body: Mapping[str, Any],
    ) -> dict[str, Any]:
        if state != _RECORD_KINDS[kind] and not (
            kind == "terminal" and state == "launch_unknown"
        ):
            raise IssueDeliveryOperationRefused("destination receipt state is invalid")
        self._authority("repository_worktree" if kind in {"reservation", "attempt"} else "closure_reconciliation")
        payload = {
            "schema": f"builderops.issue-delivery-{kind}.v1",
            "repository": self.repository,
            "operation_type": OPERATION_TYPE,
            "operation_key": self.operation_key,
            "approval_id": self.approval_id,
            "approval_manifest_hash": self.approval_manifest_hash,
            **dict(body),
        }
        payload["receipt_hash"] = _json_hash(payload)
        try:
            self.client.issue_delivery_operation_record(
                envelope={
                    "repository": self.repository,
                    "scope": "issue-delivery-operation",
                    "stack": "builderops-control-plane",
                    "source_refs": [
                        f"issue-delivery-approval:{self.approval_id}",
                        f"operation:{self.operation_key}",
                    ],
                },
                record_id=self._record_id(kind),
                state=state,
                payload=payload,
                idempotency_key=f"issue-delivery-operation:{kind}:{self.operation_key}",
                operation_key=self.operation_key,
                approval_id=self.approval_id,
                approval_manifest_hash=self.approval_manifest_hash,
            )
        except ControlPlaneClientError as exc:
            # A concurrent writer may have committed the exact record while
            # this request was in flight.  Re-read the destination-owned
            # record before surfacing failure; an unavailable lookup remains
            # unresolved and must never be interpreted as permission to retry.
            try:
                existing = self._read_record(kind)
            except IssueDeliveryOperationError:
                existing = None
            if existing is not None:
                return existing
            raise IssueDeliveryOperationRefused(
                "destination receipt was not durably committed"
            ) from exc
        record = self._read_record(kind)
        if record is None:
            raise IssueDeliveryOperationRefused(
                "destination receipt commit has no authoritative readback"
            )
        return record

    def reserve(self) -> dict[str, Any]:
        """Reserve the proposed destination/run exactly once."""

        self._authority("repository_worktree")
        existing = self._read_record("reservation")
        if existing is not None:
            return existing
        destination = dict(self.approval["destination"])
        return self._write_record(
            "reservation",
            "reserved",
            {
                "destination": destination,
                "proposed_run": {"run_id": self.run_id},
                "reserved_at": self.now(),
            },
        )

    def record_attempt(self) -> dict[str, Any]:
        """Persist one unique attempt before crossing the launcher boundary."""

        reservation = self.reserve()
        existing = self._read_record("attempt")
        if existing is not None:
            return existing
        reservation_hash = _record_hash(reservation)
        return self._write_record(
            "attempt",
            "attempted",
            {
                "reservation_receipt_hash": reservation_hash,
                "attempt_id": f"{self.operation_key}:attempt",
                "attempted_at": self.now(),
            },
        )

    def record_entry(
        self,
        *,
        session_id: str,
        state: str = "active",
    ) -> dict[str, Any]:
        """Persist the actual observed Codex process/session independently."""

        session_id = _text(session_id, "observed session id", limit=256)
        attempt = self.record_attempt()
        existing = self._read_record("entry")
        if existing is not None:
            payload = existing["payload"]
            if payload.get("session_id") != session_id:
                raise IssueDeliveryOperationRefused(
                    "destination entry is bound to another session"
                )
            return existing
        return self._write_record(
            "entry",
            state,
            {
                "attempt_receipt_hash": _record_hash(attempt),
                "attempt_id": attempt["payload"]["attempt_id"],
                "session_id": session_id,
                "entered_at": self.now(),
            },
        )

    def record_terminal(
        self,
        *,
        session_id: str | None,
        worker_receipt: Mapping[str, Any] | None,
        state: str = "terminal",
    ) -> dict[str, Any]:
        """Record a terminal or launch-unknown observation without stop claims."""

        existing = self._read_record("terminal")
        if existing is not None:
            return existing
        entry = self._read_record("entry")
        attempt = self.record_attempt()
        return self._write_record(
            "terminal",
            state,
            {
                "attempt_receipt_hash": _record_hash(attempt),
                "entry_receipt_hash": _record_hash(entry) if entry is not None else None,
                "session_id": session_id,
                "worker_receipt": dict(worker_receipt) if worker_receipt is not None else None,
                "observed_at": self.now(),
            },
        )

    def launch(
        self,
        context_pack: Mapping[str, Any],
        *,
        execution_routing: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Reserve, attempt, observe entry, then delegate to the existing launcher."""

        if execution_routing is not None:
            raise IssueDeliveryOperationRefused("Issue-delivery adapter does not permit canary routing")
        selected = self.approval.get("context", {}).get("dispatch_plan", {}).get("context_packs", [])
        if not isinstance(selected, list) or len(selected) != 1:
            raise IssueDeliveryOperationRefused("approval does not bind one context pack")
        if canonical_hash(selected[0]) != canonical_hash(context_pack):
            raise IssueDeliveryOperationRefused("launch context differs from approved context")

        terminal = self._read_record("terminal")
        entry = self._read_record("entry")
        if terminal is not None:
            state = terminal.get("state")
            if state != "terminal":
                raise IssueDeliveryOperationError(
                    "existing launch is unresolved; replacement launch is forbidden",
                    session_id=(entry or {}).get("payload", {}).get("session_id"),
                )
            terminal_payload = terminal.get("payload", {})
            return {
                "session_id": terminal_payload.get("session_id") or (entry or {}).get("payload", {}).get("session_id"),
                "worker_receipt": terminal_payload.get("worker_receipt"),
                "operation_state": "terminal",
                "reservation_receipt_hash": _record_hash(self._read_record("reservation") or {}),
                "attempt_receipt_hash": _record_hash(self._read_record("attempt") or {}),
                "entry_receipt_hash": _record_hash(entry) if entry is not None else None,
                "stop_support": "unsupported",
            }
        if entry is not None:
            raise IssueDeliveryOperationError(
                "existing active launch requires destination reconciliation; relaunch is forbidden",
                session_id=entry.get("payload", {}).get("session_id"),
            )
        # An attempt is the point after which the launcher boundary may have
        # been crossed.  If entry/terminal observation is missing, preserve the
        # ambiguity and require reconciliation instead of treating the attempt
        # as a harmless preflight artifact and launching a second worker.
        attempt = self._read_record("attempt")
        if attempt is not None:
            raise IssueDeliveryOperationError(
                "existing launch attempt has no observed entry; replacement launch is forbidden"
            )

        self.reserve()
        self.record_attempt()
        try:
            result = self.launcher.launch(context_pack)
            if not isinstance(result, Mapping):
                raise IssueDeliveryOperationError("existing launcher returned a non-object result")
            session_id = result.get("session_id")
            if not isinstance(session_id, str) or not session_id.strip():
                self.record_terminal(session_id=None, worker_receipt=None, state="launch_unknown")
                raise IssueDeliveryOperationError("launcher returned no observed session entry")
            entry = self.record_entry(session_id=session_id)
            worker_receipt = result.get("worker_receipt")
            if isinstance(worker_receipt, Mapping):
                self.record_terminal(session_id=session_id, worker_receipt=worker_receipt)
            return {
                **dict(result),
                "operation_state": "terminal" if isinstance(worker_receipt, Mapping) else "active",
                "reservation_receipt_hash": _record_hash(self._read_record("reservation") or {}),
                "attempt_receipt_hash": _record_hash(self._read_record("attempt") or {}),
                "entry_receipt_hash": _record_hash(entry),
                "stop_support": "unsupported",
            }
        except IssueDeliveryOperationError:
            raise
        except Exception as exc:
            session_id = getattr(exc, "session_id", None)
            if not isinstance(session_id, str) or not session_id.strip():
                session_id = None
            if session_id is not None:
                try:
                    self.record_entry(session_id=session_id)
                except IssueDeliveryOperationError as entry_exc:
                    raise IssueDeliveryOperationError(
                        "launcher response was lost and entry observation is unavailable",
                        session_id=session_id,
                    ) from entry_exc
            try:
                self.record_terminal(
                    session_id=session_id,
                    worker_receipt=None,
                    state="launch_unknown",
                )
            except IssueDeliveryOperationError as terminal_exc:
                raise IssueDeliveryOperationError(
                    "launcher outcome is ambiguous; destination reconciliation is required",
                    session_id=session_id,
                ) from terminal_exc
            raise IssueDeliveryOperationError(
                "launcher outcome is ambiguous; replacement launch is forbidden",
                session_id=session_id,
            ) from exc

    def stop(self) -> dict[str, str]:
        """The selected launcher has no stop/control API."""

        return {"stop_support": "unsupported", "stop_status": "unsupported"}


__all__ = [
    "IssueDeliveryOperationAdapter",
    "IssueDeliveryOperationError",
    "IssueDeliveryOperationRefused",
]
