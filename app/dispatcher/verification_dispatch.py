"""Durable verification-request lifecycle on the central dispatcher store."""

from __future__ import annotations

import builtins
import hashlib
import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping, Sequence, TypeGuard

from app.dispatcher.store import SqliteStore

CONTRACT_VERSION = "verification_dispatch_request.v1"
TERMINAL_STATES = frozenset({"completed", "failed", "needs_human", "superseded"})
ACTIVE_STATES = frozenset({"claimed", "running"})
_REQUEST_FIELDS = (
    "contract_version",
    "stage",
    "repository",
    "pr_number",
    "linked_issue",
    "supporting_issues",
    "current_head_sha",
    "source_workflow",
    "artifact_provenance",
    "evidence_pack",
    "live_truth",
    "generated_at",
    "idempotency_key",
)
_NESTED_REQUEST_FIELDS = {
    "source_workflow": ("name", "run_id", "run_attempt", "head_sha"),
    "artifact_provenance": (
        "workflow_run_id",
        "repository_id",
        "artifact_name",
    ),
    "evidence_pack": (
        "contract",
        "workflow_name",
        "artifact_name",
        "repository",
        "pr_number",
        "head_sha",
    ),
    "live_truth": (
        "repository",
        "pr_number",
        "current_head_sha",
        "source_run_id",
    ),
}


class _AuthenticatedVerificationRequest(dict[str, object]):
    """In-process capability minted only after GitHub producer/source authentication."""


def _authenticated_verification_request(
    request: Mapping[str, object],
) -> _AuthenticatedVerificationRequest:
    return _AuthenticatedVerificationRequest(request)


class VerificationSubscriptionBusy(ValueError):
    """The single global verification subscription is already occupied."""


