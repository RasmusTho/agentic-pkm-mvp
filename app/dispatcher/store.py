"""SQLite-backed dispatcher store.

The store is intentionally narrow: persist task, lease, and event rows behind
an interface so a Postgres implementation can replace it later without
rewriting callers. Queue selection and claim lifecycle are out of scope for the
foundation slice.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Protocol

from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.models import EventRecord, LeaseRecord, TaskRecord
from app.dispatcher.schema import (
    DDL_STATEMENTS,
    LEGACY_UNTRUSTED_VERIFICATION_STATUS,
    SCHEMA_VERSION,
    verification_v3_schema_error,
    verification_v4_schema_error,
    verification_v5_schema_error,
    verification_v6_schema_error,
)


class DispatcherStore(Protocol):
    def initialize(self) -> None: ...
    def upsert_task(self, task: TaskRecord) -> None: ...
    def get_task(self, task_id: str) -> TaskRecord | None: ...
    def upsert_lease(self, lease: LeaseRecord) -> None: ...
    def get_lease(self, lease_id: str) -> LeaseRecord | None: ...
    def append_event(self, event: EventRecord) -> None: ...
    def list_tasks(
        self, status: str | None = None, repo: str | None = None
    ) -> list[TaskRecord]: ...
    def list_events(self, task_id: str | None = None) -> list[EventRecord]: ...
    def get_meta(self, key: str) -> str | None: ...
    def set_meta(self, key: str, value: str) -> None: ...


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _loads(value: str | None) -> Any:
    if value is None or value == "":
        return None
    return json.loads(value)


_PRE_TRUST_REQUEST_FIELDS = frozenset(
    {
        "base_ref",
        "contract_version",
        "current_head_sha",
        "evidence_pack",
        "generated_at",
        "head_ref",
        "idempotency_key",
        "linked_issue",
        "live_truth",
        "pr_number",
        "repository",
        "source_workflow",
        "stage",
    }
)
_PRE_TRUST_NESTED_FIELDS = {
    "source_workflow": frozenset({"name", "run_id", "run_attempt", "head_sha"}),
    "evidence_pack": frozenset(
        {
            "contract",
            "workflow_name",
            "artifact_name",
            "repository",
            "pr_number",
            "head_sha",
        }
    ),
    "live_truth": frozenset(
        {"repository", "pr_number", "current_head_sha", "source_run_id"}
    ),
}
# The b4e2310 producer bound verification artifacts to GitHub provenance,
# adding exactly one top-level field (``artifact_provenance``) to the pre-trust
# shape and no ``supporting_issues``. Its provenance object is descriptive audit
# metadata only and is never authoritative for execution.
_PRE_TRUST_ARTIFACT_PROVENANCE_FIELDS = _PRE_TRUST_REQUEST_FIELDS | {
    "artifact_provenance"
}
_PRE_TRUST_ARTIFACT_PROVENANCE_NESTED = frozenset(
    {"workflow_run_id", "repository_id", "artifact_name"}
)
_CANONICAL_VERIFICATION_STATUSES = frozenset(
    {
        "queued",
        "backoff",
        "claimed",
        "running",
        "completed",
        "failed",
        "needs_human",
        "superseded",
    }
)


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def recognized_pre_trust_verification_request(
    row: Mapping[str, Any] | sqlite3.Row,
    request: Mapping[str, object],
) -> bool:
    """Recognize the exact request contracts deployed before trust closure.

    Two historical producer shapes are recognized: the original pre-trust shape
    (no ``artifact_provenance``) and the b4e2310 shape, which added exactly one
    top-level field, ``artifact_provenance``, and still predates
    ``supporting_issues``. Both are audit evidence only. Recognition never
    upgrades them to the current closed request contract; it only permits an
    atomic migration to a permanently inert ledger state. The recognizer stays
    exact-shape and fail-closed: any other field set, extra key, or malformed
    provenance object is rejected.
    """
    fields = set(request)
    if fields == _PRE_TRUST_REQUEST_FIELDS:
        has_artifact_provenance = False
    elif fields == _PRE_TRUST_ARTIFACT_PROVENANCE_FIELDS:
        has_artifact_provenance = True
    else:
        return False
    if row["request_json"] != json.dumps(
        request,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ):
        return False
    nested: dict[str, Mapping[str, object]] = {}
    for field, fields_set in _PRE_TRUST_NESTED_FIELDS.items():
        value = request.get(field)
        if not isinstance(value, Mapping) or set(value) != fields_set:
            return False
        nested[field] = value
    if has_artifact_provenance:
        provenance = request.get("artifact_provenance")
        if (
            not isinstance(provenance, Mapping)
            or set(provenance) != _PRE_TRUST_ARTIFACT_PROVENANCE_NESTED
        ):
            return False
        nested["artifact_provenance"] = provenance

    repository = request.get("repository")
    pr_number = request.get("pr_number")
    linked_issue = request.get("linked_issue")
    head_sha = request.get("current_head_sha")
    idempotency_key = request.get("idempotency_key")
    if (
        request.get("contract_version") != "verification_dispatch_request.v1"
        or request.get("stage") != "verification"
        or not isinstance(repository, str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository)
        or any(part in {".", ".."} for part in repository.split("/"))
        or not _positive_int(pr_number)
        or not _positive_int(linked_issue)
        or not isinstance(head_sha, str)
        or not re.fullmatch(r"[0-9a-fA-F]{40}", head_sha)
        or not isinstance(idempotency_key, str)
        or not re.fullmatch(r"[0-9a-f]{64}", idempotency_key)
        or any(
            not isinstance(request.get(field), str) or not request[field]
            for field in ("base_ref", "head_ref", "generated_at")
        )
    ):
        return False

    identity = {
        "contract_version": "verification_dispatch_request.v1",
        "head_sha": head_sha,
        "pr_number": pr_number,
        "repository": repository,
        "stage": "verification",
    }
    expected_idempotency = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    source = nested["source_workflow"]
    evidence = nested["evidence_pack"]
    live_truth = nested["live_truth"]
    artifact_provenance_ok = not has_artifact_provenance or bool(
        _positive_int(nested["artifact_provenance"].get("workflow_run_id"))
        and _positive_int(nested["artifact_provenance"].get("repository_id"))
        and nested["artifact_provenance"].get("artifact_name")
        == f"verification-dispatch-{pr_number}-{head_sha}"
    )
    return bool(
        artifact_provenance_ok
        and idempotency_key == expected_idempotency
        and row["run_id"] == f"vrun-{idempotency_key[:16]}"
        and row["idempotency_key"] == idempotency_key
        and row["contract_version"] == request["contract_version"]
        and row["repository"] == repository
        and row["pr_number"] == pr_number
        and row["head_sha"] == head_sha
        and row["stage"] == request["stage"]
        and source.get("name") == "CI"
        and _positive_int(source.get("run_id"))
        and _positive_int(source.get("run_attempt"))
        and source.get("head_sha") == head_sha
        and evidence.get("contract") == "pr_evidence_pack"
        and evidence.get("workflow_name") == "PR Evidence Pack"
        and evidence.get("artifact_name") == f"pr-evidence-pack-{pr_number}"
        and evidence.get("repository") == repository
        and evidence.get("pr_number") == pr_number
        and evidence.get("head_sha") == head_sha
        and live_truth.get("repository") == repository
        and live_truth.get("pr_number") == pr_number
        and live_truth.get("current_head_sha") == head_sha
        and live_truth.get("source_run_id") == source.get("run_id")
    )


def _verification_authority_migration(
    row: sqlite3.Row,
) -> tuple[str, bool]:
    """Return the durable authority projection and whether the row is inert."""
    try:
        request = json.loads(row["request_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("verification request audit is malformed") from exc
    supporting = request.get("supporting_issues") if isinstance(request, dict) else None
    if (
        not isinstance(supporting, list)
        or any(
            isinstance(issue, bool) or not isinstance(issue, int) or issue <= 0
            for issue in supporting
        )
        or len(set(supporting)) != len(supporting)
    ):
        if isinstance(request, Mapping) and recognized_pre_trust_verification_request(
            row, request
        ):
            return "[]", True
        raise ValueError("verification supporting authority is malformed")
    if isinstance(request, Mapping) and recognized_ambiguous_v1_closure_request(
        row, request
    ):
        return "[]", True
    return (
        json.dumps(supporting, separators=(",", ":"), ensure_ascii=False),
        False,
    )


def recognized_ambiguous_v1_closure_request(
    row: Mapping[str, Any] | sqlite3.Row,
    request: Mapping[str, object],
) -> bool:
    """Recognize a canonical v1 request whose exact closure is unknowable."""
    supporting = request.get("supporting_issues")
    if (
        request.get("contract_version") != "verification_dispatch_request.v1"
        or not isinstance(supporting, list)
    ):
        return False
    try:
        from app.dispatcher.verification_dispatch import (
            _canonical_request_projection,
            _validate_request,
        )

        projected = _canonical_request_projection(request)
        _validate_request(projected, allow_legacy_audit=True)
    except (KeyError, TypeError, ValueError):
        return False
    idempotency_key = request.get("idempotency_key")
    if not isinstance(idempotency_key, str):
        return False
    return bool(
        row["request_json"]
        == json.dumps(
            projected,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        and row["run_id"] == f"vrun-{idempotency_key[:16]}"
        and row["idempotency_key"] == idempotency_key
        and row["contract_version"] == request["contract_version"]
        and row["repository"] == request["repository"]
        and row["pr_number"] == request["pr_number"]
        and row["head_sha"] == request["current_head_sha"]
        and row["stage"] == request["stage"]
    )


def _verification_closing_authority_migration(row: sqlite3.Row) -> str:
    """Backfill v1 conservatively; preserve exact v2 closure authority."""
    try:
        request = json.loads(row["request_json"])
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("verification request audit is malformed") from exc
    if not isinstance(request, Mapping):
        raise ValueError("verification closing authority is malformed")
    if recognized_pre_trust_verification_request(
        row, request
    ) or recognized_ambiguous_v1_closure_request(row, request):
        return "[]"
    linked_issue = request.get("linked_issue")
    supporting = request.get("supporting_issues")
    if not _positive_int(linked_issue) or not isinstance(supporting, list):
        raise ValueError("verification closing authority is malformed")
    version = request.get("contract_version")
    closing = request.get("closing_issues")
    if (
        version != "verification_dispatch_request.v2"
        or not isinstance(closing, list)
        or not closing
        or any(not _positive_int(issue) for issue in closing)
        or len(set(closing)) != len(closing)
        or not set(closing).issubset({linked_issue, *supporting})
    ):
        raise ValueError("verification closing authority is malformed")
    return json.dumps(closing, separators=(",", ":"), ensure_ascii=False)


def _legacy_verification_row_is_quarantined(row: sqlite3.Row) -> bool:
    try:
        supporting_authority = json.loads(row["supporting_authority_json"])
        closing_authority = json.loads(row["closing_authority_json"])
    except (TypeError, json.JSONDecodeError):
        return False
    return bool(
        row["status"] == LEGACY_UNTRUSTED_VERIFICATION_STATUS
        and row["legacy_recovery_audit_json"] is None
        and supporting_authority == []
        and closing_authority == []
        and row["current_head_sha"] == row["head_sha"]
        and row["verified_head_sha"] is None
        and all(
            row[field] is None
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
    )


def _validate_canonical_verification_row(row: sqlite3.Row) -> None:
    """Reuse the ledger's complete request/row contract before schema commit."""
    if row["status"] not in _CANONICAL_VERIFICATION_STATUSES:
        raise ValueError("verification canonical run authority is malformed")
    # Local import avoids a module cycle while retaining one canonical
    # validator for request shape, nested provenance, identity, heads, and
    # cumulative supporting authority.
    from app.dispatcher.verification_dispatch import _validated_row_request

    _validated_row_request(row)


