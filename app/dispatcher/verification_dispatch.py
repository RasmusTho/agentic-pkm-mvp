"""Durable verification-request lifecycle on the central dispatcher store."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from app.dispatcher.store import SqliteStore

CONTRACT_VERSION = "verification_dispatch_request.v1"
TERMINAL_STATES = frozenset({"completed", "failed", "needs_human", "superseded"})
ACTIVE_STATES = frozenset({"claimed", "running"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _future(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(
        timespec="microseconds"
    )


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load(value: str | None) -> Any:
    return json.loads(value) if value else None


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validate_request(request: Mapping[str, object]) -> None:
    required_strings = (
        "contract_version",
        "stage",
        "repository",
        "current_head_sha",
        "idempotency_key",
        "generated_at",
    )
    if any(not isinstance(request.get(key), str) or not request[key] for key in required_strings):
        raise ValueError("malformed verification dispatch request")
    if request["contract_version"] != CONTRACT_VERSION or request["stage"] != "verification":
        raise ValueError("unsupported verification dispatch request")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(request["repository"])):
        raise ValueError("malformed verification repository identity")
    if not _positive_int(request.get("pr_number")):
        raise ValueError("malformed verification dispatch request")
    identity = {
        "contract_version": CONTRACT_VERSION,
        "head_sha": request["current_head_sha"],
        "pr_number": request["pr_number"],
        "repository": request["repository"],
        "stage": request["stage"],
    }
    expected = hashlib.sha256(_json(identity).encode()).hexdigest()
    if request["idempotency_key"] != expected:
        raise ValueError("verification request idempotency key does not match identity")


@dataclass(frozen=True)
class VerificationRun:
    run_id: str
    idempotency_key: str
    repository: str
    pr_number: int
    head_sha: str
    stage: str
    status: str
    claimed_by: str | None
    lease_id: str | None
    lease_expires_at: str | None
    coordinator_session_id: str | None
    request: dict[str, object]
    context_pack: dict[str, object] | None
    terminal_receipt: dict[str, object] | None
    stop_reason: str | None
    retry_after: str | None


def _run(row: sqlite3.Row) -> VerificationRun:
    return VerificationRun(
        run_id=row["run_id"],
        idempotency_key=row["idempotency_key"],
        repository=row["repository"],
        pr_number=row["pr_number"],
        head_sha=row["head_sha"],
        stage=row["stage"],
        status=row["status"],
        claimed_by=row["claimed_by"],
        lease_id=row["lease_id"],
        lease_expires_at=row["lease_expires_at"],
        coordinator_session_id=row["coordinator_session_id"],
        request=_load(row["request_json"]),
        context_pack=_load(row["context_pack_json"]),
        terminal_receipt=_load(row["terminal_receipt_json"]),
        stop_reason=row["stop_reason"],
        retry_after=row["retry_after"],
    )


class VerificationDispatchLedger:
    """Atomic, idempotent lifecycle for PR/head verification chains."""

    def __init__(self, store: SqliteStore) -> None:
        self.store = store
        self.store.initialize()

    def ingest(self, request: Mapping[str, object]) -> VerificationRun:
        _validate_request(request)
        now = _now()
        run_id = f"vrun-{str(request['idempotency_key'])[:16]}"
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT OR IGNORE INTO verification_runs (
                    run_id, idempotency_key, contract_version, repository,
                    pr_number, head_sha, stage, request_json, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    run_id,
                    request["idempotency_key"],
                    request["contract_version"],
                    request["repository"],
                    request["pr_number"],
                    request["current_head_sha"],
                    request["stage"],
                    _json(dict(request)),
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM verification_runs WHERE idempotency_key = ?",
                (request["idempotency_key"],),
            ).fetchone()
            conn.commit()
        assert row is not None
        return _run(row)

    def get(self, run_id: str) -> VerificationRun | None:
        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT * FROM verification_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return _run(row) if row is not None else None

    def list(self, *, limit: int = 20, status: str | None = None) -> list[VerificationRun]:
        if limit <= 0:
            raise ValueError("verification status limit must be positive")
        where = "WHERE status = ?" if status is not None else ""
        parameters: tuple[object, ...] = (status, limit) if status is not None else (limit,)
        with self.store._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM verification_runs {where} ORDER BY updated_at DESC LIMIT ?",
                parameters,
            ).fetchall()
        return [_run(row) for row in rows]

    def claim(self, run_id: str, holder: str, ttl_seconds: int = 900) -> VerificationRun:
        if ttl_seconds <= 0 or not holder:
            raise ValueError("holder and positive ttl are required")
        now, expires = _now(), _future(ttl_seconds)
        lease_id = f"vlease-{uuid.uuid4().hex[:12]}"
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM verification_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"verification run {run_id} not found")
            expired = row["lease_expires_at"] is not None and row["lease_expires_at"] <= now
            eligible = row["status"] in {"queued", "backoff"} or (
                row["status"] in ACTIVE_STATES and expired
            )
            if not eligible:
                raise ValueError(f"verification run {run_id} is not claimable")
            result = conn.execute(
                """
                UPDATE verification_runs
                SET status='claimed', claimed_by=?, lease_id=?, lease_expires_at=?,
                    last_heartbeat_at=?, updated_at=?
                WHERE run_id=? AND status=? AND lease_id IS ?
                """,
                (holder, lease_id, expires, now, now, run_id, row["status"], row["lease_id"]),
            )
            if result.rowcount != 1:
                raise ValueError("verification claim lost a concurrent race")
            updated = conn.execute(
                "SELECT * FROM verification_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            conn.commit()
        assert updated is not None
        return _run(updated)

    def heartbeat(self, run_id: str, holder: str, ttl_seconds: int = 900) -> VerificationRun:
        now, expires = _now(), _future(ttl_seconds)
        with self.store._connect() as conn:
            result = conn.execute(
                """
                UPDATE verification_runs
                SET lease_expires_at=?, last_heartbeat_at=?, updated_at=?
                WHERE run_id=? AND claimed_by=? AND status IN ('claimed','running')
                """,
                (expires, now, now, run_id, holder),
            )
            if result.rowcount != 1:
                raise ValueError("verification heartbeat ownership mismatch")
            conn.commit()
        run = self.get(run_id)
        assert run is not None
        return run

    def start(
        self,
        run_id: str,
        holder: str,
        session_id: str,
        context_pack: Mapping[str, object],
    ) -> VerificationRun:
        now = _now()
        with self.store._connect() as conn:
            result = conn.execute(
                """
                UPDATE verification_runs
                SET status='running', coordinator_session_id=?, context_pack_json=?, updated_at=?
                WHERE run_id=? AND claimed_by=? AND status='claimed'
                """,
                (session_id, _json(dict(context_pack)), now, run_id, holder),
            )
            if result.rowcount != 1:
                raise ValueError("verification start ownership mismatch")
            conn.commit()
        run = self.get(run_id)
        assert run is not None
        return run

    def terminal(
        self,
        run_id: str,
        status: str,
        receipt: Mapping[str, object],
        *,
        reason: str | None = None,
    ) -> VerificationRun:
        if status not in TERMINAL_STATES:
            raise ValueError("invalid verification terminal status")
        with self.store._connect() as conn:
            result = conn.execute(
                """
                UPDATE verification_runs
                SET status=?, terminal_receipt_json=?, stop_reason=?, claimed_by=NULL,
                    lease_id=NULL, lease_expires_at=NULL, updated_at=?
                WHERE run_id=? AND status NOT IN ('completed','failed','needs_human','superseded')
                """,
                (status, _json(dict(receipt)), reason, _now(), run_id),
            )
            if result.rowcount == 0:
                existing = self.get(run_id)
                if existing is None or existing.status != status or existing.terminal_receipt != dict(receipt):
                    raise ValueError("verification run already has a different terminal result")
                return existing
            conn.commit()
        run = self.get(run_id)
        assert run is not None
        return run

    def backoff(self, run_id: str, receipt: Mapping[str, object], retry_after: str) -> VerificationRun:
        with self.store._connect() as conn:
            conn.execute(
                """
                UPDATE verification_runs
                SET status='backoff', terminal_receipt_json=?, retry_after=?, claimed_by=NULL,
                    lease_id=NULL, lease_expires_at=NULL, updated_at=?
                WHERE run_id=? AND status IN ('claimed','running')
                """,
                (_json(dict(receipt)), retry_after, _now(), run_id),
            )
            conn.commit()
        run = self.get(run_id)
        assert run is not None
        return run

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
    ) -> int:
        limits = {"standard_repair": 2, "escalated_repair": 2}
        allowed = {*limits, "review", "verification"}
        if kind not in allowed:
            raise ValueError("invalid verification attempt kind")
        context_hash = hashlib.sha256(_json(dict(context)).encode()).hexdigest()
        with self.store._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if kind == "review":
                reused = conn.execute(
                    "SELECT 1 FROM verification_attempts WHERE run_id=? AND session_id=? LIMIT 1",
                    (run_id, session_id),
                ).fetchone()
                if reused is not None:
                    raise ValueError("independent re-review requires a fresh session")
            count = conn.execute(
                "SELECT COUNT(*) FROM verification_attempts WHERE run_id=? AND attempt_kind=?",
                (run_id, kind),
            ).fetchone()[0]
            ordinal = count + 1
            if kind in limits and ordinal > limits[kind]:
                raise ValueError(f"{kind} budget exhausted")
            if kind == "escalated_repair":
                standard = conn.execute(
                    "SELECT COUNT(*) FROM verification_attempts "
                    "WHERE run_id=? AND attempt_kind='standard_repair'",
                    (run_id,),
                ).fetchone()[0]
                if standard < 2:
                    raise ValueError("strongest capability is only allowed after two standard attempts")
            conn.execute(
                """
                INSERT INTO verification_attempts (
                    attempt_id, run_id, attempt_kind, ordinal, session_id,
                    capability, reasoning_effort, context_hash, outcome,
                    receipt_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    f"vattempt-{uuid.uuid4().hex[:12]}", run_id, kind, ordinal,
                    session_id, capability, reasoning_effort, context_hash, outcome,
                    _json(dict(receipt)) if receipt else None, _now(),
                ),
            )
            conn.commit()
        return ordinal

    def exception(
        self, run_id: str, failure_class: str, packet: Mapping[str, object]
    ) -> str:
        run = self.get(run_id)
        if run is None:
            raise ValueError("verification run not found")
        now = _now()
        exception_id = f"vexception-{hashlib.sha256(f'{run_id}:{failure_class}:{run.head_sha}'.encode()).hexdigest()[:16]}"
        with self.store._connect() as conn:
            conn.execute(
                """
                INSERT INTO verification_exceptions (
                    exception_id, run_id, failure_class, head_sha, packet_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, failure_class, head_sha)
                DO UPDATE SET packet_json=excluded.packet_json, updated_at=excluded.updated_at
                """,
                (exception_id, run_id, failure_class, run.head_sha, _json(dict(packet)), now, now),
            )
            conn.commit()
        return exception_id