class VerificationBackoffPending(ValueError):
    """A deferred run is not eligible before its durable retry timestamp."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _future(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(
        timespec="microseconds"
    )


def _future_from(now: str, seconds: int) -> str:
    return (datetime.fromisoformat(now) + timedelta(seconds=seconds)).isoformat(
        timespec="microseconds"
    )


def _begin_immediate_now(conn: sqlite3.Connection) -> str:
    """Acquire SQLite's write lock before sampling mutation authority time."""
    conn.execute("BEGIN IMMEDIATE")
    return _now()


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError("retry_after must be an absolute RFC3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("retry_after must include a timezone")
    return parsed.astimezone(timezone.utc)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load(value: str | None) -> Any:
    return json.loads(value) if value else None


def _positive_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _closed_projection(
    value: Mapping[str, object], *, fields: Sequence[str], location: str
) -> dict[str, object]:
    if any(not isinstance(key, str) or key not in fields for key in value):
        raise ValueError(
            f"verification request contains unknown properties in {location}"
        )
    if any(field not in value for field in fields):
        raise ValueError(
            f"verification request is missing required properties in {location}"
        )
    return {field: value[field] for field in fields}


def _canonical_request_projection(request: Mapping[str, object]) -> dict[str, object]:
    """Return the only request shape permitted to cross into durable state."""
    projected = _closed_projection(request, fields=_REQUEST_FIELDS, location="request")
    for field, nested_fields in _NESTED_REQUEST_FIELDS.items():
        value = projected.get(field)
        if not isinstance(value, Mapping):
            raise ValueError(f"malformed verification {field.replace('_', '-')} identity")
        projected[field] = _closed_projection(
            value, fields=nested_fields, location=field
        )
    supporting_issues = projected.get("supporting_issues")
    if isinstance(supporting_issues, list):
        projected["supporting_issues"] = list(supporting_issues)
    return projected


def _required_string(request: Mapping[str, object], field: str) -> str:
    value = request.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError("malformed verification dispatch request")
    return value


def _required_mapping(
    request: Mapping[str, object], field: str
) -> Mapping[str, object]:
    value = request.get(field)
    if not isinstance(value, Mapping):
        raise ValueError(f"malformed verification {field.replace('_', '-')} identity")
    return value


def _required_positive_int(request: Mapping[str, object], field: str) -> int:
    value = request.get(field)
    if not _positive_int(value):
        raise ValueError("malformed verification dispatch request")
    return value


def _validate_request(request: Mapping[str, object]) -> None:
    if "base_ref" in request or "head_ref" in request:
        raise ValueError("verification request contains untrusted branch refs")
    required_strings = {
        "contract_version",
        "stage",
        "repository",
        "base_ref",
        "head_ref",
        "current_head_sha",
        "idempotency_key",
        "generated_at",
    }
    strings = {field: _required_string(request, field) for field in required_strings}
    if request["contract_version"] != CONTRACT_VERSION or request["stage"] != "verification":
        raise ValueError("unsupported verification dispatch request")
    pr_number = _required_positive_int(request, "pr_number")
    linked_issue = _required_positive_int(request, "linked_issue")
    supporting_issues = request.get("supporting_issues")
    if (
        not isinstance(supporting_issues, list)
        or any(not _positive_int(value) for value in supporting_issues)
        or len(set(supporting_issues)) != len(supporting_issues)
        or linked_issue in supporting_issues
    ):
        raise ValueError("verification request supporting issues are malformed")
    repository = strings["repository"]
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) or any(
        component in {".", ".."} for component in repository.split("/")
    ):
        raise ValueError("malformed verification repository identity")
    head_sha = strings["current_head_sha"]
    if not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha):
        raise ValueError("malformed verification head identity")
    source = _required_mapping(request, "source_workflow")
    source_name = _required_string(source, "name")
    source_run_id = _required_positive_int(source, "run_id")
    _required_positive_int(source, "run_attempt")
    source_head_sha = _required_string(source, "head_sha")
    if source_name != "CI" or source_head_sha != head_sha:
        raise ValueError("malformed verification source identity")
    artifact_provenance = _required_mapping(request, "artifact_provenance")
    _required_positive_int(artifact_provenance, "workflow_run_id")
    _required_positive_int(artifact_provenance, "repository_id")
    artifact_name = _required_string(artifact_provenance, "artifact_name")
    expected_artifact_name = f"verification-dispatch-{pr_number}-{head_sha}"
    if artifact_name != expected_artifact_name:
        raise ValueError("malformed verification artifact provenance")
    evidence_pack = _required_mapping(request, "evidence_pack")
    evidence_contract = _required_string(evidence_pack, "contract")
    evidence_workflow = _required_string(evidence_pack, "workflow_name")
    evidence_artifact = _required_string(evidence_pack, "artifact_name")
    evidence_repository = _required_string(evidence_pack, "repository")
    evidence_pr_number = _required_positive_int(evidence_pack, "pr_number")
    evidence_head_sha = _required_string(evidence_pack, "head_sha")
    if (
        evidence_contract != "pr_evidence_pack"
        or evidence_workflow != "PR Evidence Pack"
        or evidence_artifact != f"pr-evidence-pack-{pr_number}"
        or evidence_repository != repository
        or evidence_pr_number != pr_number
        or evidence_head_sha != head_sha
    ):
        raise ValueError("malformed verification evidence-pack identity")
    live_truth = _required_mapping(request, "live_truth")
    live_repository = _required_string(live_truth, "repository")
    live_pr_number = _required_positive_int(live_truth, "pr_number")
    live_head_sha = _required_string(live_truth, "current_head_sha")
    live_source_run_id = _required_positive_int(live_truth, "source_run_id")
    if (
        live_repository != repository
        or live_pr_number != pr_number
        or live_head_sha != head_sha
        or live_source_run_id != source_run_id
    ):
        raise ValueError("verification live truth does not match request identity")
    identity = {
        "contract_version": CONTRACT_VERSION,
        "head_sha": head_sha,
        "pr_number": pr_number,
        "repository": repository,
        "stage": strings["stage"],
    }
    expected = hashlib.sha256(_json(identity).encode()).hexdigest()
    if strings["idempotency_key"] != expected:
        raise ValueError("verification request idempotency key does not match identity")


def _validated_stored_request(value: str | None) -> dict[str, object]:
    loaded = _load(value)
    if not isinstance(loaded, Mapping):
        raise ValueError("verification canonical run authority is malformed")
    projected = _canonical_request_projection(loaded)
    _validate_request(projected)
    return projected


def _validated_row_request(row: sqlite3.Row) -> dict[str, object]:
    request = _validated_stored_request(row["request_json"])
    if (
        row["idempotency_key"] != request["idempotency_key"]
        or row["contract_version"] != request["contract_version"]
        or row["repository"] != request["repository"]
        or row["pr_number"] != request["pr_number"]
        or row["head_sha"] != request["current_head_sha"]
        or row["stage"] != request["stage"]
    ):
        raise ValueError("verification canonical run authority is malformed")
    return request


