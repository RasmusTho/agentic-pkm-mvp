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

from app.dispatcher.schema import LEGACY_UNTRUSTED_VERIFICATION_STATUS
from app.dispatcher.verification_contract import MAX_CLOSING_ISSUES
from app.dispatcher.store import (
    SqliteStore,
    recognized_ambiguous_v1_closure_request,
    recognized_pre_trust_verification_request,
    validated_legacy_current_head,
)

LEGACY_CONTRACT_VERSION = "verification_dispatch_request.v1"
CONTRACT_VERSION = "verification_dispatch_request.v2"
TERMINAL_STATES = frozenset({"completed", "failed", "needs_human", "superseded"})
ACTIVE_STATES = frozenset({"claimed", "running"})
REPAIR_BUDGET_POLICY_LEGACY = "v1"
REPAIR_BUDGET_POLICY_MECHANISM = "v2"
REPAIR_ATTEMPT_LIMITS = {"standard_repair": 2, "escalated_repair": 2}
REPAIR_FAILURE_DOMAINS = frozenset(
    {
        "review_code_correctness",
        "static_quality",
        "lease_concurrency",
        "deployment_model_schema",
    }
)
_STABLE_MECHANISM_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:+-]{0,127}\Z")
_REQUEST_FIELDS_V1 = (
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
_REQUEST_FIELDS = (
    *_REQUEST_FIELDS_V1[:5],
    "closing_issues",
    *_REQUEST_FIELDS_V1[5:],
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
_LEGACY_RECOVERY_AUDIT_CONTRACT_V1 = "verification_legacy_recovery_audit.v1"
_LEGACY_RECOVERY_AUDIT_CONTRACT = "verification_legacy_recovery_audit.v2"
_LEGACY_RECOVERY_ROW_FIELDS = (
    "run_id",
    "idempotency_key",
    "contract_version",
    "repository",
    "pr_number",
    "head_sha",
    "current_head_sha",
    "verified_head_sha",
    "stage",
    "request_json",
    "supporting_authority_json",
    "closing_authority_json",
    "legacy_recovery_audit_json",
    "repair_budget_policy",
    "status",
    "claimed_by",
    "lease_id",
    "lease_expires_at",
    "last_heartbeat_at",
    "coordinator_session_id",
    "context_pack_json",
    "terminal_receipt_json",
    "stop_reason",
    "retry_after",
    "created_at",
    "updated_at",
)
_LEGACY_RECOVERY_EXCEPTION_FIELDS = (
    "exception_id",
    "run_id",
    "failure_class",
    "head_sha",
    "packet_json",
    "created_at",
    "updated_at",
)


class _AuthenticatedVerificationRequest(dict[str, object]):
    """In-process capability minted only after GitHub producer/source authentication."""


@dataclass(frozen=True)
class _LiveVerificationObservation:
    """Bounded fresh PR observation carried without retaining the raw PR body."""

    repository: str
    pr_number: int
    head_sha: str
    state: str
    draft: bool
    merged_at: str | None
    linked_issue: int | None
    closing_issues: tuple[int, ...]
    supporting_issues: tuple[int, ...]


@dataclass(frozen=True)
class _CanonicalVerificationChainToken:
    """Bounded optimistic token for the canonical chain observed before GitHub I/O."""

    repository: str
    pr_number: int
    stage: str
    linked_issue: int
    fingerprint: str


class _LiveObservedVerificationRequest(_AuthenticatedVerificationRequest):
    """Authenticated artifact paired with a fresh structured live PR observation."""

    live_observation: _LiveVerificationObservation
    canonical_chain_token: _CanonicalVerificationChainToken

    def __init__(
        self,
        request: Mapping[str, object],
        live_observation: _LiveVerificationObservation,
        canonical_chain_token: _CanonicalVerificationChainToken,
    ) -> None:
        super().__init__(request)
        self.live_observation = live_observation
        self.canonical_chain_token = canonical_chain_token


def _authenticated_verification_request(
    request: Mapping[str, object],
) -> _AuthenticatedVerificationRequest:
    projected = _canonical_request_projection(request)
    _validate_request(projected)
    return _AuthenticatedVerificationRequest(projected)


def _live_observed_verification_request(
    request: Mapping[str, object],
    *,
    observed_repository: object,
    observed_pr_number: object,
    observed_head_sha: object,
    observed_state: object,
    observed_merged_at: object,
    observed_draft: object,
    observed_linked_issue: object,
    observed_closing_issues: object,
    observed_supporting_issues: object,
    canonical_chain_token: object,
) -> _LiveObservedVerificationRequest:
    """Pair an authenticated artifact with bounded, structurally valid live PR truth."""

    if not isinstance(request, _AuthenticatedVerificationRequest):
        raise ValueError("verification live PR observation requires authenticated artifact")
    projected = _canonical_request_projection(request)
    _validate_request(projected)
    if (
        not isinstance(observed_repository, str)
        or not re.fullmatch(
            r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", observed_repository
        )
        or any(
            component in {".", ".."} for component in observed_repository.split("/")
        )
        or not _positive_int(observed_pr_number)
        or not isinstance(observed_head_sha, str)
        or not re.fullmatch(r"[0-9a-fA-F]{40}", observed_head_sha)
        or not isinstance(observed_state, str)
        or not observed_state
        or not isinstance(observed_draft, bool)
        or (
            observed_merged_at is not None
            and (not isinstance(observed_merged_at, str) or not observed_merged_at)
        )
        or (
            observed_linked_issue is not None
            and not _positive_int(observed_linked_issue)
        )
        or (
            observed_linked_issue is None
            and (
                observed_closing_issues is not None
                or observed_supporting_issues is not None
            )
        )
        or (
            observed_linked_issue is not None
            and (
                not isinstance(observed_supporting_issues, tuple)
                or not isinstance(observed_closing_issues, tuple)
                or not observed_closing_issues
                or len(observed_closing_issues) > MAX_CLOSING_ISSUES
                or any(
                    not _positive_int(issue) for issue in observed_closing_issues
                )
                or len(set(observed_closing_issues)) != len(observed_closing_issues)
                or any(
                    not _positive_int(issue)
                    for issue in observed_supporting_issues
                )
                or len(set(observed_supporting_issues))
                != len(observed_supporting_issues)
            )
        )
        or not isinstance(
            canonical_chain_token, _CanonicalVerificationChainToken
        )
        or canonical_chain_token.repository != projected.get("repository")
        or canonical_chain_token.pr_number != projected.get("pr_number")
        or canonical_chain_token.stage != projected.get("stage")
        or canonical_chain_token.linked_issue != projected.get("linked_issue")
        or not re.fullmatch(r"[0-9a-f]{64}", canonical_chain_token.fingerprint)
    ):
        raise ValueError("malformed fresh live PR observation")
    supporting_issues = tuple(
        issue
        for issue in (
            observed_supporting_issues
            if isinstance(observed_supporting_issues, tuple)
            else ()
        )
        if _positive_int(issue)
    )
    closing_issues = tuple(
        issue
        for issue in (
            observed_closing_issues
            if isinstance(observed_closing_issues, tuple)
            else ()
        )
        if _positive_int(issue)
    )
    observation = _LiveVerificationObservation(
        repository=observed_repository,
        pr_number=observed_pr_number,
        head_sha=observed_head_sha,
        state=observed_state,
        draft=observed_draft,
        merged_at=observed_merged_at,
        linked_issue=(
            observed_linked_issue
            if _positive_int(observed_linked_issue)
            else None
        ),
        closing_issues=tuple(sorted(closing_issues)),
        supporting_issues=tuple(sorted(supporting_issues)),
    )
    assert isinstance(canonical_chain_token, _CanonicalVerificationChainToken)
    return _LiveObservedVerificationRequest(
        projected, observation, canonical_chain_token
    )


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
    fields = (
        _REQUEST_FIELDS_V1
        if request.get("contract_version") == LEGACY_CONTRACT_VERSION
        else _REQUEST_FIELDS
    )
    projected = _closed_projection(request, fields=fields, location="request")
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
    closing_issues = projected.get("closing_issues")
    if isinstance(closing_issues, list):
        projected["closing_issues"] = list(closing_issues)
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


def _validate_request(
    request: Mapping[str, object], *, allow_legacy_audit: bool = False
) -> None:
    if "base_ref" in request or "head_ref" in request:
        raise ValueError("verification request contains untrusted branch refs")
    required_strings = {
        "contract_version",
        "stage",
        "repository",
        "current_head_sha",
        "idempotency_key",
        "generated_at",
    }
    strings = {field: _required_string(request, field) for field in required_strings}
    if request["contract_version"] not in {
        LEGACY_CONTRACT_VERSION,
        CONTRACT_VERSION,
    } or request["stage"] != "verification":
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
    if (
        request["contract_version"] == LEGACY_CONTRACT_VERSION
        and not allow_legacy_audit
    ):
        raise ValueError(
            "legacy verification request does not authenticate closing authority; "
            "fresh v2 artifact required"
        )
    if request["contract_version"] == CONTRACT_VERSION:
        closing_issues = request.get("closing_issues")
        if (
            not isinstance(closing_issues, list)
            or not closing_issues
            or len(closing_issues) > MAX_CLOSING_ISSUES
            or any(not _positive_int(value) for value in closing_issues)
            or len(set(closing_issues)) != len(closing_issues)
            or not set(closing_issues).issubset({linked_issue, *supporting_issues})
        ):
            raise ValueError("verification request closing issues are malformed")
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
        "contract_version": strings["contract_version"],
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
    if row["status"] == LEGACY_UNTRUSTED_VERIFICATION_STATUS:
        raise ValueError("legacy verification audit is not executable")
    request = _validated_stored_request(row["request_json"])
    idempotency_key = request["idempotency_key"]
    assert isinstance(idempotency_key, str)
    legacy_recovery_audit = _validated_legacy_recovery_audit(row)
    current_head_sha = row["current_head_sha"]
    verified_head_sha = row["verified_head_sha"]
    if (
        (
            row["run_id"] != f"vrun-{idempotency_key[:16]}"
            and legacy_recovery_audit is None
        )
        or row["idempotency_key"] != request["idempotency_key"]
        or row["contract_version"] != request["contract_version"]
        or row["repository"] != request["repository"]
        or row["pr_number"] != request["pr_number"]
        or (
            row["head_sha"] != request["current_head_sha"]
            and legacy_recovery_audit is None
        )
        or row["stage"] != request["stage"]
    ):
        raise ValueError("verification canonical run authority is malformed")
    if not isinstance(current_head_sha, str) or not re.fullmatch(
        r"[0-9a-fA-F]{40}", current_head_sha
    ):
        raise ValueError("verification canonical run authority is malformed")
    if verified_head_sha is not None and (
        not isinstance(verified_head_sha, str)
        or not re.fullmatch(r"[0-9a-fA-F]{40}", verified_head_sha)
        or verified_head_sha != current_head_sha
        or row["status"] != "completed"
    ):
        raise ValueError("verification canonical run authority is malformed")
    _validated_supporting_authority(row, request)
    _validated_closing_authority(row, request)
    return request


def _validated_legacy_row_request(
    row: Mapping[str, object] | sqlite3.Row,
) -> dict[str, object]:
    request_json = row["request_json"]
    supporting_authority_json = row["supporting_authority_json"]
    closing_authority_json = row["closing_authority_json"]
    loaded = _load(request_json if isinstance(request_json, str) else None)
    if (
        row["status"] != LEGACY_UNTRUSTED_VERIFICATION_STATUS
        or not isinstance(loaded, Mapping)
        or not (
            recognized_pre_trust_verification_request(row, loaded)
            or recognized_ambiguous_v1_closure_request(row, loaded)
        )
        or _load(
            supporting_authority_json
            if isinstance(supporting_authority_json, str)
            else None
        )
        != []
        or _load(
            closing_authority_json
            if isinstance(closing_authority_json, str)
            else None
        )
        != []
        or row["legacy_recovery_audit_json"] is not None
        or row["verified_head_sha"] is not None
        or any(
            row[field] is not None
            for field in (
                "claimed_by",
                "lease_id",
                "lease_expires_at",
                "last_heartbeat_at",
                "coordinator_session_id",
                "context_pack_json",
                "retry_after",
            )
        )
    ):
        raise ValueError("legacy verification audit is malformed")
    validated_legacy_current_head(row)
    return dict(loaded)


def _validated_legacy_recovery_audit(
    row: Mapping[str, object] | sqlite3.Row,
) -> dict[str, object] | None:
    """Validate the immutable quarantined row archived by same-head recovery."""
    raw = row["legacy_recovery_audit_json"]
    if raw is None:
        return None
    loaded = _load(raw if isinstance(raw, str) else None)
    if not isinstance(loaded, Mapping):
        raise ValueError("legacy verification recovery audit is malformed")
    contract = loaded.get("contract")
    expected_fields = (
        {"contract", "quarantined_row"}
        if contract == _LEGACY_RECOVERY_AUDIT_CONTRACT_V1
        else {"contract", "quarantined_row", "quarantined_exceptions"}
    )
    if set(loaded) != expected_fields:
        raise ValueError("legacy verification recovery audit is malformed")
    archived = loaded.get("quarantined_row")
    if (
        contract
        not in {
            _LEGACY_RECOVERY_AUDIT_CONTRACT_V1,
            _LEGACY_RECOVERY_AUDIT_CONTRACT,
        }
        or not isinstance(archived, Mapping)
        or set(archived) != set(_LEGACY_RECOVERY_ROW_FIELDS)
    ):
        raise ValueError("legacy verification recovery audit is malformed")
    legacy_request = _validated_legacy_row_request(archived)
    recovered_request = _validated_stored_request(
        row["request_json"] if isinstance(row["request_json"], str) else None
    )
    if (
        archived["run_id"] != row["run_id"]
        or archived["repository"] != row["repository"]
        or archived["pr_number"] != row["pr_number"]
        or archived["head_sha"] != row["head_sha"]
        or archived["current_head_sha"] != recovered_request["current_head_sha"]
        or archived["stage"] != row["stage"]
        or archived["repair_budget_policy"] != row["repair_budget_policy"]
        or archived["created_at"] != row["created_at"]
        or archived["idempotency_key"] == row["idempotency_key"]
        or legacy_request.get("linked_issue")
        != recovered_request.get("linked_issue")
    ):
        raise ValueError("legacy verification recovery audit is malformed")
    if contract == _LEGACY_RECOVERY_AUDIT_CONTRACT:
        exceptions = loaded.get("quarantined_exceptions")
        if not isinstance(exceptions, list):
            raise ValueError("legacy verification recovery audit is malformed")
        seen_exception_ids: set[str] = set()
        seen_exception_keys: set[tuple[str, str]] = set()
        for exception in exceptions:
            if not isinstance(exception, Mapping) or set(exception) != set(
                _LEGACY_RECOVERY_EXCEPTION_FIELDS
            ):
                raise ValueError("legacy verification recovery audit is malformed")
            exception_id = exception.get("exception_id")
            failure_class = exception.get("failure_class")
            head_sha = exception.get("head_sha")
            packet_json = exception.get("packet_json")
            if (
                not isinstance(exception_id, str)
                or not exception_id
                or exception_id in seen_exception_ids
                or exception.get("run_id") != row["run_id"]
                or not isinstance(failure_class, str)
                or not failure_class
                or not isinstance(head_sha, str)
                or re.fullmatch(r"[0-9a-fA-F]{40}", head_sha) is None
                or (failure_class, head_sha) in seen_exception_keys
                or not isinstance(packet_json, str)
                or not isinstance(_load(packet_json), Mapping)
                or not isinstance(exception.get("created_at"), str)
                or not isinstance(exception.get("updated_at"), str)
            ):
                raise ValueError("legacy verification recovery audit is malformed")
            seen_exception_ids.add(exception_id)
            seen_exception_keys.add((failure_class, head_sha))
    return dict(archived)


def _legacy_recovery_audit_snapshot(
    conn: sqlite3.Connection, row: sqlite3.Row
) -> str:
    """Serialize the inert row and exception children before v2 activation."""
    _validated_legacy_row_request(row)
    archived = {field: row[field] for field in _LEGACY_RECOVERY_ROW_FIELDS}
    exceptions = [
        {field: exception[field] for field in _LEGACY_RECOVERY_EXCEPTION_FIELDS}
        for exception in conn.execute(
            """
            SELECT * FROM verification_exceptions
            WHERE run_id=? ORDER BY exception_id ASC
            """,
            (row["run_id"],),
        )
    ]
    return _json(
        {
            "contract": _LEGACY_RECOVERY_AUDIT_CONTRACT,
            "quarantined_row": archived,
            "quarantined_exceptions": exceptions,
        }
    )


def _validated_supporting_authority(
    row: sqlite3.Row, request: Mapping[str, object]
) -> list[int]:
    """Validate the durable cumulative supporting evidence for a run."""
    loaded = _load(row["supporting_authority_json"])
    requested = request.get("supporting_issues")
    if (
        not isinstance(loaded, list)
        or any(not _positive_int(issue) for issue in loaded)
        or len(set(loaded)) != len(loaded)
        or not isinstance(requested, list)
        or not set(requested).issubset(loaded)
    ):
        raise ValueError("verification canonical supporting authority is malformed")
    return loaded


def _request_closing_authority(request: Mapping[str, object]) -> list[int]:
    if request.get("contract_version") != CONTRACT_VERSION:
        raise ValueError("verification closing authority requires a v2 artifact")
    closing = request.get("closing_issues")
    if not isinstance(closing, list):
        raise ValueError("verification closing authority is malformed")
    return list(closing)


def _validated_closing_authority(
    row: sqlite3.Row, request: Mapping[str, object]
) -> list[int]:
    loaded = _load(row["closing_authority_json"])
    requested = _request_closing_authority(request)
    if (
        not isinstance(loaded, list)
        or any(not _positive_int(issue) for issue in loaded)
        or len(set(loaded)) != len(loaded)
        or loaded != requested
    ):
        raise ValueError("verification canonical closing authority is malformed")
    return loaded


def _fingerprint_record(
    digest: Any, table: str, row: Mapping[str, object]
) -> None:
    encoded = _json({"table": table, "row": dict(row)}).encode()
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _canonical_chain_fingerprint(
    conn: sqlite3.Connection, request: Mapping[str, object]
) -> str:
    """Hash the complete bounded token input without exposing canonical row data."""

    digest = hashlib.sha256()
    identity = {
        "repository": request["repository"],
        "pr_number": request["pr_number"],
        "stage": request["stage"],
        "linked_issue": request["linked_issue"],
    }
    _fingerprint_record(digest, "identity", identity)
    rows = conn.execute(
        """
        SELECT * FROM verification_runs
        WHERE repository=? AND pr_number=? AND stage=?
        ORDER BY created_at ASC, run_id ASC
        """,
        (request["repository"], request["pr_number"], request["stage"]),
    ).fetchall()
    for row in rows:
        if row["status"] == LEGACY_UNTRUSTED_VERIFICATION_STATUS:
            _validated_legacy_row_request(row)
        else:
            _validated_row_request(row)
        _fingerprint_record(digest, "verification_runs", dict(row))
        for attempt in conn.execute(
            """
            SELECT * FROM verification_attempts
            WHERE run_id=? ORDER BY created_at ASC, attempt_id ASC
            """,
            (row["run_id"],),
        ):
            _fingerprint_record(digest, "verification_attempts", dict(attempt))
        for exception in conn.execute(
            """
            SELECT * FROM verification_exceptions
            WHERE run_id=? ORDER BY exception_id ASC
            """,
            (row["run_id"],),
        ):
            _fingerprint_record(digest, "verification_exceptions", dict(exception))
    return digest.hexdigest()


def _canonical_chain_token_matches(
    conn: sqlite3.Connection,
    token: _CanonicalVerificationChainToken | None,
    request: Mapping[str, object],
) -> bool:
    return bool(
        token is not None
        and token.repository == request.get("repository")
        and token.pr_number == request.get("pr_number")
        and token.stage == request.get("stage")
        and token.linked_issue == request.get("linked_issue")
        and token.fingerprint == _canonical_chain_fingerprint(conn, request)
    )


def _live_takeover_authority_matches(
    observation: _LiveVerificationObservation | None,
    request: Mapping[str, object],
    candidate_request: Mapping[str, object],
    candidate_supporting: Sequence[int],
) -> bool:
    """Require exact live head and cumulative contract truth for head takeover."""

    incoming_supporting = request.get("supporting_issues")
    incoming_closing = _request_closing_authority(request)
    candidate_closing = _request_closing_authority(candidate_request)
    return bool(
        observation is not None
        and observation.state == "open"
        and observation.merged_at is None
        and not observation.draft
        and observation.repository == request.get("repository")
        and observation.pr_number == request.get("pr_number")
        and observation.head_sha == request.get("current_head_sha")
        and observation.linked_issue == request.get("linked_issue")
        and observation.linked_issue == candidate_request.get("linked_issue")
        and isinstance(incoming_supporting, list)
        and set(candidate_supporting).issubset(incoming_supporting)
        and set(incoming_supporting).issubset(observation.supporting_issues)
        and set(candidate_supporting).issubset(observation.supporting_issues)
        and set(incoming_closing) == set(candidate_closing)
        and set(incoming_closing) == set(observation.closing_issues)
    )


def _current_head_replay_authority_matches(
    observation: _LiveVerificationObservation | None,
    request: Mapping[str, object],
    candidate_request: Mapping[str, object],
    candidate_supporting: Sequence[int],
) -> bool:
    """Require exact durable and live authority for current-head replay."""

    incoming_supporting = request.get("supporting_issues")
    incoming_closing = _request_closing_authority(request)
    candidate_closing = _request_closing_authority(candidate_request)
    return bool(
        observation is not None
        and observation.repository == request.get("repository")
        and observation.pr_number == request.get("pr_number")
        and observation.head_sha == request.get("current_head_sha")
        and observation.linked_issue == request.get("linked_issue")
        and observation.linked_issue == candidate_request.get("linked_issue")
        and isinstance(incoming_supporting, list)
        and set(incoming_supporting) == set(candidate_supporting)
        and set(observation.supporting_issues) == set(candidate_supporting)
        and set(incoming_closing) == set(candidate_closing)
        and set(incoming_closing) == set(observation.closing_issues)
    )


def _same_head_legacy_recovery_authority_matches(
    observation: _LiveVerificationObservation | None,
    request: Mapping[str, object],
    legacy_request: Mapping[str, object],
    legacy_current_head: str,
) -> bool:
    """Require fresh exact live authority before promoting one inert v1 row."""
    incoming_supporting = request.get("supporting_issues")
    legacy_supporting = legacy_request.get("supporting_issues")
    incoming_closing = _request_closing_authority(request)
    return bool(
        observation is not None
        and observation.state == "open"
        and observation.merged_at is None
        and not observation.draft
        and observation.repository == request.get("repository")
        and observation.pr_number == request.get("pr_number")
        and observation.head_sha == request.get("current_head_sha")
        and observation.linked_issue == request.get("linked_issue")
        and legacy_request.get("repository") == request.get("repository")
        and legacy_request.get("pr_number") == request.get("pr_number")
        and legacy_current_head == request.get("current_head_sha")
        and legacy_request.get("stage") == request.get("stage")
        and legacy_request.get("linked_issue") == request.get("linked_issue")
        and isinstance(incoming_supporting, list)
        # Deployed v1 did not authenticate an exact closing set, but it did
        # persist its supporting issue contract. Reusing its attempts and
        # repair budget is safe only when that authority is unchanged. Older
        # v1 shapes without a supporting set remain inert because compatibility
        # cannot be proved.
        and isinstance(legacy_supporting, list)
        and set(incoming_supporting) == set(legacy_supporting)
        and set(incoming_supporting).issubset(observation.supporting_issues)
        and set(incoming_closing).issubset(
            {request.get("linked_issue"), *legacy_supporting}
        )
        and set(incoming_closing) == set(observation.closing_issues)
    )


def _recover_same_head_legacy_run(
    conn: sqlite3.Connection,
    row: sqlite3.Row,
    request: Mapping[str, object],
    observation: _LiveVerificationObservation | None,
    token: _CanonicalVerificationChainToken | None,
    *,
    now: str,
) -> sqlite3.Row:
    """Atomically archive inert v1 authority and activate authenticated v2."""
    legacy_request = _validated_legacy_row_request(row)
    legacy_current_head = validated_legacy_current_head(row)
    if not _canonical_chain_token_matches(conn, token, request):
        raise ValueError(
            "verification canonical authority changed during live observation"
        )
    if not _same_head_legacy_recovery_authority_matches(
        observation, request, legacy_request, legacy_current_head
    ):
        raise ValueError(
            "authenticated v2 artifact does not match legacy recovery authority"
        )
    incoming_supporting = request.get("supporting_issues")
    assert isinstance(incoming_supporting, list)
    legacy_recovery_audit = _legacy_recovery_audit_snapshot(conn, row)
    conn.execute(
        """
        UPDATE verification_runs
        SET idempotency_key=?, contract_version=?, request_json=?,
            supporting_authority_json=?, closing_authority_json=?,
            legacy_recovery_audit_json=?, status='queued',
            current_head_sha=?, verified_head_sha=NULL,
            claimed_by=NULL, lease_id=NULL, lease_expires_at=NULL,
            last_heartbeat_at=NULL, coordinator_session_id=NULL,
            context_pack_json=NULL, terminal_receipt_json=NULL,
            stop_reason=NULL, retry_after=NULL, updated_at=?
        WHERE run_id=? AND idempotency_key=? AND status=?
          AND legacy_recovery_audit_json IS NULL
        """,
        (
            request["idempotency_key"],
            request["contract_version"],
            _json(request),
            _json(incoming_supporting),
            _json(_request_closing_authority(request)),
            legacy_recovery_audit,
            request["current_head_sha"],
            now,
            row["run_id"],
            row["idempotency_key"],
            LEGACY_UNTRUSTED_VERIFICATION_STATUS,
        ),
    )
    if conn.execute("SELECT changes()").fetchone()[0] != 1:
        raise ValueError(
            "verification canonical run authority changed during legacy recovery"
        )
    conn.execute(
        "DELETE FROM verification_exceptions WHERE run_id=?", (row["run_id"],)
    )
    recovered = conn.execute(
        "SELECT * FROM verification_runs WHERE run_id=?", (row["run_id"],)
    ).fetchone()
    assert recovered is not None
    _validated_row_request(recovered)
    return recovered


def _validated_mutation_row(
    conn: sqlite3.Connection, run_id: str
) -> sqlite3.Row | None:
    """Read and validate durable run authority before any transaction mutation."""
    row = conn.execute(
        "SELECT * FROM verification_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    if row is not None:
        if row["status"] == LEGACY_UNTRUSTED_VERIFICATION_STATUS:
            _validated_legacy_row_request(row)
            raise ValueError("legacy verification audit is not executable")
        _validated_row_request(row)
    return row


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
    authority_state: str
    claimed_by: str | None
    lease_id: str | None
    lease_expires_at: str | None
    coordinator_session_id: str | None
    request: dict[str, object]
    supporting_authority: tuple[int, ...]
    closing_authority: tuple[int, ...]
    repair_budget_policy: str
    context_pack: dict[str, object] | None
    terminal_receipt: dict[str, object] | None
    stop_reason: str | None
    retry_after: str | None

    @property
    def head_sha(self) -> str:
        """Compatibility name for the lease-fenced current PR head."""
        return self.current_head_sha


def _run(row: sqlite3.Row) -> VerificationRun:
    is_legacy = row["status"] == LEGACY_UNTRUSTED_VERIFICATION_STATUS
    request = (
        _validated_legacy_row_request(row)
        if is_legacy
        else _validated_row_request(row)
    )
    supporting_authority = (
        [] if is_legacy else _validated_supporting_authority(row, request)
    )
    closing_authority = (
        [] if is_legacy else _validated_closing_authority(row, request)
    )
    repair_budget_policy = row["repair_budget_policy"]
    if repair_budget_policy not in {
        REPAIR_BUDGET_POLICY_LEGACY,
        REPAIR_BUDGET_POLICY_MECHANISM,
    }:
        raise ValueError("invalid verification repair budget policy")
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
        authority_state=(
            LEGACY_UNTRUSTED_VERIFICATION_STATUS if is_legacy else "canonical"
        ),
        claimed_by=row["claimed_by"],
        lease_id=row["lease_id"],
        lease_expires_at=row["lease_expires_at"],
        coordinator_session_id=row["coordinator_session_id"],
        request=request,
        supporting_authority=tuple(supporting_authority),
        closing_authority=tuple(closing_authority),
        repair_budget_policy=repair_budget_policy,
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
        "finding_id": row["finding_id"],
        "failure_domain": row["failure_domain"],
        "mechanism_id": row["mechanism_id"],
        "receipt": _load(row["receipt_json"]),
    }


def _validated_attempt_identity(
    attempts: Sequence[Mapping[str, object]],
    *,
    kind: str,
    outcome: str,
    receipt: Mapping[str, object] | None,
    policy: str,
) -> tuple[str | None, str | None, str | None]:
    if policy not in {REPAIR_BUDGET_POLICY_LEGACY, REPAIR_BUDGET_POLICY_MECHANISM}:
        raise ValueError("invalid verification repair budget policy")
    if kind not in {*REPAIR_ATTEMPT_LIMITS, "review"}:
        return None, None, None

    # Runs migrated from v3 retain the original global v1 accounting model.
    # Their historical receipts may carry a finding without the domain and
    # mechanism fields introduced by v2, so identity must remain unbound.
    if policy == REPAIR_BUDGET_POLICY_LEGACY:
        return None, None, None

    finding = receipt.get("finding_id") if receipt is not None else None
    domain = receipt.get("failure_domain") if receipt is not None else None
    mechanism = receipt.get("mechanism_id") if receipt is not None else None
    identity = (finding, domain, mechanism)
    identity_present = any(value is not None for value in identity)
    requires_identity = kind in REPAIR_ATTEMPT_LIMITS or (
        kind == "review" and outcome == "blocking"
    )
    if policy == REPAIR_BUDGET_POLICY_MECHANISM and requires_identity and not all(
        isinstance(value, str) and bool(value) for value in identity
    ):
        raise ValueError(
            "repair and blocking review require a stable finding, failure domain, "
            "and mechanism binding"
        )
    if not identity_present:
        return None, None, None
    if not all(isinstance(value, str) and bool(value) for value in identity):
        raise ValueError("verification finding binding is incomplete")
    assert isinstance(finding, str)
    assert isinstance(domain, str)
    assert isinstance(mechanism, str)
    if domain not in REPAIR_FAILURE_DOMAINS:
        raise ValueError("invalid verification failure domain")
    if _STABLE_MECHANISM_ID.fullmatch(mechanism) is None:
        raise ValueError("invalid stable verification mechanism id")
    for attempt in attempts:
        if attempt.get("finding_id") != finding:
            continue
        if (
            attempt.get("failure_domain") != domain
            or attempt.get("mechanism_id") != mechanism
        ):
            raise ValueError("verification finding binding cannot be changed")
    return finding, domain, mechanism


def _attempt_plan(
    attempts: Sequence[Mapping[str, object]],
    *,
    kind: str,
    outcome: str,
    receipt: Mapping[str, object] | None,
    policy: str,
) -> tuple[int, str | None, str | None, str | None]:
    finding, domain, mechanism = _validated_attempt_identity(
        attempts,
        kind=kind,
        outcome=outcome,
        receipt=receipt,
        policy=policy,
    )
    ordinal = sum(row.get("kind") == kind for row in attempts) + 1
    if kind not in REPAIR_ATTEMPT_LIMITS:
        return ordinal, finding, domain, mechanism
    if policy == REPAIR_BUDGET_POLICY_LEGACY:
        keyed = [row for row in attempts if row.get("kind") == kind]
        standard = [
            row for row in attempts if row.get("kind") == "standard_repair"
        ]
    else:
        keyed = [
            row
            for row in attempts
            if row.get("kind") == kind
            and row.get("failure_domain") == domain
            and row.get("mechanism_id") == mechanism
        ]
        standard = [
            row
            for row in attempts
            if row.get("kind") == "standard_repair"
            and row.get("failure_domain") == domain
            and row.get("mechanism_id") == mechanism
        ]
    if len(keyed) >= REPAIR_ATTEMPT_LIMITS[kind]:
        raise ValueError(f"{kind} budget exhausted")
    if kind == "escalated_repair" and len(standard) < 2:
        raise ValueError(
            "strongest capability is only allowed after two standard attempts "
            "for the same failure mechanism"
        )
    return ordinal, finding, domain, mechanism


def _projected_mechanism_id(mechanism_id: str) -> str:
    if re.fullmatch(r"mechanism-[0-9a-f]{16}", mechanism_id):
        return mechanism_id
    digest = hashlib.sha256(mechanism_id.encode()).hexdigest()[:16]
    return f"mechanism-{digest}"


class VerificationDispatchLedger:
    """Atomic, idempotent lifecycle for PR/head verification chains."""

    def __init__(self, store: SqliteStore) -> None:
        self.store = store
        self.store.initialize()

    def canonical_chain_token(
        self, request: Mapping[str, object]
    ) -> _CanonicalVerificationChainToken:
        """Capture an optimistic canonical-chain token before external observation."""

        if not isinstance(request, _AuthenticatedVerificationRequest):
            raise ValueError(
                "verification canonical chain observation requires authenticated artifact"
            )
        projected = _canonical_request_projection(request)
        _validate_request(projected)
        with self.store._connect() as conn:
            conn.execute("BEGIN")
            fingerprint = _canonical_chain_fingerprint(conn, projected)
            conn.commit()
        repository = projected["repository"]
        pr_number = projected["pr_number"]
        stage = projected["stage"]
        linked_issue = projected["linked_issue"]
        assert isinstance(repository, str)
        assert _positive_int(pr_number)
        assert isinstance(stage, str)
        assert _positive_int(linked_issue)
        return _CanonicalVerificationChainToken(
            repository=repository,
            pr_number=pr_number,
            stage=stage,
            linked_issue=linked_issue,
            fingerprint=fingerprint,
        )

    def ingest(self, request: Mapping[str, object]) -> VerificationRun:
        authenticated_artifact = isinstance(request, _AuthenticatedVerificationRequest)
        live_observation = (
            request.live_observation
            if isinstance(request, _LiveObservedVerificationRequest)
            else None
        )
        canonical_chain_token = (
            request.canonical_chain_token
            if isinstance(request, _LiveObservedVerificationRequest)
            else None
        )
        request = _canonical_request_projection(request)
        _validate_request(request)
        now = _now()
        run_id = f"vrun-{str(request['idempotency_key'])[:16]}"
        with self.store._connect() as conn:
            now = _begin_immediate_now(conn)
            inert_audits = list(conn.execute(
                """
                SELECT * FROM verification_runs
                WHERE repository=? AND pr_number=? AND stage=? AND status=?
                ORDER BY created_at ASC, run_id ASC
                """,
                (
                    request["repository"],
                    request["pr_number"],
                    request["stage"],
                    LEGACY_UNTRUSTED_VERIFICATION_STATUS,
                ),
            ))
            if inert_audits and not authenticated_artifact:
                raise ValueError(
                    "legacy verification audit requires an authenticated artifact"
                )
            inert_same_head = [
                row
                for row in inert_audits
                if row["current_head_sha"] == request["current_head_sha"]
            ]
            recoverable_inert = [
                row
                for row in inert_audits
                if recognized_ambiguous_v1_closure_request(
                    row, _validated_legacy_row_request(row)
                )
            ]
            if recoverable_inert and not inert_same_head:
                raise ValueError(
                    "verification artifact head does not match legacy current run"
                )
            if inert_same_head:
                if len(inert_audits) != 1 or len(inert_same_head) != 1:
                    raise ValueError(
                        "verification legacy recovery authority is ambiguous"
                    )
                other_chain = conn.execute(
                    """
                    SELECT 1 FROM verification_runs
                    WHERE repository=? AND pr_number=? AND stage=? AND status<>?
                    LIMIT 1
                    """,
                    (
                        request["repository"],
                        request["pr_number"],
                        request["stage"],
                        LEGACY_UNTRUSTED_VERIFICATION_STATUS,
                    ),
                ).fetchone()
                if other_chain is not None:
                    raise ValueError(
                        "verification legacy recovery authority is ambiguous"
                    )
                recovered = _recover_same_head_legacy_run(
                    conn,
                    inert_same_head[0],
                    request,
                    live_observation,
                    canonical_chain_token,
                    now=now,
                )
                conn.commit()
                return _run(recovered)
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
                # The stable idempotency identity intentionally omits closure authority,
                # so replay must compare the incoming set with the durable canonical set.
                stored_closing = _validated_closing_authority(
                    existing, existing_request
                )
                incoming_closing = _request_closing_authority(request)
                stored_supporting = _validated_supporting_authority(
                    existing, existing_request
                )
                incoming_supporting = request.get("supporting_issues")
                if (
                    not isinstance(incoming_supporting, list)
                    or set(incoming_supporting) != set(stored_supporting)
                    or set(incoming_closing) != set(stored_closing)
                ):
                    raise ValueError("verification idempotency authority conflict")
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
                    or existing_request["current_head_sha"]
                    != request["current_head_sha"]
                ):
                    raise ValueError("verification idempotency authority conflict")
                if existing_request.get("linked_issue") != request.get("linked_issue"):
                    if active_status:
                        raise ValueError(
                            "verification canonical run governing issue mismatch"
                        )
                    raise ValueError("verification idempotency authority conflict")
                if existing["current_head_sha"] != request.get("current_head_sha"):
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
                    retry_after = candidate["retry_after"]
                    candidate_supporting = _validated_supporting_authority(
                        candidate, candidate_request
                    )
                    incoming_supporting = request.get("supporting_issues")
                    if live_observation is not None and not _canonical_chain_token_matches(
                        conn, canonical_chain_token, request
                    ):
                        raise ValueError(
                            "verification canonical authority changed during live observation"
                        )
                    expired_running = (
                        candidate["status"] == "running"
                        and isinstance(lease_expires_at, str)
                        and _parse_timestamp(lease_expires_at)
                        <= _parse_timestamp(now)
                    )
                    expired_backoff = (
                        candidate["status"] == "backoff"
                        and isinstance(retry_after, str)
                        and _parse_timestamp(retry_after) <= _parse_timestamp(now)
                    )
                    authority_matches = (
                        _live_takeover_authority_matches(
                            live_observation,
                            request,
                            candidate_request,
                            candidate_supporting,
                        )
                        and (expired_running or expired_backoff)
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
                            supporting_authority_json=?,
                            claimed_by=NULL, lease_id=NULL, lease_expires_at=NULL,
                            last_heartbeat_at=NULL, coordinator_session_id=NULL,
                            context_pack_json=NULL, terminal_receipt_json=NULL,
                            stop_reason=NULL, retry_after=NULL, updated_at=?
                        WHERE run_id=? AND current_head_sha=? AND (
                            (status='running' AND lease_expires_at=?) OR
                            (status='backoff' AND retry_after=?)
                        )
                        """,
                        (
                            next_head,
                            _json(incoming_supporting),
                            now,
                            candidate["run_id"],
                            candidate["current_head_sha"],
                            lease_expires_at,
                            retry_after,
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
                candidate_supporting = _validated_supporting_authority(
                    candidate, candidate_request
                )
                candidate_closing = _validated_closing_authority(
                    candidate, candidate_request
                )
                incoming_supporting = request.get("supporting_issues")
                incoming_closing = _request_closing_authority(request)
                if (
                    not isinstance(incoming_supporting, list)
                    or set(incoming_supporting) != set(candidate_supporting)
                    or set(incoming_closing) != set(candidate_closing)
                ):
                    raise ValueError(
                        "verification active replay authority does not match canonical run"
                    )
                if live_observation is not None:
                    if not _canonical_chain_token_matches(
                        conn, canonical_chain_token, request
                    ):
                        raise ValueError(
                            "verification canonical authority changed during live observation"
                        )
                    if not _current_head_replay_authority_matches(
                        live_observation,
                        request,
                        candidate_request,
                        candidate_supporting,
                    ):
                        raise ValueError(
                            "verification active replay authority does not match canonical run"
                        )
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
            if len(terminal_candidates) == 1:
                candidate = terminal_candidates[0]
                if candidate["current_head_sha"] == request.get("current_head_sha"):
                    candidate_request = _validated_row_request(candidate)
                    candidate_supporting = _validated_supporting_authority(
                        candidate, candidate_request
                    )
                    if not _canonical_chain_token_matches(
                        conn, canonical_chain_token, request
                    ):
                        raise ValueError(
                            "verification canonical authority changed during live observation"
                        )
                    if not _current_head_replay_authority_matches(
                        live_observation,
                        request,
                        candidate_request,
                        candidate_supporting,
                    ):
                        raise ValueError(
                            "verification terminal replay authority does not match canonical run"
                        )
                    conn.commit()
                    return _run(candidate)
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
                candidate_request = _validated_row_request(candidate)
                candidate_supporting = _validated_supporting_authority(
                    candidate, candidate_request
                )
                if live_observation is not None and not _canonical_chain_token_matches(
                    conn, canonical_chain_token, request
                ):
                    raise ValueError(
                        "verification canonical authority changed during live observation"
                    )
                if not _live_takeover_authority_matches(
                    live_observation,
                    request,
                    candidate_request,
                    candidate_supporting,
                ):
                    raise ValueError(
                        "verification artifact head does not match canonical run"
                    )
                incoming_supporting = request.get("supporting_issues")
                assert isinstance(incoming_supporting, list)
                conn.execute(
                    """
                    UPDATE verification_runs
                    SET status='queued', current_head_sha=?, verified_head_sha=NULL,
                        supporting_authority_json=?,
                        claimed_by=NULL, lease_id=NULL, lease_expires_at=NULL,
                        last_heartbeat_at=NULL, coordinator_session_id=NULL,
                        context_pack_json=NULL, terminal_receipt_json=NULL,
                        stop_reason=NULL, retry_after=NULL, updated_at=?
                    WHERE run_id=? AND status='superseded'
                      AND stop_reason='stale_head'
                    """,
                    (
                        next_head,
                        _json(incoming_supporting),
                        now,
                        candidate["run_id"],
                    ),
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
                    pr_number, head_sha, current_head_sha, stage, request_json,
                    supporting_authority_json, closing_authority_json,
                    repair_budget_policy, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?)
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
                    _json(request["supporting_issues"]),
                    _json(_request_closing_authority(request)),
                    REPAIR_BUDGET_POLICY_MECHANISM,
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
            row = _validated_mutation_row(conn, run_id)
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
            row = _validated_mutation_row(conn, run_id)
            if row is None:
                raise ValueError("verification heartbeat ownership mismatch")
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
            row = _validated_mutation_row(conn, run_id)
            if row is None:
                raise ValueError("verification start ownership mismatch")
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
            owner = _validated_mutation_row(conn, run_id)
            if (
                owner is None
                or owner["claimed_by"] != holder
                or owner["lease_id"] != lease_id
                or owner["status"] not in ACTIVE_STATES
                or owner["lease_expires_at"] is None
                or owner["lease_expires_at"] <= now
            ):
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
            row = _validated_mutation_row(conn, run_id)
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
            row = _validated_mutation_row(conn, run_id)
            if row is None:
                raise ValueError("verification backoff ownership mismatch")
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
        with self.store._connect() as conn:
            now = _begin_immediate_now(conn)
            row = _validated_mutation_row(conn, run_id)
            if row is None:
                raise ValueError("verification run is not unclaimed and deferrable")
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
        with self.store._connect() as conn:
            now = _begin_immediate_now(conn)
            row = _validated_mutation_row(conn, run_id)
            if row is None:
                raise ValueError("verification run is not unclaimed and supersedable")
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
        allowed = {*REPAIR_ATTEMPT_LIMITS, "review", "verification"}
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
            owner = _validated_mutation_row(conn, run_id)
            if (
                owner is None
                or owner["claimed_by"] != holder
                or owner["lease_id"] != lease_id
                or owner["status"] not in ACTIVE_STATES
                or owner["lease_expires_at"] is None
                or owner["lease_expires_at"] <= now
            ):
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
            attempts = self._attempts(conn, run_id)
            ordinal, finding_id, failure_domain, mechanism_id = _attempt_plan(
                attempts,
                kind=kind,
                outcome=outcome,
                receipt=receipt,
                policy=owner["repair_budget_policy"],
            )
            conn.execute(
                """
                INSERT INTO verification_attempts (
                    attempt_id, run_id, attempt_kind, ordinal, session_id,
                    capability, reasoning_effort, context_hash, outcome,
                    finding_id, failure_domain, mechanism_id, receipt_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id, run_id, kind, ordinal,
                    session_id, capability, reasoning_effort, context_hash, outcome,
                    finding_id, failure_domain, mechanism_id,
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
            owner = _validated_mutation_row(conn, run_id)
            if (
                owner is None
                or owner["claimed_by"] != holder
                or owner["lease_id"] != lease_id
                or owner["status"] not in ACTIVE_STATES
                or owner["lease_expires_at"] is None
                or owner["lease_expires_at"] <= now
            ):
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
            working = list(attempts)
            validated: builtins.list[dict[str, object]] = []
            for item in planned:
                item_receipt = item["receipt"]
                if not isinstance(item_receipt, Mapping):
                    raise ValueError("verification event batch receipt is malformed")
                ordinal, finding_id, failure_domain, mechanism_id = _attempt_plan(
                    working,
                    kind=str(item["kind"]),
                    outcome=str(item["outcome"]),
                    receipt=item_receipt,
                    policy=owner["repair_budget_policy"],
                )
                if item.get("ordinal") != ordinal:
                    raise ValueError("verification event batch ordinal is malformed")
                projected = dict(item)
                projected.update(
                    {
                        "finding_id": finding_id,
                        "failure_domain": failure_domain,
                        "mechanism_id": mechanism_id,
                    }
                )
                working.append(projected)
                validated.append(projected)
            batch_started = datetime.now(timezone.utc)
            for index, item in enumerate(validated):
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
                        finding_id, failure_domain, mechanism_id,
                        receipt_json, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        item["finding_id"],
                        item["failure_domain"],
                        item["mechanism_id"],
                        _json(receipt),
                        (batch_started + timedelta(microseconds=index)).isoformat(
                            timespec="microseconds"
                        ),
                    ),
                )
            conn.commit()
        return len(validated)

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

    def repair_budget_projection(self, run_id: str) -> dict[str, object]:
        """Return a bounded coordinator-safe view without finding identities."""
        with self.store._connect() as conn:
            run = conn.execute(
                "SELECT repair_budget_policy FROM verification_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise ValueError("verification run not found")
            policy = str(run["repair_budget_policy"])
            attempts = self._attempts(conn, run_id)
        if policy == REPAIR_BUDGET_POLICY_LEGACY:
            standard = sum(
                row["kind"] == "standard_repair" for row in attempts
            )
            escalated = sum(
                row["kind"] == "escalated_repair" for row in attempts
            )
            return {
                "policy_version": policy,
                "mechanism_count": 1,
                "truncated": False,
                "omitted_count": 0,
                "mechanisms": [
                    {
                        "failure_domain": "legacy_global",
                        "mechanism_id": "legacy-global",
                        "standard_used": standard,
                        "standard_remaining": max(0, 2 - standard),
                        "escalated_used": escalated,
                        "escalated_remaining": max(0, 2 - escalated),
                    }
                ],
            }
        if policy != REPAIR_BUDGET_POLICY_MECHANISM:
            raise ValueError("invalid verification repair budget policy")
        last_seen: dict[tuple[str, str], int] = {}
        for index, row in enumerate(attempts):
            if (
                row["kind"] in REPAIR_ATTEMPT_LIMITS
                and isinstance(row["failure_domain"], str)
                and isinstance(row["mechanism_id"], str)
            ):
                last_seen[(row["failure_domain"], row["mechanism_id"])] = index
        ordered_keys = sorted(
            last_seen,
            key=lambda key: (-last_seen[key], key),
        )
        mechanism_count = len(ordered_keys)
        keys = ordered_keys[:32]
        mechanisms: builtins.list[dict[str, object]] = []
        for domain, mechanism in keys:
            standard = sum(
                row["kind"] == "standard_repair"
                and row["failure_domain"] == domain
                and row["mechanism_id"] == mechanism
                for row in attempts
            )
            escalated = sum(
                row["kind"] == "escalated_repair"
                and row["failure_domain"] == domain
                and row["mechanism_id"] == mechanism
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
        omitted_count = mechanism_count - len(mechanisms)
        return {
            "policy_version": policy,
            "mechanism_count": mechanism_count,
            "truncated": omitted_count > 0,
            "omitted_count": omitted_count,
            "mechanisms": mechanisms,
        }

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
                "SELECT * FROM verification_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                return False
            if row["status"] == LEGACY_UNTRUSTED_VERIFICATION_STATUS:
                _validated_legacy_row_request(row)
                return False
            _validated_row_request(row)
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
            owner = _validated_mutation_row(conn, run_id)
            if (
                owner is None
                or owner["claimed_by"] != holder
                or owner["lease_id"] != lease_id
                or owner["status"] not in ACTIVE_STATES
                or owner["lease_expires_at"] is None
                or owner["lease_expires_at"] <= now
            ):
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