class SqliteStore:
    """SQLite implementation of :class:`DispatcherStore`.

    Pairs with a :class:`JsonlEventWriter`; ``append_event`` writes to both so
    the SQLite row and JSONL audit line stay correlated by ``event_id``.
    """

    def __init__(
        self,
        db_path: Path,
        event_writer: JsonlEventWriter | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._event_writer = event_writer
        self._schema_ensured = False

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if not self._schema_ensured:
            self._ensure_schema(conn)
            self._schema_ensured = True
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """Self-heal an on-disk DB created before the ``repo`` column (schema v1).

        Runs on every connection, not just :meth:`initialize` — a long-lived
        shared instance (e.g. the Demerzel dispatcher) is never re-``init``ed
        once its DB file exists, so a migration reachable only from
        ``initialize()`` would never execute against it. Cached via
        ``self._schema_ensured`` so a tight loop of many ``_connect()`` calls
        (e.g. one dispatcher ``pull`` upserting hundreds of issues) pays the
        cheap outer check once per process, not once per row.

        The migration itself (additive DDL plus authority backfills) runs inside
        one explicit ``BEGIN IMMEDIATE`` transaction, committed or rolled back
        together: ``ALTER TABLE`` autocommits immediately outside an explicit
        transaction in Python's sqlite3 driver, so without this a crash
        between the ALTER and the backfill UPDATEs would permanently strand
        legacy rows with ``repo=''`` (the column-exists check has nothing
        left to detect). ``BEGIN IMMEDIATE`` also takes SQLite's write lock
        up front, so a second process racing this same migration blocks
        until the first finishes rather than hitting "duplicate column name"
        on its own ``ALTER TABLE`` — the column check is re-run *after*
        acquiring the lock (not just before) so the loser sees the column
        already present and skips straight to committing a no-op.
        """
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dispatcher_tasks'"
        ).fetchone()
        if exists is None:
            # Fresh DB: initialize() will create the table via DDL_STATEMENTS,
            # which already includes the repo column — nothing to migrate.
            return
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(dispatcher_tasks)")}
        meta_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dispatcher_meta'"
        ).fetchone()
        current_version = None
        if meta_exists is not None:
            row = conn.execute(
                "SELECT value FROM dispatcher_meta WHERE key='schema_version'"
            ).fetchone()
            current_version = None if row is None else str(row["value"])
        if "repo" in columns and current_version == str(SCHEMA_VERSION):
            # A database declaring the current version must already have the
            # complete current shape. Missing v4 identity columns cannot be
            # reconstructed without resetting keyed repair accounting.
            schema_error = verification_v6_schema_error(conn)
            if schema_error is not None:
                raise ValueError(schema_error)
            authority_reconciliation_required = False
            for verification_row in conn.execute(
                "SELECT * FROM verification_runs"
            ).fetchall():
                _, is_inert = _verification_authority_migration(verification_row)
                if is_inert:
                    authority_reconciliation_required = (
                        authority_reconciliation_required
                        or not _legacy_verification_row_is_quarantined(
                            verification_row
                        )
                    )
                else:
                    if (
                        verification_row["status"]
                        == LEGACY_UNTRUSTED_VERIFICATION_STATUS
                    ):
                        raise ValueError(
                            "legacy verification audit classification is malformed"
                        )
                    _validate_canonical_verification_row(verification_row)
            if not authority_reconciliation_required:
                return

        # Only the original v1 layout is a supported migration source.  In
        # particular, do not turn a database written by a newer dispatcher
        # into the current schema merely because its version differs from
        # ours: opening a future database must fail loudly and leave its
        # recovery evidence untouched.  The first v1 release predated
        # dispatcher_meta, so its absence is recognized only together with
        # the v1-specific missing ``repo`` column.
        is_unversioned_v1 = current_version is None and "repo" not in columns
        if current_version not in {
            "1", "2", "3", "4", "5", str(SCHEMA_VERSION)
        } and not is_unversioned_v1:
            version = "missing" if current_version is None else repr(current_version)
            raise ValueError(f"unsupported dispatcher schema_version: {version}")
        if current_version == "2" and "repo" not in columns:
            raise ValueError("dispatcher schema_version 2 is incompatible with the on-disk schema")

        conn.execute("BEGIN IMMEDIATE")
        try:
            # Re-check under the write lock: another process may have
            # completed this same migration between our check above and
            # acquiring the lock here.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(dispatcher_tasks)")}
            # The database may have changed while waiting for the write lock.
            # Re-read its version under that lock before performing any DDL.
            meta_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dispatcher_meta'"
            ).fetchone()
            current_version = None
            if meta_exists is not None:
                row = conn.execute(
                    "SELECT value FROM dispatcher_meta WHERE key='schema_version'"
                ).fetchone()
                current_version = None if row is None else str(row["value"])
            is_unversioned_v1 = current_version is None and "repo" not in columns
            if current_version not in {
                "1", "2", "3", "4", "5", str(SCHEMA_VERSION)
            } and not is_unversioned_v1:
                version = "missing" if current_version is None else repr(current_version)
                raise ValueError(f"unsupported dispatcher schema_version: {version}")
            if current_version in {
                "3", "4", "5", str(SCHEMA_VERSION)
            } and "repo" in columns:
                schema_error = (
                    verification_v3_schema_error(
                        conn, allow_additive_migration=True
                    )
                    if current_version == "3"
                    else (
                        verification_v4_schema_error(conn)
                        if current_version == "4"
                        else (
                            verification_v5_schema_error(conn)
                            if current_version == "5"
                            else verification_v6_schema_error(conn)
                        )
                    )
                )
                if schema_error is not None:
                    raise ValueError(schema_error)
                verification_columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(verification_runs)")
                }
                if (
                    current_version == "3"
                    and "current_head_sha" not in verification_columns
                ):
                    conn.execute(
                        "ALTER TABLE verification_runs ADD COLUMN "
                        "current_head_sha TEXT NOT NULL DEFAULT ''"
                    )
                    conn.execute(
                        "UPDATE verification_runs SET current_head_sha=head_sha "
                        "WHERE current_head_sha=''"
                    )
                if (
                    current_version == "3"
                    and "verified_head_sha" not in verification_columns
                ):
                    conn.execute(
                        "ALTER TABLE verification_runs ADD COLUMN verified_head_sha TEXT"
                    )
                supporting_authority_added = (
                    current_version == "3"
                    and "supporting_authority_json" not in verification_columns
                )
                if supporting_authority_added:
                    conn.execute(
                        "ALTER TABLE verification_runs ADD COLUMN "
                        "supporting_authority_json TEXT NOT NULL DEFAULT '[]'"
                    )
                closing_authority_added = (
                    current_version in {"3", "4"}
                    and "closing_authority_json" not in verification_columns
                )
                if closing_authority_added:
                    conn.execute(
                        "ALTER TABLE verification_runs ADD COLUMN "
                        "closing_authority_json TEXT NOT NULL DEFAULT '[]'"
                    )
                if (
                    current_version in {"3", "4", "5"}
                    and "legacy_recovery_audit_json" not in verification_columns
                ):
                    conn.execute(
                        "ALTER TABLE verification_runs ADD COLUMN "
                        "legacy_recovery_audit_json TEXT"
                    )
                if (
                    current_version == "3"
                    and "repair_budget_policy" not in verification_columns
                ):
                    conn.execute(
                        "ALTER TABLE verification_runs ADD COLUMN "
                        "repair_budget_policy TEXT NOT NULL DEFAULT 'v1'"
                    )
                verification_attempt_columns = {
                    row["name"]
                    for row in conn.execute(
                        "PRAGMA table_info(verification_attempts)"
                    )
                }
                for column in ("finding_id", "failure_domain", "mechanism_id"):
                    if (
                        current_version == "3"
                        and column not in verification_attempt_columns
                    ):
                        conn.execute(
                            f"ALTER TABLE verification_attempts ADD COLUMN {column} TEXT"
                        )
                for verification_row in conn.execute(
                    "SELECT * FROM verification_runs"
                ).fetchall():
                    supporting_authority, is_inert = (
                        _verification_authority_migration(verification_row)
                    )
                    if is_inert:
                        conn.execute(
                            """
                            UPDATE verification_runs
                            SET supporting_authority_json=?,
                                closing_authority_json='[]', status=?,
                                current_head_sha=head_sha,
                                verified_head_sha=NULL, claimed_by=NULL,
                                lease_id=NULL, lease_expires_at=NULL,
                                last_heartbeat_at=NULL,
                                coordinator_session_id=NULL,
                                context_pack_json=NULL, retry_after=NULL
                            WHERE run_id=?
                            """,
                            (
                                supporting_authority,
                                LEGACY_UNTRUSTED_VERIFICATION_STATUS,
                                verification_row["run_id"],
                            ),
                        )
                    elif supporting_authority_added:
                        conn.execute(
                            "UPDATE verification_runs "
                            "SET supporting_authority_json=? WHERE run_id=?",
                            (
                                supporting_authority,
                                verification_row["run_id"],
                            ),
                        )
                    if closing_authority_added:
                        conn.execute(
                            "UPDATE verification_runs "
                            "SET closing_authority_json=? WHERE run_id=?",
                            (
                                _verification_closing_authority_migration(
                                    verification_row
                                ),
                                verification_row["run_id"],
                            ),
                        )
                for verification_row in conn.execute(
                    "SELECT * FROM verification_runs"
                ).fetchall():
                    _, is_inert = _verification_authority_migration(
                        verification_row
                    )
                    if is_inert:
                        if not _legacy_verification_row_is_quarantined(
                            verification_row
                        ):
                            raise ValueError(
                                "legacy verification audit classification is malformed"
                            )
                    else:
                        if (
                            verification_row["status"]
                            == LEGACY_UNTRUSTED_VERIFICATION_STATUS
                        ):
                            raise ValueError(
                                "legacy verification audit classification is malformed"
                            )
                        _validate_canonical_verification_row(verification_row)
                schema_error = verification_v6_schema_error(conn)
                if schema_error is not None:
                    raise ValueError(schema_error)
                conn.execute(
                    "INSERT OR REPLACE INTO dispatcher_meta(key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
                conn.commit()
                return
            if current_version == str(SCHEMA_VERSION):
                raise ValueError(
                    f"dispatcher schema_version {SCHEMA_VERSION} is incompatible with the on-disk schema"
                )
            if current_version == "2" and "repo" not in columns:
                raise ValueError(
                    "dispatcher schema_version 2 is incompatible with the on-disk schema"
                )
            if "repo" not in columns:
                conn.execute("ALTER TABLE dispatcher_tasks ADD COLUMN repo TEXT NOT NULL DEFAULT ''")
                # The legacy task_id format (pre-multi-repo) had no repo
                # qualifier and was only ever produced for
                # RasmusTho/agentic-pkm-mvp pulls; backfill repo and re-key
                # task_id to the current repo-qualified form so these rows
                # don't linger as orphaned duplicates the moment a pull runs
                # under the new scheme. Also re-key the matching event-log
                # rows so historical events stay joinable to the renamed task.
                conn.execute(
                    """
                    UPDATE dispatcher_tasks
                    SET repo = 'RasmusTho/agentic-pkm-mvp',
                        task_id = 'github-RasmusTho--agentic-pkm-mvp-issue-' || issue_number
                    WHERE task_id LIKE 'github-issue-%'
                    """
                )
                conn.execute(
                    """
                    UPDATE dispatcher_events
                    SET task_id = 'github-RasmusTho--agentic-pkm-mvp-issue-'
                        || substr(task_id, length('github-issue-') + 1)
                    WHERE task_id LIKE 'github-issue-%'
                    """
                )
            for stmt in DDL_STATEMENTS:
                conn.execute(stmt)
            schema_error = verification_v6_schema_error(conn)
            if schema_error is not None:
                raise ValueError(schema_error)
            conn.execute(
                "INSERT OR REPLACE INTO dispatcher_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for stmt in DDL_STATEMENTS:
                    conn.execute(stmt)
                schema_error = verification_v6_schema_error(conn)
                if schema_error is not None:
                    raise ValueError(schema_error)
                conn.execute(
                    "INSERT OR REPLACE INTO dispatcher_meta(key, value) VALUES (?, ?)",
                    ("schema_version", str(SCHEMA_VERSION)),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    # ----- coordination metadata -----

    def get_meta(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM dispatcher_meta WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO dispatcher_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            conn.commit()

    # ----- tasks -----

    def upsert_task(self, task: TaskRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dispatcher_tasks (
                    task_id, issue_number, title, status, priority, repo,
                    source_anchor_refs, claimed_by, lease_id, lease_expires_at,
                    linked_pr, blocked_reason, last_heartbeat_at, sync_state,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id) DO UPDATE SET
                    issue_number=excluded.issue_number,
                    title=excluded.title,
                    status=excluded.status,
                    priority=excluded.priority,
                    repo=excluded.repo,
                    source_anchor_refs=excluded.source_anchor_refs,
                    claimed_by=excluded.claimed_by,
                    lease_id=excluded.lease_id,
                    lease_expires_at=excluded.lease_expires_at,
                    linked_pr=excluded.linked_pr,
                    blocked_reason=excluded.blocked_reason,
                    last_heartbeat_at=excluded.last_heartbeat_at,
                    sync_state=excluded.sync_state,
                    updated_at=excluded.updated_at
                """,
                (
                    task.task_id,
                    task.issue_number,
                    task.title,
                    task.status,
                    task.priority,
                    task.repo,
                    _dumps(list(task.source_anchor_refs)),
                    task.claimed_by,
                    task.lease_id,
                    task.lease_expires_at,
                    task.linked_pr,
                    task.blocked_reason,
                    task.last_heartbeat_at,
                    _dumps(task.sync_state),
                    task.created_at,
                    task.updated_at,
                ),
            )
            conn.commit()

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM dispatcher_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            return None
        return TaskRecord(
            task_id=row["task_id"],
            issue_number=row["issue_number"],
            title=row["title"],
            status=row["status"],
            priority=row["priority"],
            repo=row["repo"],
            source_anchor_refs=list(_loads(row["source_anchor_refs"]) or []),
            claimed_by=row["claimed_by"],
            lease_id=row["lease_id"],
            lease_expires_at=row["lease_expires_at"],
            linked_pr=row["linked_pr"],
            blocked_reason=row["blocked_reason"],
            last_heartbeat_at=row["last_heartbeat_at"],
            sync_state=_loads(row["sync_state"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ----- leases -----

    def upsert_lease(self, lease: LeaseRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dispatcher_leases (
                    lease_id, resource, holder, ttl_seconds, acquired_at,
                    expires_at, heartbeat_at, released_at, release_reason
                ) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(lease_id) DO UPDATE SET
                    resource=excluded.resource,
                    holder=excluded.holder,
                    ttl_seconds=excluded.ttl_seconds,
                    acquired_at=excluded.acquired_at,
                    expires_at=excluded.expires_at,
                    heartbeat_at=excluded.heartbeat_at,
                    released_at=excluded.released_at,
                    release_reason=excluded.release_reason
                """,
                (
                    lease.lease_id,
                    lease.resource,
                    lease.holder,
                    lease.ttl_seconds,
                    lease.acquired_at,
                    lease.expires_at,
                    lease.heartbeat_at,
                    lease.released_at,
                    lease.release_reason,
                ),
            )
            conn.commit()

    def get_lease(self, lease_id: str) -> LeaseRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM dispatcher_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
        if row is None:
            return None
        return LeaseRecord(
            lease_id=row["lease_id"],
            resource=row["resource"],
            holder=row["holder"],
            ttl_seconds=row["ttl_seconds"],
            acquired_at=row["acquired_at"],
            expires_at=row["expires_at"],
            heartbeat_at=row["heartbeat_at"],
            released_at=row["released_at"],
            release_reason=row["release_reason"],
        )

    # ----- events -----

    def append_event(self, event: EventRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dispatcher_events (
                    event_id, timestamp, task_id, event_type, actor,
                    lease_id, payload
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    event.event_id,
                    event.timestamp,
                    event.task_id,
                    event.event_type,
                    event.actor,
                    event.lease_id,
                    _dumps(event.payload),
                ),
            )
            conn.commit()
        if self._event_writer is not None:
            self._event_writer.append(event)

    def list_tasks(
        self, status: str | None = None, repo: str | None = None
    ) -> list[TaskRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if repo is not None:
            clauses.append("repo = ?")
            params.append(repo)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM dispatcher_tasks {where}"
                "ORDER BY updated_at DESC, created_at DESC",
                tuple(params),
            ).fetchall()
        return [
            TaskRecord(
                task_id=r["task_id"],
                issue_number=r["issue_number"],
                title=r["title"],
                status=r["status"],
                priority=r["priority"],
                repo=r["repo"],
                source_anchor_refs=list(_loads(r["source_anchor_refs"]) or []),
                claimed_by=r["claimed_by"],
                lease_id=r["lease_id"],
                lease_expires_at=r["lease_expires_at"],
                linked_pr=r["linked_pr"],
                blocked_reason=r["blocked_reason"],
                last_heartbeat_at=r["last_heartbeat_at"],
                sync_state=_loads(r["sync_state"]),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def list_events(self, task_id: str | None = None) -> list[EventRecord]:
        with self._connect() as conn:
            if task_id is None:
                rows = conn.execute(
                    "SELECT * FROM dispatcher_events ORDER BY timestamp, event_id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM dispatcher_events WHERE task_id = ? "
                    "ORDER BY timestamp, event_id",
                    (task_id,),
                ).fetchall()
        return [
            EventRecord(
                event_id=r["event_id"],
                timestamp=r["timestamp"],
                task_id=r["task_id"],
                event_type=r["event_type"],
                actor=r["actor"],
                lease_id=r["lease_id"],
                payload=_loads(r["payload"]),
            )
            for r in rows
        ]
