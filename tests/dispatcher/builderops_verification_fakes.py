from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any

from app.builderops.control_plane import (
    LeaseUnavailable,
    StaleFencingToken,
)


class FakeBuilderOpsClient:
    """In-memory transport double for the API adapter, never a store double."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self.attempt_rows: dict[str, list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._fence = 0

    def _call(self, name: str, values: dict[str, Any]) -> None:
        self.calls.append((name, values))

    def get_task(self, *, repository: str, task_id: str) -> dict[str, Any]:
        self._call("get_task", {"repository": repository, "task_id": task_id})
        if task_id not in self.tasks:
            from app.builderops.control_plane.client import ControlPlaneNotFoundError

            raise ControlPlaneNotFoundError("not found")
        return self.tasks[task_id]

    def list_tasks(
        self, *, repository: str, task_prefix: str | None = None
    ) -> list[dict[str, Any]]:
        self._call(
            "list_tasks",
            {"repository": repository, "task_prefix": task_prefix},
        )
        return [
            row
            for task_id, row in self.tasks.items()
            if task_prefix is None or task_id.startswith(task_prefix)
        ]

    def transition_task(self, **values: Any) -> dict[str, Any]:
        self._call("transition_task", values)
        task_id = values["task_id"]
        existing = self.tasks.get(task_id)
        version = 1 if existing is None else int(existing["version"]) + 1
        lease = existing.get("lease") if existing is not None else None
        self.tasks[task_id] = {
            "repository": values["envelope"]["repository"],
            "task_id": task_id,
            "state": values["to_state"],
            "payload": values["request"],
            "authority_envelope": values["envelope"],
            "version": version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "lease": lease,
        }
        operation_key = None
        if values.get("outbox"):
            operation_key = hashlib.sha256(
                json.dumps(
                    {
                        "repository": values["envelope"]["repository"],
                        "idempotency_key": values["idempotency_key"],
                        "effect_type": values["outbox"]["effect_type"],
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode()
            ).hexdigest()
        return {
            "result": {
                "task_id": task_id,
                "state": values["to_state"],
                "operation_key": operation_key,
            }
        }

    def claim_task(self, **values: Any) -> dict[str, Any]:
        self._call("claim_task", values)
        task = self.tasks[values["task_id"]]
        self._fence += 1
        lease = {
            "repository": values["envelope"]["repository"],
            "resource_id": values["task_id"],
            "holder": "verification-host",
            "fencing_token": self._fence,
            "expires_at": (
                datetime.now(timezone.utc)
                + timedelta(seconds=values["ttl_seconds"])
            ).isoformat(),
            "lease_kind": "task",
        }
        task.update(
            state="claimed",
            payload=values["request"],
            version=int(task["version"]) + 1,
            lease=lease,
        )
        return {"result": {"state": "claimed"}, "lease": lease}

    def release_task(self, **values: Any) -> dict[str, Any]:
        return self._finish_task("ready", "release_task", values)

    def complete_task(self, **values: Any) -> dict[str, Any]:
        return self._finish_task("completed", "complete_task", values)

    def _finish_task(
        self, state: str, call_name: str, values: dict[str, Any]
    ) -> dict[str, Any]:
        self._call(call_name, values)
        lease = values["lease"]
        task = self.tasks[lease["resource_id"]]
        task.update(
            state=state,
            payload=values["request"],
            version=int(task["version"]) + 1,
            lease=None,
        )
        return {"result": {"state": state}}

    def heartbeat_task(self, **values: Any) -> dict[str, Any]:
        self._call("heartbeat_task", values)
        lease = dict(values["lease"])
        lease["expires_at"] = (
            datetime.now(timezone.utc)
            + timedelta(seconds=values["ttl_seconds"])
        ).isoformat()
        self.tasks[lease["resource_id"]]["lease"] = lease
        return {"result": {"state": "claimed"}, "lease": lease}

    def commit_attempt(self, **values: Any) -> dict[str, Any]:
        self._call("commit_attempt", values)
        rows = self.attempt_rows.setdefault(values["task_id"], [])
        existing = next(
            (
                row
                for row in rows
                if row["attempt_id"] == values["attempt_id"]
            ),
            None,
        )
        if existing is None:
            rows.append(
                {
                    "repository": values["envelope"]["repository"],
                    "task_id": values["task_id"],
                    "attempt_id": values["attempt_id"],
                    "state": values["state"],
                    "payload": values["payload"],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            task = self.tasks[values["task_id"]]
            task["version"] = int(task["version"]) + 1
        return {"object_id": values["attempt_id"], "state": values["state"]}

    def list_attempts(
        self, *, repository: str, task_id: str
    ) -> list[dict[str, Any]]:
        self._call(
            "list_attempts",
            {"repository": repository, "task_id": task_id},
        )
        return list(self.attempt_rows.get(task_id, []))


class FakeVerificationOutbox:
    def __init__(self, client: FakeBuilderOpsClient) -> None:
        self.client = client
        self.calls: list[str] = []
        self.states: dict[str, str] = {}
        self.evidence: dict[str, dict[str, Any]] = {}
        self.claims: dict[str, dict[str, Any]] = {}
        self.recovered_claims: set[str] = set()

    def claim(self, operation_key: str):
        self.calls.append("claim")
        self.states[operation_key] = "claimed"
        effect_call = next(
            values
            for name, values in reversed(self.client.calls)
            if name == "transition_task" and values.get("outbox") is not None
        )
        claim = {
            "repository": effect_call["envelope"]["repository"],
            "operation_key": operation_key,
            "worker_id": "verification-host",
            "fencing_token": 1,
            "intent_lsn": "0/10",
            "claim_lsn": "0/20",
            "receipt_sequence": 2,
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(minutes=5)
            ).isoformat(),
            "effect_eligible": True,
            "task_id": effect_call["task_id"],
            "effect_type": effect_call["outbox"]["effect_type"],
            "payload": effect_call["outbox"]["payload"],
        }
        self.claims[operation_key] = claim
        return dict(claim)

    def recover(self, operation_key: str):
        self.calls.append("recover")
        claim = dict(self.claims[operation_key])
        state = self.states.get(operation_key)
        if state == "claimed" or operation_key in self.recovered_claims:
            expires = datetime.fromisoformat(
                str(claim["expires_at"]).replace("Z", "+00:00")
            )
            if expires > datetime.now(timezone.utc):
                raise LeaseUnavailable(
                    "outbox operation still has an active claim"
                )
        self.states[operation_key] = "unknown"
        claim.update(
            fencing_token=int(claim["fencing_token"]) + 1,
            receipt_sequence=int(claim["receipt_sequence"]) + 1,
            claim_lsn="0/30",
            expires_at=(
                datetime.now(timezone.utc) + timedelta(minutes=5)
            ).isoformat(),
        )
        self.claims[operation_key] = claim
        self.recovered_claims.add(operation_key)
        return dict(claim)

    def status(self, operation_key: str):
        self.calls.append("status")
        return {
            "status": self.states.get(operation_key, "missing"),
            "reconciliation_evidence": self.evidence.get(operation_key),
            "reconciliation_receipt_sequence": (
                3 if operation_key in self.evidence else None
            ),
        }

    def mark_unknown(self, claim, *, detail: str):
        self.calls.append("unknown")
        self._assert_current_claim(claim)
        self.states[claim["operation_key"]] = "unknown"

    def reconcile(
        self,
        claim,
        *,
        observed_applied: bool,
        terminal_unknown: bool = False,
        evidence,
    ):
        self.calls.append("reconcile")
        self._assert_current_claim(claim)
        status = (
            "dead_letter"
            if terminal_unknown
            else ("succeeded" if observed_applied else "pending")
        )
        self.states[claim["operation_key"]] = status
        self.evidence[claim["operation_key"]] = dict(evidence)
        return {"status": status}

    def _assert_current_claim(self, claim: dict[str, Any]) -> None:
        current = self.claims[claim["operation_key"]]
        expires = datetime.fromisoformat(
            str(claim["expires_at"]).replace("Z", "+00:00")
        )
        if (
            claim["worker_id"] != current["worker_id"]
            or claim["fencing_token"] != current["fencing_token"]
            or claim["receipt_sequence"] != current["receipt_sequence"]
            or expires <= datetime.now(timezone.utc)
        ):
            raise StaleFencingToken("outbox claim is stale")