@dataclass(frozen=True)
class VerificationRun:
    run_id: str
    idempotency_key: str
    repository: str
    pr_number: int
    requested_head_sha: str
    current_head_sha: str
    verified_head_sha: str | None
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

    @property
    def head_sha(self) -> str:
        """Compatibility name for the lease-fenced current PR head."""
        return self.current_head_sha


def _run(row: sqlite3.Row) -> VerificationRun:
    return VerificationRun(
        run_id=row["run_id"],
        idempotency_key=row["idempotency_key"],
        repository=row["repository"],
        pr_number=row["pr_number"],
        requested_head_sha=row["head_sha"],
        current_head_sha=row["current_head_sha"],
        verified_head_sha=row["verified_head_sha"],
        stage=row["stage"],
        status=row["status"],
        claimed_by=row["claimed_by"],
        lease_id=row["lease_id"],
        lease_expires_at=row["lease_expires_at"],
        coordinator_session_id=row["coordinator_session_id"],
        request=_validated_row_request(row),
        context_pack=_load(row["context_pack_json"]),
        terminal_receipt=_load(row["terminal_receipt_json"]),
        stop_reason=row["stop_reason"],
        retry_after=row["retry_after"],
    )


def _attempt(row: sqlite3.Row) -> dict[str, object]:
    return {
        "attempt_id": row["attempt_id"],
        "kind": row["attempt_kind"],
        "ordinal": row["ordinal"],
        "session_id": row["session_id"],
        "capability": row["capability"],
        "reasoning_effort": row["reasoning_effort"],
        "outcome": row["outcome"],
        "receipt": _load(row["receipt_json"]),
    }


class VerificationDispatchLedger:
    """Atomic, idempotent lifecycle for PR/head verification chains."""

    def __init__(self, store: SqliteStore) -> None:
        self.store = store
        self.store.initialize()

    def ingest(self, request: Mapping[str, object]) -> VerificationRun:
        authenticated_artifact = isinstance(request, _AuthenticatedVerificationRequest)
        request = _canonical_request_projection(request)
        _validate_request(request)
        now = _now()
        run_id = f"vrun-{str(request['idempotency_key'])[:16]}"
        with self.store._connect() as conn:
            now = _begin_immediate_now(conn)
            active_before_exact = list(
                conn.execute(
                    """
                    SELECT * FROM verification_runs
                    WHERE repository=? AND pr_number=? AND stage=?
                      AND status IN ('queued','backoff','claimed','running')
                    ORDER BY created_at ASC, run_id ASC
                    """,
                    (request["repository"], request["pr_number"], request["stage"]),
                )
            )
            terminal_before_exact = list(
                conn.execute(
                    """
                    SELECT * FROM verification_runs
                    WHERE repository=? AND pr_number=? AND stage=?
                      AND status IN ('completed','failed','needs_human','superseded')
                    ORDER BY created_at ASC, run_id ASC
                    """,
                    (request["repository"], request["pr_number"], request["stage"]),
                )
            )
            multiple_active = len(active_before_exact) > 1
            active_with_terminal = bool(active_before_exact and terminal_before_exact)
            if multiple_active or active_with_terminal:
                for candidate in [*active_before_exact, *terminal_before_exact]:
                    candidate_request = _validated_row_request(candidate)
                    if candidate_request.get("linked_issue") != request.get(
                        "linked_issue"
                    ):
                        if (
                            candidate["idempotency_key"]
                            == request["idempotency_key"]
                            and candidate["status"]
                            in {"completed", "failed", "needs_human", "superseded"}
                        ):
                            raise ValueError(
                                "verification idempotency authority conflict"
                            )
                        raise ValueError(
                            "verification canonical run governing issue mismatch"
                        )
                if multiple_active:
                    raise ValueError("verification canonical active chain is ambiguous")
                raise ValueError("verification canonical terminal chain is ambiguous")
            existing = conn.execute(
                "SELECT * FROM verification_runs WHERE idempotency_key = ?",
                (request["idempotency_key"],),
            ).fetchone()
            if existing is not None:
                existing_request = _validated_row_request(existing)
                active_status = existing["status"] in {
                    "queued",
                    "backoff",
                    "claimed",
                    "running",
                }
                if (
                    existing["repository"] != request["repository"]
                    or existing["pr_number"] != request["pr_number"]
                    or existing["stage"] != request["stage"]
                    or existing["head_sha"] != request["current_head_sha"]
                ):
                    raise ValueError("verification idempotency authority conflict")
                if existing_request.get("linked_issue") != request.get("linked_issue"):
                    if active_status:
                        raise ValueError(
                            "verification canonical run governing issue mismatch"
                        )
                    raise ValueError("verification idempotency authority conflict")
                if (
                    active_status
                    and existing["current_head_sha"]
                    != request.get("current_head_sha")
                ):
                    raise ValueError(
                        "verification artifact head does not match canonical run"
                    )
                conn.commit()
                return _run(existing)
            for candidate in conn.execute(
                """
                SELECT * FROM verification_runs
                WHERE repository=? AND pr_number=? AND stage=?
                  AND status IN ('queued','backoff','claimed','running')
                ORDER BY created_at ASC, run_id ASC
                """,
                (request["repository"], request["pr_number"], request["stage"]),
            ):
                candidate_request = _validated_row_request(candidate)
                if candidate_request.get("linked_issue") != request.get("linked_issue"):
                    raise ValueError("verification canonical run governing issue mismatch")
                if candidate["current_head_sha"] != request.get("current_head_sha"):
                    lease_expires_at = candidate["lease_expires_at"]
                    candidate_supporting = candidate_request.get("supporting_issues")
                    incoming_supporting = request.get("supporting_issues")
                    supporting_authority_extends = (
                        isinstance(candidate_supporting, list)
                        and isinstance(incoming_supporting, list)
                        and set(candidate_supporting).issubset(incoming_supporting)
                    )
                    authority_matches = (
                        authenticated_artifact
                        and candidate["status"] == "running"
                        and isinstance(lease_expires_at, str)
                        and _parse_timestamp(lease_expires_at)
                        <= _parse_timestamp(now)
                        and supporting_authority_extends
                    )
                    if not authority_matches:
                        raise ValueError(
                            "verification artifact head does not match canonical run"
                        )
                    next_head = request["current_head_sha"]
                    conn.execute(
                        """
                        UPDATE verification_runs
                        SET status='queued', current_head_sha=?, verified_head_sha=NULL,
                            claimed_by=NULL, lease_id=NULL, lease_expires_at=NULL,
                            last_heartbeat_at=NULL, coordinator_session_id=NULL,
                            context_pack_json=NULL, terminal_receipt_json=NULL,
                            stop_reason=NULL, retry_after=NULL, updated_at=?
                        WHERE run_id=? AND status='running' AND lease_expires_at=?
                        """,
                        (
                            next_head,
                            now,
                            candidate["run_id"],
                            lease_expires_at,
                        ),
                    )
                    if conn.execute("SELECT changes()").fetchone()[0] != 1:
                        raise ValueError(
                            "verification canonical run authority changed during reconciliation"
                        )
                    reopened = conn.execute(
                        "SELECT * FROM verification_runs WHERE run_id=?",
                        (candidate["run_id"],),
                    ).fetchone()
                    assert reopened is not None
                    conn.commit()
                    return _run(reopened)
                conn.commit()
                return _run(candidate)
            terminal_candidates = list(
                conn.execute(
                    """
                    SELECT * FROM verification_runs
                    WHERE repository=? AND pr_number=? AND stage=?
                      AND status IN ('completed','failed','needs_human','superseded')
                    ORDER BY created_at ASC, run_id ASC
                    """,
                    (request["repository"], request["pr_number"], request["stage"]),
                )
            )
            for candidate in terminal_candidates:
                candidate_request = _validated_row_request(candidate)
                if candidate_request.get("linked_issue") != request.get("linked_issue"):
                    raise ValueError("verification canonical run governing issue mismatch")
            non_reopenable = [
                candidate
                for candidate in terminal_candidates
                if candidate["status"] != "superseded"
                or candidate["stop_reason"] != "stale_head"
            ]
            if non_reopenable:
                raise ValueError(
                    "verification canonical chain is terminal: "
                    f"{non_reopenable[-1]['status']}"
                )
            stale_candidates = [
                candidate
                for candidate in terminal_candidates
                if candidate["status"] == "superseded"
                and candidate["stop_reason"] == "stale_head"
            ]
            if len(stale_candidates) > 1:
                raise ValueError("verification canonical terminal chain is ambiguous")
            for candidate in stale_candidates:
                next_head = request.get("current_head_sha")
                if candidate["current_head_sha"] == next_head:
                    raise ValueError(
                        "stale-head supersession requires an authoritative new head"
                    )
                conn.execute(
                    """
                    UPDATE verification_runs
                    SET status='queued', current_head_sha=?, verified_head_sha=NULL,
                        claimed_by=NULL, lease_id=NULL, lease_expires_at=NULL,
                        last_heartbeat_at=NULL, coordinator_session_id=NULL,
                        context_pack_json=NULL, terminal_receipt_json=NULL,
                        stop_reason=NULL, retry_after=NULL, updated_at=?
                    WHERE run_id=? AND status='superseded'
                      AND stop_reason='stale_head'
                    """,
                    (next_head, now, candidate["run_id"]),
                )
                reopened = conn.execute(
                    "SELECT * FROM verification_runs WHERE run_id=?",
                    (candidate["run_id"],),
                ).fetchone()
                assert reopened is not None
                conn.commit()
                return _run(reopened)
            conn.execute(
                """
                INSERT OR IGNORE INTO verification_runs (
                    run_id, idempotency_key, contract_version, repository,
                    pr_number, head_sha, current_head_sha, stage, request_json, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
                """,
                (
                    run_id,
                    request["idempotency_key"],
                    request["contract_version"],
                    request["repository"],
                    request["pr_number"],
                    request["current_head_sha"],
                    request["current_head_sha"],
                    request["stage"],
                    _json(request),
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
        lease_id = f"vlease-{uuid.uuid4().hex[:12]}"
        with self.store._connect() as conn:
            now = _begin_immediate_now(conn)
            expires = _future_from(now, ttl_seconds)
            row = conn.execute(
                "SELECT * FROM verification_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"verification run {run_id} not found")
            expired = row["lease_expires_at"] is not None and row["lease_expires_at"] <= now
            if row["status"] == "backoff" and (
                not row["retry_after"] or row["retry_after"] > now
            ):
                raise VerificationBackoffPending(
                    f"verification run {run_id} is deferred until {row['retry_after']}"
                )
            eligible = row["status"] in {"queued", "backoff"} or (
                row["status"] in ACTIVE_STATES and expired
            )
            if not eligible:
                raise ValueError(f"verification run {run_id} is not claimable")
            occupied = conn.execute(
                """
                SELECT run_id FROM verification_runs
                WHERE run_id<>? AND status IN ('claimed','running')
                  AND lease_expires_at>?
                LIMIT 1
                """,
                (run_id, now),
            ).fetchone()
            if occupied is not None:
                raise VerificationSubscriptionBusy(
                    f"verification subscription occupied by {occupied['run_id']}"
                )
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

    def heartbeat(
        self, run_id: str, holder: str, lease_id: str, ttl_seconds: int = 900
    ) -> VerificationRun:
        with self.store._connect() as conn:
            now = _begin_immediate_now(conn)
            expires = _future(ttl_seconds)
            result = conn.execute(
                """
                UPDATE verification_runs
                SET lease_expires_at=?, last_heartbeat_at=?, updated_at=?
                WHERE run_id=? AND claimed_by=? AND lease_id=?
                  AND status IN ('claimed','running')
                  AND lease_expires_at>?
                """,
                (expires, now, now, run_id, holder, lease_id, now),
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
        lease_id: str,
        session_id: str,
        context_pack: Mapping[str, object],
    ) -> VerificationRun:
        with self.store._connect() as conn:
            now = _begin_immediate_now(conn)
            result = conn.execute(
                """
                UPDATE verification_runs
                SET status='running', coordinator_session_id=?, context_pack_json=?, updated_at=?
                WHERE run_id=? AND claimed_by=? AND lease_id=? AND status='claimed'
                  AND lease_expires_at>?
                """,
                (session_id, _json(dict(context_pack)), now, run_id, holder, lease_id, now),
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
        holder: str,
        lease_id: str,
    ) -> VerificationRun:
        if status not in TERMINAL_STATES:
            raise ValueError("invalid verification terminal status")
        with self.store._connect() as conn:
            now = _begin_immediate_now(conn)
            owner = conn.execute(
                """
                SELECT current_head_sha FROM verification_runs
                WHERE run_id=? AND claimed_by=? AND lease_id=?
                  AND status IN ('claimed','running')
                  AND lease_expires_at>?
                """,
                (run_id, holder, lease_id, now),
            ).fetchone()
            if owner is None:
                raise ValueError("verification terminal ownership mismatch")
            if status == "completed" and not self._closure_ready(
                conn, run_id, owner["current_head_sha"]
            ):
                raise ValueError(
                    "completed requires two fresh clean reviews after the final repair"
                )
            result = conn.execute(
                """
                UPDATE verification_runs
                SET status=?, terminal_receipt_json=?, stop_reason=?, claimed_by=NULL,
                    lease_id=NULL, lease_expires_at=NULL,
                    verified_head_sha=CASE WHEN ?='completed' THEN current_head_sha
                                           ELSE verified_head_sha END,
                    updated_at=?
                WHERE run_id=? AND claimed_by=? AND lease_id=?
                  AND status IN ('claimed','running')
                  AND lease_expires_at>?
                """,
                (
                    status,
                    _json(dict(receipt)),
                    reason,
                    status,
                    now,
                    run_id,
                    holder,
                    lease_id,
                    now,
                ),
            )
            if result.rowcount == 0:
                raise ValueError("verification terminal ownership mismatch")
            updated = conn.execute(
                "SELECT * FROM verification_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            conn.commit()
        assert updated is not None
        return _run(updated)

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
        """Advance the active head only under the lease and exact live GitHub truth.

        ``verification_runs.head_sha`` remains the immutable request identity used by
        the idempotency/unique contract. Only ``current_head_sha`` advances, and any
        prior verified-head marker is cleared until two clean reviews complete.
        """
        if not re.fullmatch(r"[0-9a-fA-F]{40}", new_head_sha):
            raise ValueError("malformed verification rebind head")
        if new_head_sha != observed_head_sha:
            raise ValueError("verification rebind does not match live PR head")
        with self.store._connect() as conn:
            now = _begin_immediate_now(conn)
            row = conn.execute(
                "SELECT * FROM verification_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise ValueError("verification run not found")
            if (
                row["repository"] != observed_repository
                or row["pr_number"] != observed_pr_number
            ):
                raise ValueError("verification rebind live PR identity mismatch")
            result = conn.execute(
                """
                UPDATE verification_runs
                SET current_head_sha=?, verified_head_sha=NULL, updated_at=?
                WHERE run_id=? AND current_head_sha=?
                  AND claimed_by=? AND lease_id=?
                  AND status IN ('claimed','running')
                  AND lease_expires_at>?
                """,
                (
                    new_head_sha,
                    now,
                    run_id,
                    expected_head_sha,
                    holder,
                    lease_id,
                    now,
                ),
            )
            if result.rowcount != 1:
                raise ValueError("verification head rebind ownership or head mismatch")
            updated = conn.execute(
                "SELECT * FROM verification_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            conn.commit()
        assert updated is not None
        return _run(updated)

    def backoff(
        self,
        run_id: str,
        receipt: Mapping[str, object],
        retry_after: str,
        *,
        holder: str,
        lease_id: str,
    ) -> VerificationRun:
        _parse_timestamp(retry_after)
        with self.store._connect() as conn:
            now = _begin_immediate_now(conn)
            result = conn.execute(
                """
                UPDATE verification_runs
                SET status='backoff', terminal_receipt_json=?, retry_after=?, claimed_by=NULL,
                    lease_id=NULL, lease_expires_at=NULL, updated_at=?
                WHERE run_id=? AND claimed_by=? AND lease_id=?
                  AND status IN ('claimed','running')
                  AND lease_expires_at>?
                """,
                (_json(dict(receipt)), retry_after, now, run_id, holder, lease_id, now),
            )
            if result.rowcount != 1:
                raise ValueError("verification backoff ownership mismatch")
            conn.commit()
        run = self.get(run_id)
        assert run is not None
        return run

    def defer_unclaimed(
        self, run_id: str, receipt: Mapping[str, object], retry_after: str
    ) -> VerificationRun:
        _parse_timestamp(retry_after)
        now = _now()
        with self.store._connect() as conn:
            result = conn.execute(
                """
                UPDATE verification_runs
                SET status='backoff', terminal_receipt_json=?, retry_after=?,
                    claimed_by=NULL, lease_id=NULL, lease_expires_at=NULL, updated_at=?
                WHERE run_id=? AND (
                    status IN ('queued','backoff') OR
                    (status IN ('claimed','running') AND lease_expires_at<=?)
                )
                """,
                (_json(dict(receipt)), retry_after, now, run_id, now),
            )
            if result.rowcount != 1:
                raise ValueError("verification run is not unclaimed and deferrable")
            conn.commit()
        run = self.get(run_id)
        assert run is not None
        return run

    def supersede_unclaimed(
        self, run_id: str, receipt: Mapping[str, object], *, reason: str
    ) -> VerificationRun:
        now = _now()
        with self.store._connect() as conn:
            result = conn.execute(
                """
                UPDATE verification_runs
                SET status='superseded', terminal_receipt_json=?, stop_reason=?,
                    claimed_by=NULL, lease_id=NULL, lease_expires_at=NULL, updated_at=?
                WHERE run_id=? AND (
                    status IN ('queued','backoff') OR
                    (status IN ('claimed','running') AND lease_expires_at<=?)
                )
                """,
                (_json(dict(receipt)), reason, now, run_id, now),
            )
            if result.rowcount != 1:
                raise ValueError("verification run is not unclaimed and supersedable")
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
        *,
        holder: str,
        lease_id: str,
        idempotency_key: str | None = None,
    ) -> int:
        limits = {"standard_repair": 2, "escalated_repair": 2}
        allowed = {*limits, "review", "verification"}
        if kind not in allowed:
            raise ValueError("invalid verification attempt kind")
        context_hash = hashlib.sha256(_json(dict(context)).encode()).hexdigest()
        attempt_id = (
            "vattempt-"
            + hashlib.sha256(f"{run_id}:{idempotency_key}".encode()).hexdigest()[:16]
            if idempotency_key
            else f"vattempt-{uuid.uuid4().hex[:12]}"
        )
        with self.store._connect() as conn:
            now = _begin_immediate_now(conn)
            owner = conn.execute(
                """
                SELECT 1 FROM verification_runs
                WHERE run_id=? AND claimed_by=? AND lease_id=?
                  AND status IN ('claimed','running')
                  AND lease_expires_at>?
                """,
                (run_id, holder, lease_id, now),
            ).fetchone()
            if owner is None:
                raise ValueError("verification attempt ownership mismatch")
            if idempotency_key:
                existing = conn.execute(
                    "SELECT * FROM verification_attempts WHERE attempt_id=?",
                    (attempt_id,),
                ).fetchone()
                if existing is not None:
                    row = _attempt(existing)
                    if (
                        row["kind"] != kind
                        or row["session_id"] != session_id
                        or row["capability"] != capability
                        or row["reasoning_effort"] != reasoning_effort
                        or row["outcome"] != outcome
                        or row["receipt"] != (dict(receipt) if receipt else None)
                    ):
                        raise ValueError("verification attempt replay conflicts")
                    replay_ordinal = row["ordinal"]
                    if not isinstance(replay_ordinal, int) or isinstance(
                        replay_ordinal, bool
                    ):
                        raise ValueError("verification attempt replay ordinal is malformed")
                    conn.commit()
                    return replay_ordinal
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
                    attempt_id, run_id, kind, ordinal,
                    session_id, capability, reasoning_effort, context_hash, outcome,
                    _json(dict(receipt)) if receipt else None, now,
                ),
            )
            conn.commit()
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
        """Validate and insert one coordinator event batch in one transaction.

        The stable ``batch_id`` makes an exact replay a no-op. A planner error,
        ownership loss, head change, or later insert conflict rolls the entire
        batch back, so recovery never observes a prefix of the final receipt.
        """
        if not batch_id or batch_size <= 0:
            raise ValueError("verification event batch identity is required")

        def attempt_id(index: int) -> str:
            digest = hashlib.sha256(f"{run_id}:{batch_id}:{index}".encode()).hexdigest()
            return f"vattempt-{digest[:16]}"

        with self.store._connect() as conn:
            now = _begin_immediate_now(conn)
            owner = conn.execute(
                """
                SELECT current_head_sha FROM verification_runs
                WHERE run_id=? AND claimed_by=? AND lease_id=?
                  AND status IN ('claimed','running')
                  AND lease_expires_at>?
                """,
                (run_id, holder, lease_id, now),
            ).fetchone()
            if owner is None:
                raise ValueError("verification event batch ownership mismatch")
            if owner["current_head_sha"] != expected_head_sha:
                raise ValueError("verification event batch head changed")
            rows = conn.execute(
                "SELECT * FROM verification_attempts "
                "WHERE run_id=? ORDER BY created_at, attempt_id",
                (run_id,),
            ).fetchall()
            attempts = [_attempt(row) for row in rows]
            replay_rows = [
                row
                for row in attempts
                if isinstance(row["receipt"], Mapping)
                and row["receipt"].get("event_batch_id") == batch_id
            ]
            if replay_rows:
                indexes = {
                    row["receipt"].get("event_batch_index")
                    for row in replay_rows
                    if isinstance(row["receipt"], Mapping)
                }
                sizes = {
                    row["receipt"].get("event_batch_size")
                    for row in replay_rows
                    if isinstance(row["receipt"], Mapping)
                }
                expected_indexes = set(range(batch_size))
                if indexes != expected_indexes or sizes != {batch_size}:
                    raise ValueError("verification event batch is partially persisted")
                conn.commit()
                return 0

            planned = list(planner(attempts, attempt_id))
            if len(planned) != batch_size:
                raise ValueError("verification event batch plan size mismatch")
            batch_started = datetime.now(timezone.utc)
            for index, item in enumerate(planned):
                item_receipt = item["receipt"]
                if not isinstance(item_receipt, Mapping):
                    raise ValueError("verification event batch receipt is malformed")
                receipt = dict(item_receipt)
                receipt.update(
                    {
                        "event_batch_id": batch_id,
                        "event_batch_index": index,
                        "event_batch_size": batch_size,
                    }
                )
                conn.execute(
                    """
                    INSERT INTO verification_attempts (
                        attempt_id, run_id, attempt_kind, ordinal, session_id,
                        capability, reasoning_effort, context_hash, outcome,
                        receipt_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["attempt_id"],
                        run_id,
                        item["kind"],
                        item["ordinal"],
                        item["session_id"],
                        item["capability"],
                        item["reasoning_effort"],
                        item["context_hash"],
                        item["outcome"],
                        _json(receipt),
                        (batch_started + timedelta(microseconds=index)).isoformat(
                            timespec="microseconds"
                        ),
                    ),
                )
            conn.commit()
        return len(planned)

    def _attempts(
        self, conn: sqlite3.Connection, run_id: str
    ) -> builtins.list[dict[str, object]]:
        rows = conn.execute(
            "SELECT * FROM verification_attempts WHERE run_id=? ORDER BY created_at, attempt_id",
            (run_id,),
        ).fetchall()
        return [_attempt(row) for row in rows]

    def attempts(self, run_id: str) -> builtins.list[dict[str, object]]:
        with self.store._connect() as conn:
            return self._attempts(conn, run_id)

    def _closure_ready(
        self, conn: sqlite3.Connection, run_id: str, current_head_sha: str
    ) -> bool:
        attempts = self._attempts(conn, run_id)
        repairs = [row for row in attempts if row["kind"] in {"standard_repair", "escalated_repair"}]
        verifications = [row for row in attempts if row["kind"] == "verification"]
        if not repairs and not verifications:
            return False
        final_anchor = (repairs[-1] if repairs else verifications[-1])["attempt_id"]
        reviews = [
            row for row in attempts
            if row["kind"] == "review"
            and isinstance(row["receipt"], Mapping)
            and row["receipt"].get("reviewed_attempt_id") == final_anchor
            and row["receipt"].get("head_sha") == current_head_sha
            and row["outcome"] == "clean"
        ]
        return len(reviews) >= 2 and len({row["session_id"] for row in reviews[-2:]}) == 2

    def closure_ready(self, run_id: str) -> bool:
        with self.store._connect() as conn:
            row = conn.execute(
                "SELECT current_head_sha FROM verification_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                return False
            return self._closure_ready(conn, run_id, row["current_head_sha"])

    def exception(
        self,
        run_id: str,
        failure_class: str,
        packet: Mapping[str, object],
        *,
        holder: str,
        lease_id: str,
    ) -> str:
        with self.store._connect() as conn:
            now = _begin_immediate_now(conn)
            owner = conn.execute(
                """
                SELECT current_head_sha FROM verification_runs
                WHERE run_id=? AND claimed_by=? AND lease_id=?
                  AND status IN ('claimed','running')
                  AND lease_expires_at>?
                """,
                (run_id, holder, lease_id, now),
            ).fetchone()
            if owner is None:
                raise ValueError("verification exception ownership mismatch")
            head_sha = owner["current_head_sha"]
            exception_id = "vexception-" + hashlib.sha256(
                f"{run_id}:{failure_class}:{head_sha}".encode()
            ).hexdigest()[:16]
            conn.execute(
                """
                INSERT INTO verification_exceptions (
                    exception_id, run_id, failure_class, head_sha, packet_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id, failure_class, head_sha)
                DO UPDATE SET packet_json=excluded.packet_json, updated_at=excluded.updated_at
                """,
                (exception_id, run_id, failure_class, head_sha, _json(dict(packet)), now, now),
            )
            conn.commit()
        return exception_id
