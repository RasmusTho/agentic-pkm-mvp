"""PostgreSQL transaction, fencing, and outbox kernel for BuilderOps."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

if TYPE_CHECKING:
    from app.builderops.owner_fact_producers import OwnerOutcomeAdmission

from app.builderops.control_plane.migrations import AUTHORITY_EPOCH, MIGRATIONS, SCHEMA_VERSION
from app.builderops.control_plane.models import (
    AuthorityEnvelope,
    AuthorityObjectResult,
    DurabilityPending,
    EnvelopeValidationError,
    IdempotencyConflict,
    Lease,
    LeaseRequired,
    LeaseUnavailable,
    OutboxClaim,
    OutboxReconciliation,
    StateConflict,
    StaleFencingToken,
    TransactionResult,
    UnknownEffectNeedsReconciliation,
    canonical_repository,
)

_ISSUE_DELIVERY_IDEMPOTENCY_PREFIX = "issue-delivery:"
_ISSUE_DELIVERY_OPERATION_IDEMPOTENCY_PREFIX = "issue-delivery-operation:"
_ISSUE_DELIVERY_SCOPE = "issue-delivery-approval"
_ISSUE_DELIVERY_RECORD_TYPE = "IssueDeliveryApproval"
_ISSUE_DELIVERY_ADMISSION_CAPABILITY = object()
_ISSUE_DELIVERY_OPERATION_SCOPE = "issue-delivery-operation"
_ISSUE_DELIVERY_OPERATION_RECORD_TYPE = "BuilderOpsReceipt"
_ISSUE_DELIVERY_OPERATION_CAPABILITY = object()


def _issue_delivery_admission_capability() -> object:
    """Return the in-process capability held by the owner-admission service."""

    return _ISSUE_DELIVERY_ADMISSION_CAPABILITY


def _issue_delivery_operation_capability() -> object:
    """Return the in-process capability held by the destination adapter.

    Keeping this capability private prevents a generic record writer from
    manufacturing an Issue-delivery reservation or entry.  The HTTP service
    is the only caller that can obtain it and performs the fresh approval and
    destination checks before invoking the store.
    """

    return _ISSUE_DELIVERY_OPERATION_CAPABILITY


def _guard_idempotency_namespace(
    idempotency_key: str,
    *,
    envelope: AuthorityEnvelope,
    object_kind: str | None = None,
    record_type: str | None = None,
    secondary_id: str | None = None,
) -> None:
    """Reserve the Issue-delivery keyspace at every global write boundary.

    The Issue-delivery approval writer is the sole admitted owner of this
    prefix. Keeping the decision here, rather than only in an HTTP route,
    prevents direct store callers (including leases and task transitions) from
    squatting an operation key before the authenticated approval is committed.
    """
    if not isinstance(idempotency_key, str):
        return
    operation_keyspace = idempotency_key.startswith(
        _ISSUE_DELIVERY_OPERATION_IDEMPOTENCY_PREFIX
    )
    if operation_keyspace:
        operation_record = (
            envelope.scope == _ISSUE_DELIVERY_OPERATION_SCOPE
            and object_kind == "record"
            and secondary_id == _ISSUE_DELIVERY_OPERATION_RECORD_TYPE
        )
        if not operation_record:
            raise StateConflict(
                "Issue-delivery operation idempotency keys require the destination adapter"
            )
        return
    if not idempotency_key.startswith(_ISSUE_DELIVERY_IDEMPOTENCY_PREFIX):
        return
    issue_delivery_record = (
        envelope.scope == _ISSUE_DELIVERY_SCOPE
        and object_kind == "record"
        and (
            record_type == _ISSUE_DELIVERY_RECORD_TYPE
            or secondary_id == _ISSUE_DELIVERY_RECORD_TYPE
        )
    )
    if not issue_delivery_record:
        raise StateConflict("Issue-delivery idempotency keys require exact owner admission")


def _canonical(value: Mapping[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _validate_row_derived_evidence(
    evidence: Mapping[str, Any], *, terminal_unknown: bool
) -> None:
    """Validate the closed post-effect evidence schema at the persistence boundary."""
    if terminal_unknown:
        _assert_terminal_unknown_model_evidence(
            effect_type="model.verification_coordinator",
            effect_payload={"head_sha": evidence.get("head_sha")},
            task_payload={
                "contract_version": "builderops_verification_run.v1",
                "run": {"coordinator_session_id": None, "context_pack": None},
            },
            evidence=evidence,
        )
        return
    allowed = {"readback", "relaunch_performed"}
    if not isinstance(evidence, Mapping) or not set(evidence).issubset(allowed):
        raise ValueError("row-derived readback evidence contains unknown fields")
    readback = evidence.get("readback")
    if readback not in {"found", "not-found", "unknown"}:
        raise ValueError("row-derived readback evidence has an invalid outcome")
    relaunch = evidence.get("relaunch_performed")
    if relaunch is not None and type(relaunch) is not bool:
        raise ValueError("row-derived readback evidence has an invalid relaunch flag")


def _operation_key(repository: str, idempotency_key: str, effect_type: str) -> str:
    return _hash(
        {"repository": repository, "idempotency_key": idempotency_key, "effect_type": effect_type}
    )


def _assert_terminal_unknown_model_evidence(
    *,
    effect_type: str,
    effect_payload: Mapping[str, Any],
    task_payload: Mapping[str, Any],
    evidence: Mapping[str, Any],
) -> None:
    expected_keys = {
        "head_sha",
        "outcome",
        "provider_session_id",
        "relaunch_performed",
    }
    head_sha = evidence.get("head_sha")
    run = task_payload.get("run")
    durable_pre_session = bool(
        task_payload.get("contract_version") == "builderops_verification_run.v1"
        and isinstance(run, Mapping)
        and "coordinator_session_id" in run
        and run.get("coordinator_session_id") is None
        and "context_pack" in run
        and run.get("context_pack") is None
    )
    if (
        effect_type != "model.verification_coordinator"
        or not durable_pre_session
        or set(evidence) != expected_keys
        or evidence.get("outcome") != "indeterminate_pre_session_model_effect"
        or evidence.get("provider_session_id") is not None
        or evidence.get("relaunch_performed") is not False
        or not isinstance(head_sha, str)
        or len(head_sha) != 40
        or any(character not in "0123456789abcdef" for character in head_sha)
        or effect_payload.get("head_sha") != head_sha
    ):
        raise StateConflict(
            "terminal-unknown reconciliation is restricted to an exact "
            "pre-session verification-model effect receipt"
        )


class PostgresBuilderOpsStore:
    """Single-authority kernel; it never performs an external side effect."""

    def __init__(self, dsn: str) -> None:
        if not dsn.startswith(("postgresql://", "postgres://", "postgresql+psycopg://")):
            raise RuntimeError("BuilderOps production authority requires PostgreSQL")
        self.dsn = dsn.replace("postgresql+psycopg://", "postgresql://", 1)

    def _connect(self) -> psycopg.Connection[dict[str, Any]]:
        return psycopg.connect(self.dsn, row_factory=dict_row)

    @staticmethod
    def _database_now(conn: psycopg.Connection[dict[str, Any]]) -> datetime:
        row = conn.execute("SELECT clock_timestamp() AS database_now").fetchone()
        assert row is not None
        return row["database_now"]

    @staticmethod
    def _schema_fingerprint(conn: psycopg.Connection[dict[str, Any]]) -> str:
        """Hash the live BuilderOps catalog shape, excluding mutable row data."""
        rows = conn.execute(
            "SELECT kind, identity, definition FROM ("
            "SELECT 'relation' AS kind, class.relname AS identity, class.relkind::text AS definition "
            "FROM pg_class AS class "
            "JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
            "WHERE namespace.nspname = current_schema() "
            "AND (class.relname LIKE 'builderops_%' OR class.relname LIKE 'idx_builderops_%') "
            "UNION ALL "
            "SELECT 'column', class.relname || '.' || attribute.attnum::text, "
            "concat_ws('|', attribute.attname, format_type(attribute.atttypid, attribute.atttypmod), "
            "attribute.attnotnull::text, attribute.attidentity::text, attribute.attgenerated::text, "
            "COALESCE(pg_get_expr(default_value.adbin, default_value.adrelid), '')) "
            "FROM pg_class AS class "
            "JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
            "JOIN pg_attribute AS attribute ON attribute.attrelid = class.oid "
            "LEFT JOIN pg_attrdef AS default_value ON default_value.adrelid = class.oid "
            "AND default_value.adnum = attribute.attnum "
            "WHERE namespace.nspname = current_schema() "
            "AND class.relname LIKE 'builderops_%' AND class.relkind IN ('r', 'p') "
            "AND attribute.attnum > 0 AND NOT attribute.attisdropped "
            "UNION ALL "
            "SELECT 'constraint', class.relname || '.' || constraint_row.conname, "
            "constraint_row.contype::text || '|' || pg_get_constraintdef(constraint_row.oid, true) "
            "FROM pg_constraint AS constraint_row "
            "JOIN pg_class AS class ON class.oid = constraint_row.conrelid "
            "JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
            "WHERE namespace.nspname = current_schema() AND class.relname LIKE 'builderops_%' "
            "UNION ALL "
            "SELECT 'index', index_class.relname, pg_get_indexdef(index_class.oid) "
            "FROM pg_index AS index_row "
            "JOIN pg_class AS index_class ON index_class.oid = index_row.indexrelid "
            "JOIN pg_class AS table_class ON table_class.oid = index_row.indrelid "
            "JOIN pg_namespace AS namespace ON namespace.oid = table_class.relnamespace "
            "WHERE namespace.nspname = current_schema() "
            "AND table_class.relname LIKE 'builderops_%' "
            "UNION ALL "
            "SELECT 'sequence', class.relname, concat_ws('|', sequence.seqstart::text, "
            "sequence.seqincrement::text, sequence.seqmax::text, sequence.seqmin::text, "
            "sequence.seqcache::text, sequence.seqcycle::text) "
            "FROM pg_sequence AS sequence "
            "JOIN pg_class AS class ON class.oid = sequence.seqrelid "
            "JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
            "WHERE namespace.nspname = current_schema() AND class.relname LIKE 'builderops_%' "
            "UNION ALL "
            "SELECT 'function', procedure.proname || '(' || "
            "pg_get_function_identity_arguments(procedure.oid) || ')', "
            "pg_get_functiondef(procedure.oid) "
            "FROM pg_proc AS procedure "
            "JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace "
            "WHERE namespace.nspname = current_schema() "
            "AND procedure.proname LIKE 'builderops_%'"
            ") AS catalog ORDER BY kind, identity, definition"
        ).fetchall()
        document = [
            (str(row["kind"]), str(row["identity"]), str(row["definition"])) for row in rows
        ]
        return hashlib.sha256(
            json.dumps(document, separators=(",", ":"), ensure_ascii=False).encode()
        ).hexdigest()

    @classmethod
    def _assert_schema_fingerprint(
        cls,
        conn: psycopg.Connection[dict[str, Any]],
        expected: str,
    ) -> None:
        if cls._schema_fingerprint(conn) != expected:
            raise RuntimeError("BuilderOps live schema does not match its recorded fingerprint")

    def initialize(self) -> None:
        with self._connect() as conn:
            migration_rows: dict[int, Mapping[str, Any]] = {}
            existing_relations = {
                str(row["relname"])
                for row in conn.execute(
                    "SELECT class.relname FROM pg_class AS class "
                    "JOIN pg_namespace AS namespace ON namespace.oid = class.relnamespace "
                    "WHERE namespace.nspname = current_schema() "
                    "AND (class.relname LIKE 'builderops_%' "
                    "OR class.relname LIKE 'idx_builderops_%')"
                ).fetchall()
            }
            existing_functions = {
                str(row["proname"])
                for row in conn.execute(
                    "SELECT procedure.proname FROM pg_proc AS procedure "
                    "JOIN pg_namespace AS namespace ON namespace.oid = procedure.pronamespace "
                    "WHERE namespace.nspname = current_schema() "
                    "AND procedure.proname LIKE 'builderops_%'"
                ).fetchall()
            }
            has_migration_ledger = "builderops_schema_migrations" in existing_relations
            has_authority_metadata = "builderops_authority_metadata" in existing_relations
            if (existing_relations or existing_functions) and not (
                has_migration_ledger and has_authority_metadata
            ):
                raise RuntimeError(
                    "existing BuilderOps schema is missing migration or authority metadata"
                )
            if has_migration_ledger != has_authority_metadata:
                raise RuntimeError(
                    "BuilderOps migration ledger and authority metadata must exist together"
                )
            if has_migration_ledger:
                columns = {
                    str(row["column_name"])
                    for row in conn.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() "
                        "AND table_name = 'builderops_schema_migrations'"
                    ).fetchall()
                }
                if "checksum" not in columns:
                    raise RuntimeError("BuilderOps migration ledger predates checksum enforcement")
                migration_rows = {
                    int(row["version"]): row
                    for row in conn.execute(
                        "SELECT version, name, checksum FROM builderops_schema_migrations "
                        "ORDER BY version"
                    ).fetchall()
                }
                applied_versions = sorted(migration_rows)
                if not applied_versions or applied_versions != list(
                    range(1, applied_versions[-1] + 1)
                ):
                    raise RuntimeError("BuilderOps migration ledger is empty or non-contiguous")
                for version, row in migration_rows.items():
                    if version < 1 or version > SCHEMA_VERSION:
                        raise RuntimeError(
                            "BuilderOps database has a newer or unknown migration version"
                        )
                    path = MIGRATIONS[version - 1]
                    expected_checksum = hashlib.sha256(path.read_bytes()).hexdigest()
                    if row["name"] != path.name or row["checksum"] != expected_checksum:
                        raise RuntimeError(
                            f"BuilderOps migration {version} does not match this release lineage"
                        )
            if has_authority_metadata:
                metadata_columns = {
                    str(row["column_name"])
                    for row in conn.execute(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = current_schema() "
                        "AND table_name = 'builderops_authority_metadata'"
                    ).fetchall()
                }
                if "schema_fingerprint" not in metadata_columns:
                    raise RuntimeError(
                        "BuilderOps authority metadata predates schema fingerprint enforcement"
                    )
                metadata = conn.execute(
                    "SELECT authority_epoch, schema_version, schema_fingerprint "
                    "FROM builderops_authority_metadata WHERE singleton FOR UPDATE"
                ).fetchone()
                if metadata is None:
                    raise RuntimeError("BuilderOps authority metadata row is missing")
                if int(metadata["schema_version"]) > SCHEMA_VERSION:
                    raise RuntimeError("BuilderOps database schema is newer than this release")
                if int(metadata["schema_version"]) != max(migration_rows):
                    raise RuntimeError(
                        "BuilderOps schema metadata does not match the migration ledger"
                    )
                self._assert_schema_fingerprint(conn, str(metadata["schema_fingerprint"]))

            for version, path in enumerate(MIGRATIONS, start=1):
                if version not in migration_rows:
                    checksum = hashlib.sha256(path.read_bytes()).hexdigest()
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute(
                        "INSERT INTO builderops_schema_migrations(version, name, checksum) "
                        "VALUES (%s, %s, %s) "
                        "ON CONFLICT (version) DO NOTHING",
                        (version, path.name, checksum),
                    )
            schema_fingerprint = self._schema_fingerprint(conn)
            metadata = conn.execute(
                "INSERT INTO builderops_authority_metadata("
                "singleton, authority_epoch, schema_version, schema_fingerprint) "
                "VALUES (true, %s, %s, %s) ON CONFLICT (singleton) DO UPDATE SET "
                "authority_epoch = GREATEST(builderops_authority_metadata.authority_epoch, "
                "EXCLUDED.authority_epoch), schema_version = EXCLUDED.schema_version, "
                "schema_fingerprint = EXCLUDED.schema_fingerprint, "
                "updated_at = clock_timestamp() "
                "WHERE builderops_authority_metadata.schema_version <= EXCLUDED.schema_version "
                "RETURNING authority_epoch, schema_version",
                (AUTHORITY_EPOCH, SCHEMA_VERSION, schema_fingerprint),
            ).fetchone()
            if metadata is None:
                raise RuntimeError("BuilderOps authority metadata refused a downgrade")

    def readiness(self) -> dict[str, int]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT authority_epoch, schema_version, schema_fingerprint "
                "FROM builderops_authority_metadata WHERE singleton"
            ).fetchone()
            if row is None:
                raise RuntimeError("BuilderOps schema is not initialized")
            self._assert_schema_fingerprint(conn, str(row["schema_fingerprint"]))
            return {
                "authority_epoch": int(row["authority_epoch"]),
                "schema_version": int(row["schema_version"]),
            }

    def recovery_state(self) -> dict[str, Any]:
        """Return the bounded recovery fence, never backup credentials or target URLs."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT activated_authority_epoch, recovery_id, restored_lsn::text AS restored_lsn, "
                "reconciliation_required, executor_enabled, activated_at, reconciled_at "
                "FROM builderops_recovery_state WHERE singleton"
            ).fetchone()
        if row is None:
            raise RuntimeError("BuilderOps recovery state is not initialized")
        return dict(row)

    def write_service_heartbeat(self, *, service_name: str, state: str = "running") -> None:
        if not service_name.strip() or not state.strip():
            raise ValueError("service_name and state are mandatory")
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO builderops_service_heartbeats(service_name, state, observed_at) "
                "VALUES (%s, %s, clock_timestamp()) ON CONFLICT (service_name) DO UPDATE SET "
                "state = EXCLUDED.state, observed_at = EXCLUDED.observed_at",
                (service_name, state),
            )

    def service_heartbeat(self, service_name: str) -> dict[str, Any] | None:
        if not service_name.strip():
            raise ValueError("service_name is mandatory")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT service_name, state, observed_at FROM builderops_service_heartbeats "
                "WHERE service_name = %s",
                (service_name,),
            ).fetchone()
        return dict(row) if row is not None else None

    def activate_recovered_epoch(self, *, recovery_id: str, restored_lsn: str) -> int:
        """Fence pre-restore actors and require external-effect reconciliation.

        This transition is deliberately independent of backup lag. It runs only
        after a database has been restored and promoted, and it never rewinds an
        epoch chosen by the database itself.
        """
        if not recovery_id.strip() or not restored_lsn.strip():
            raise ValueError("recovery_id and restored_lsn are mandatory")
        with self._connect() as conn:
            recovery = conn.execute(
                "SELECT recovery_id, activated_authority_epoch, restored_lsn::text AS restored_lsn "
                "FROM builderops_recovery_state WHERE singleton FOR UPDATE"
            ).fetchone()
            if recovery is None:
                raise RuntimeError("BuilderOps recovery state is not initialized")
            if recovery["recovery_id"] == recovery_id:
                if recovery["restored_lsn"] != restored_lsn:
                    raise RuntimeError("recovery identity was reused for another restored LSN")
                return int(recovery["activated_authority_epoch"])
            metadata = conn.execute(
                "SELECT authority_epoch FROM builderops_authority_metadata "
                "WHERE singleton FOR UPDATE"
            ).fetchone()
            if metadata is None:
                raise RuntimeError("BuilderOps authority metadata is missing")
            next_epoch = int(metadata["authority_epoch"]) + 1
            conn.execute(
                "UPDATE builderops_authority_metadata SET authority_epoch = %s, "
                "updated_at = clock_timestamp() WHERE singleton",
                (next_epoch,),
            )
            conn.execute(
                "UPDATE builderops_leases SET holder = 'recovery-fence', "
                "fencing_token = fencing_token + 1, expires_at = clock_timestamp(), "
                "updated_at = clock_timestamp()"
            )
            conn.execute(
                "UPDATE builderops_outbox SET status = 'unknown', "
                "unknown_detail = 'recovered claim requires external readback', "
                "claim_expires_at = NULL, updated_at = clock_timestamp() "
                "WHERE status = 'claimed'"
            )
            activated = conn.execute(
                "UPDATE builderops_recovery_state SET activated_authority_epoch = %s, "
                "recovery_id = %s, restored_lsn = %s::pg_lsn, "
                "reconciliation_required = true, executor_enabled = false, "
                "activated_at = clock_timestamp(), reconciled_at = NULL WHERE singleton "
                "RETURNING activated_authority_epoch",
                (next_epoch, recovery_id, restored_lsn),
            ).fetchone()
            if activated is None:
                raise RuntimeError("BuilderOps recovery fence activation failed")
        return next_epoch

    def complete_recovery_reconciliation(
        self, *, recovery_id: str, authority_epoch: int
    ) -> None:
        """Re-enable executor claims after the separate GitHub readback gate."""
        if not recovery_id.strip() or authority_epoch <= 0:
            raise ValueError("recovery_id and positive authority_epoch are mandatory")
        with self._connect() as conn:
            updated = conn.execute(
                "UPDATE builderops_recovery_state SET reconciliation_required = false, "
                "executor_enabled = true, reconciled_at = clock_timestamp() "
                "WHERE singleton AND recovery_id = %s "
                "AND activated_authority_epoch = %s AND reconciliation_required "
                "AND NOT EXISTS (SELECT 1 FROM builderops_outbox WHERE status = 'unknown') "
                "RETURNING singleton",
                (recovery_id, authority_epoch),
            ).fetchone()
            if updated is None:
                raise RuntimeError(
                    "recovery reconciliation gate still has an identity, epoch, "
                    "or unknown-effect mismatch"
                )

    @staticmethod
    def _assert_executor_enabled(conn: psycopg.Connection[dict[str, Any]]) -> None:
        row = conn.execute(
            "SELECT executor_enabled FROM builderops_recovery_state WHERE singleton"
        ).fetchone()
        if row is None or not bool(row["executor_enabled"]):
            raise DurabilityPending("executor is fenced pending post-restore reconciliation")

    def get_task(self, repository: str, task_id: str) -> Mapping[str, Any]:
        canonical = canonical_repository(repository)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT task.repository, task.task_id, task.state, task.payload, "
                "task.authority_envelope, task.version, task.updated_at, "
                "lease.holder AS lease_holder, lease.fencing_token, "
                "lease.expires_at, lease.lease_kind, lease.updated_at AS lease_updated_at "
                "FROM builderops_tasks AS task LEFT JOIN builderops_leases AS lease "
                "ON lease.repository = task.repository "
                "AND lease.resource_id = task.task_id "
                "AND lease.lease_kind = 'task' "
                "WHERE task.repository = %s AND task.task_id = %s",
                (canonical, task_id),
            ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._task_snapshot(row)

    def list_tasks(
        self, repository: str, *, task_prefix: str | None = None
    ) -> list[Mapping[str, Any]]:
        canonical = canonical_repository(repository)
        with self._connect() as conn:
            if task_prefix is None:
                rows = conn.execute(
                    "SELECT task.repository, task.task_id, task.state, task.payload, "
                    "task.authority_envelope, task.version, task.updated_at, "
                    "lease.holder AS lease_holder, lease.fencing_token, "
                    "lease.expires_at, lease.lease_kind, lease.updated_at AS lease_updated_at "
                    "FROM builderops_tasks AS task LEFT JOIN builderops_leases AS lease "
                    "ON lease.repository = task.repository "
                    "AND lease.resource_id = task.task_id "
                    "AND lease.lease_kind = 'task' "
                    "WHERE task.repository = %s "
                    "ORDER BY task.updated_at DESC, task.task_id",
                    (canonical,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT task.repository, task.task_id, task.state, task.payload, "
                    "task.authority_envelope, task.version, task.updated_at, "
                    "lease.holder AS lease_holder, lease.fencing_token, "
                    "lease.expires_at, lease.lease_kind, lease.updated_at AS lease_updated_at "
                    "FROM builderops_tasks AS task LEFT JOIN builderops_leases AS lease "
                    "ON lease.repository = task.repository "
                    "AND lease.resource_id = task.task_id "
                    "AND lease.lease_kind = 'task' "
                    "WHERE task.repository = %s AND task.task_id LIKE %s "
                    "ORDER BY task.updated_at DESC, task.task_id",
                    (canonical, f"{task_prefix}%"),
                ).fetchall()
        return [self._task_snapshot(row) for row in rows]

    @staticmethod
    def _task_snapshot(row: Mapping[str, Any]) -> Mapping[str, Any]:
        snapshot = {
            key: row[key]
            for key in (
                "repository",
                "task_id",
                "state",
                "payload",
                "authority_envelope",
                "version",
                "updated_at",
            )
        }
        if row.get("lease_holder") is not None:
            snapshot["lease"] = {
                "repository": row["repository"],
                "resource_id": row["task_id"],
                "holder": row["lease_holder"],
                "fencing_token": row["fencing_token"],
                "expires_at": row["expires_at"],
                "lease_kind": row["lease_kind"],
                "updated_at": row.get("lease_updated_at"),
            }
        else:
            snapshot["lease"] = None
        return snapshot

    def list_attempts(
        self, repository: str, task_id: str
    ) -> list[Mapping[str, Any]]:
        canonical = canonical_repository(repository)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT repository, task_id, attempt_id, state, payload, "
                "authority_envelope, updated_at FROM builderops_attempts "
                "WHERE repository = %s AND task_id = %s "
                "ORDER BY updated_at, attempt_id",
                (canonical, task_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def commit_transition(
        self,
        *,
        envelope: AuthorityEnvelope,
        task_id: str,
        to_state: str,
        idempotency_key: str,
        request: Mapping[str, Any],
        outbox: Mapping[str, Any] | None = None,
        lease: Lease | None = None,
        expected_states: tuple[str, ...] | None = None,
        expected_version: int | None = None,
        fault_at: str | None = None,
    ) -> TransactionResult:
        """Commit a guarded transition through the shared task kernel."""
        return self._commit_transition(
            envelope=envelope,
            task_id=task_id,
            to_state=to_state,
            idempotency_key=idempotency_key,
            request=request,
            outbox=outbox,
            lease=lease,
            expected_states=expected_states,
            expected_version=expected_version,
            fault_at=fault_at,
        )

    def _commit_transition(
        self,
        *,
        envelope: AuthorityEnvelope,
        task_id: str,
        to_state: str,
        idempotency_key: str,
        request: Mapping[str, Any],
        outbox: Mapping[str, Any] | None = None,
        lease: Lease | None = None,
        claim_holder: str | None = None,
        claim_ttl_seconds: int = 5400,
        require_new_fence: bool = False,
        release_on_commit: bool = False,
        expected_states: tuple[str, ...] | None = None,
        expected_version: int | None = None,
        fault_at: str | None = None,
    ) -> TransactionResult:
        _guard_idempotency_namespace(idempotency_key, envelope=envelope)
        if not task_id or not to_state or not idempotency_key:
            raise ValueError("task_id, to_state, and idempotency_key are mandatory")
        if claim_holder is not None and lease is not None:
            raise ValueError("claim_holder and an existing lease are mutually exclusive")
        if release_on_commit and lease is None:
            raise ValueError("release_on_commit requires an existing fenced lease")
        if to_state == "claimed" and claim_holder is None and lease is None:
            raise LeaseRequired(
                "claimed task state requires atomically bound fenced ownership "
                "or an exact retained fenced lease"
            )
        if outbox is not None and lease is None and claim_holder is None:
            raise LeaseRequired("outbox intent requires atomically fenced task ownership")
        request_document = {
            "authority_envelope": envelope.as_json(),
            "task_id": task_id,
            "to_state": to_state,
            "request": dict(request),
            "outbox": dict(outbox) if outbox is not None else None,
            "claim_holder": claim_holder,
            "claim_ttl_seconds": claim_ttl_seconds if claim_holder is not None else None,
            "release_on_commit": release_on_commit,
            "lease_identity": self._lease_identity_json(lease) if lease is not None else None,
            "expected_states": list(expected_states) if expected_states is not None else None,
            "expected_version": expected_version,
        }
        if claim_holder is not None and require_new_fence:
            # Preserve the pre-BCP-05 request hash for ordinary/idempotent
            # claims; only recovery's stricter semantic enters the hash.
            request_document["require_new_fence"] = True
        request_hash = _hash(request_document)
        envelope_json = Jsonb(envelope.as_json())
        replayed = False
        lifecycle_lease = lease
        with self._connect() as conn:
            conn.execute("SET LOCAL synchronous_commit = on")
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"idempotency:{envelope.repository}:{idempotency_key}",),
            )
            existing = conn.execute(
                "SELECT request_hash, result FROM builderops_idempotency "
                "WHERE repository = %s AND idempotency_key = %s FOR UPDATE",
                (envelope.repository, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict(
                        "idempotency key was already committed for another request"
                    )
                provisional = self._result(existing["result"], replayed=True)
                if provisional.recovery_lsn != "0/0":
                    return provisional
                receipt_sequence = provisional.receipt_sequence
                operation_key = provisional.operation_key
                replayed = True
            else:
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"task:{envelope.repository}:{task_id}",),
                )
                if claim_holder is not None:
                    lifecycle_lease = self._claim_lease_in_tx(
                        conn,
                        envelope=envelope,
                        resource_id=task_id,
                        holder=claim_holder,
                        ttl_seconds=claim_ttl_seconds,
                        require_new_fence=require_new_fence,
                    )
                if lease is not None:
                    self._assert_lease(conn, envelope.repository, task_id, lease)
                    self._assert_task_lease_provenance(conn, envelope.repository, task_id, lease)
                previous = conn.execute(
                    "SELECT state, version FROM builderops_tasks "
                    "WHERE repository = %s AND task_id = %s FOR UPDATE",
                    (envelope.repository, task_id),
                ).fetchone()
                previous_state = str(previous["state"]) if previous is not None else None
                previous_version = (
                    int(previous["version"]) if previous is not None else None
                )
                if expected_states is not None and previous_state not in expected_states:
                    raise StateConflict(
                        f"expected task state in {expected_states!r}, observed {previous_state!r}"
                    )
                if (
                    expected_version is not None
                    and previous_version != expected_version
                ):
                    raise StateConflict(
                        f"expected task version {expected_version}, "
                        f"observed {previous_version}"
                    )
                if previous is not None and lease is None and claim_holder is None:
                    raise LeaseRequired("an existing task mutation requires a fenced lease")
                conn.execute(
                    "INSERT INTO builderops_tasks(repository, task_id, state, payload, authority_envelope) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (repository, task_id) DO UPDATE SET "
                    "state = EXCLUDED.state, payload = EXCLUDED.payload, authority_envelope = EXCLUDED.authority_envelope, "
                    "version = builderops_tasks.version + 1, updated_at = clock_timestamp()",
                    (envelope.repository, task_id, to_state, Jsonb(dict(request)), envelope_json),
                )
                self._fault(fault_at, "after_state")
                conn.execute(
                    "INSERT INTO builderops_transitions(repository, task_id, from_state, to_state, authority_envelope) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (
                        envelope.repository,
                        task_id,
                        previous_state,
                        to_state,
                        envelope_json,
                    ),
                )
                receipt = conn.execute(
                    "INSERT INTO builderops_receipts(repository, task_id, event_type, idempotency_key, "
                    "lease_holder, lease_fencing_token, authority_envelope) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING receipt_sequence",
                    (
                        envelope.repository,
                        task_id,
                        f"task.{to_state}",
                        idempotency_key,
                        lifecycle_lease.holder if lifecycle_lease else None,
                        lifecycle_lease.fencing_token if lifecycle_lease else None,
                        envelope_json,
                    ),
                ).fetchone()
                assert receipt is not None
                receipt_sequence = int(receipt["receipt_sequence"])
                self._fault(fault_at, "after_receipt")
                conn.execute(
                    "INSERT INTO builderops_idempotency(repository, idempotency_key, request_hash, authority_envelope) "
                    "VALUES (%s, %s, %s, %s)",
                    (envelope.repository, idempotency_key, request_hash, envelope_json),
                )
                self._fault(fault_at, "after_idempotency")
                operation_key = None
                if outbox is not None:
                    effect_type = str(outbox.get("effect_type", "")).strip()
                    if not effect_type:
                        raise ValueError("outbox effect_type is mandatory")
                    operation_key = _operation_key(
                        envelope.repository, idempotency_key, effect_type
                    )
                    conn.execute(
                        "INSERT INTO builderops_outbox(repository, operation_key, task_id, effect_type, payload, "
                        "intent_receipt_sequence, authority_envelope) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                        (
                            envelope.repository,
                            operation_key,
                            task_id,
                            effect_type,
                            Jsonb(dict(outbox.get("payload", {}))),
                            receipt_sequence,
                            envelope_json,
                        ),
                    )
                provisional = TransactionResult(
                    envelope.repository, task_id, to_state, receipt_sequence, "0/0", operation_key
                )
                result_document = self._result_json(provisional)
                if lifecycle_lease is not None:
                    result_document["lease"] = self._lease_json(lifecycle_lease)
                conn.execute(
                    "UPDATE builderops_idempotency SET result = %s WHERE repository = %s AND idempotency_key = %s",
                    (Jsonb(result_document), envelope.repository, idempotency_key),
                )
                if release_on_commit:
                    assert lease is not None
                    self._release_lease_in_tx(conn, repository=envelope.repository, lease=lease)
                self._fault(fault_at, "after_outbox")
        self._fault(fault_at, "after_commit")
        recovery_lsn = self._flushed_lsn()
        return self._finalize_transition(
            envelope.repository,
            idempotency_key,
            receipt_sequence,
            operation_key,
            recovery_lsn,
            replayed=replayed,
        )

    def _flushed_lsn(self) -> str:
        with self._connect() as conn:
            row = conn.execute("SELECT pg_current_wal_flush_lsn()::text AS lsn").fetchone()
        assert row is not None
        return str(row["lsn"])

    def _finalize_transition(
        self,
        repository: str,
        idempotency_key: str,
        receipt_sequence: int,
        operation_key: str | None,
        recovery_lsn: str,
        *,
        replayed: bool,
    ) -> TransactionResult:
        with self._connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"idempotency:{repository}:{idempotency_key}",),
            )
            row = conn.execute(
                "SELECT result FROM builderops_idempotency WHERE repository = %s AND idempotency_key = %s FOR UPDATE",
                (repository, idempotency_key),
            ).fetchone()
            if row is None:
                raise RuntimeError("committed idempotency record disappeared")
            provisional = self._result(row["result"], replayed=replayed)
            if provisional.recovery_lsn != "0/0":
                conn.execute(
                    "UPDATE builderops_receipts SET recovery_lsn = COALESCE(recovery_lsn, %s) "
                    "WHERE receipt_sequence = %s",
                    (provisional.recovery_lsn, provisional.receipt_sequence),
                )
                if provisional.operation_key is not None:
                    conn.execute(
                        "UPDATE builderops_outbox SET intent_lsn = COALESCE(intent_lsn, %s) "
                        "WHERE repository = %s AND operation_key = %s",
                        (
                            provisional.recovery_lsn,
                            repository,
                            provisional.operation_key,
                        ),
                    )
                return provisional
            result = TransactionResult(
                provisional.repository,
                provisional.task_id,
                provisional.state,
                receipt_sequence,
                recovery_lsn,
                operation_key,
                replayed,
            )
            result_document = self._result_json(result)
            if row["result"].get("lease") is not None:
                result_document["lease"] = row["result"]["lease"]
            conn.execute(
                "UPDATE builderops_receipts SET recovery_lsn = %s WHERE receipt_sequence = %s",
                (recovery_lsn, receipt_sequence),
            )
            conn.execute(
                "UPDATE builderops_idempotency SET result = %s, recovery_lsn = %s "
                "WHERE repository = %s AND idempotency_key = %s",
                (Jsonb(result_document), recovery_lsn, repository, idempotency_key),
            )
            if operation_key is not None:
                conn.execute(
                    "UPDATE builderops_outbox SET intent_lsn = %s WHERE repository = %s AND operation_key = %s",
                    (recovery_lsn, repository, operation_key),
                )
        return result

    @staticmethod
    def _fault(fault_at: str | None, point: str) -> None:
        if fault_at == point:
            raise RuntimeError(f"injected transaction fault at {point}")

    @staticmethod
    def _result_json(result: TransactionResult) -> dict[str, Any]:
        return {
            "repository": result.repository,
            "task_id": result.task_id,
            "state": result.state,
            "receipt_sequence": result.receipt_sequence,
            "recovery_lsn": result.recovery_lsn,
            "operation_key": result.operation_key,
        }

    @staticmethod
    def _authority_result_json(result: AuthorityObjectResult) -> dict[str, Any]:
        return {
            "result_type": "authority_object",
            "repository": result.repository,
            "object_kind": result.object_kind,
            "object_id": result.object_id,
            "state": result.state,
            "receipt_sequence": result.receipt_sequence,
            "recovery_lsn": result.recovery_lsn,
        }

    @staticmethod
    def _lease_json(lease: Lease) -> dict[str, Any]:
        return {
            "repository": lease.repository,
            "resource_id": lease.resource_id,
            "holder": lease.holder,
            "fencing_token": lease.fencing_token,
            "expires_at": lease.expires_at.isoformat(),
            "lease_kind": lease.lease_kind,
        }

    @staticmethod
    def _lease_identity_json(lease: Lease) -> dict[str, Any]:
        return {
            "repository": lease.repository,
            "resource_id": lease.resource_id,
            "holder": lease.holder,
            "fencing_token": lease.fencing_token,
            "lease_kind": lease.lease_kind,
        }

    @staticmethod
    def _lease(value: Mapping[str, Any]) -> Lease:
        return Lease(
            repository=str(value["repository"]),
            resource_id=str(value["resource_id"]),
            holder=str(value["holder"]),
            fencing_token=int(value["fencing_token"]),
            expires_at=datetime.fromisoformat(str(value["expires_at"])),
            lease_kind=str(value["lease_kind"]),
        )

    @staticmethod
    def _result(value: Mapping[str, Any], *, replayed: bool) -> TransactionResult:
        return TransactionResult(
            repository=str(value["repository"]),
            task_id=str(value["task_id"]),
            state=str(value["state"]),
            receipt_sequence=int(value["receipt_sequence"]),
            recovery_lsn=str(value["recovery_lsn"]),
            operation_key=str(value["operation_key"]) if value.get("operation_key") else None,
            replayed=replayed,
        )

    @staticmethod
    def _authority_result(value: Mapping[str, Any], *, replayed: bool) -> AuthorityObjectResult:
        return AuthorityObjectResult(
            repository=str(value["repository"]),
            object_kind=str(value["object_kind"]),
            object_id=str(value["object_id"]),
            state=str(value["state"]),
            receipt_sequence=int(value["receipt_sequence"]),
            recovery_lsn=str(value["recovery_lsn"]),
            replayed=replayed,
        )

    def commit_issue_delivery_operation_record(
        self,
        *,
        envelope: AuthorityEnvelope,
        record_id: str,
        state: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        operation_key: str,
        approval_id: str,
        approval_manifest_hash: str,
        capability: object,
        fault_at: str | None = None,
    ) -> AuthorityObjectResult:
        """Commit one destination-owned FCA-ID-B receipt.

        Reservation, attempt, and observed-entry records deliberately use the
        existing ``builderops_records`` authority table.  The additional
        operation/approval locks and binding scan run in the same transaction
        as the record write, so two destinations cannot win different record
        IDs for one operation or reuse one approval under a new key.
        """

        if capability is not _ISSUE_DELIVERY_OPERATION_CAPABILITY:
            raise StateConflict(
                "Issue-delivery operation records require the destination capability"
            )
        if envelope.scope != _ISSUE_DELIVERY_OPERATION_SCOPE:
            raise StateConflict(
                "Issue-delivery operation records require the destination scope"
            )
        if not operation_key or not approval_id or not approval_manifest_hash:
            raise ValueError("Issue-delivery operation binding is incomplete")
        if not isinstance(payload, Mapping):
            raise ValueError("Issue-delivery operation payload is required")
        binding = {
            "operation_key": operation_key,
            "approval_id": approval_id,
            "approval_manifest_hash": approval_manifest_hash,
        }
        if any(payload.get(key) != value for key, value in binding.items()):
            raise StateConflict(
                "Issue-delivery operation payload does not match its binding"
            )
        if not record_id.startswith("issue-delivery-") or ":" not in record_id:
            raise ValueError("Issue-delivery operation record id is malformed")
        record_kind, record_operation_key = record_id.removeprefix(
            "issue-delivery-"
        ).split(":", 1)
        if record_kind not in {"reservation", "attempt", "entry", "terminal"}:
            raise ValueError("Issue-delivery operation record kind is unsupported")
        if record_operation_key != operation_key:
            raise StateConflict(
                "Issue-delivery operation record id does not match its binding"
            )
        # ``BuilderOpsReceipt`` is fixed here; allowing a caller to select an
        # arbitrary record type would turn this finite adapter into a generic
        # authority writer.
        result = self._commit_authority_object(
            envelope=envelope,
            object_kind="record",
            object_id=record_id,
            state=state,
            payload=payload,
            idempotency_key=idempotency_key,
            secondary_id=_ISSUE_DELIVERY_OPERATION_RECORD_TYPE,
            lease=None,
            lease_resource_id=f"record:{record_id}",
            fault_at=fault_at,
            binding=binding,
        )
        return result

    def commit_record(
        self,
        *,
        envelope: AuthorityEnvelope,
        record_id: str,
        record_type: str,
        state: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        lease: Lease | None = None,
        expected_states: tuple[str, ...] | None = None,
        fault_at: str | None = None,
        owner_outcome: OwnerOutcomeAdmission | None = None,
        issue_delivery_admission: object | None = None,
    ) -> AuthorityObjectResult:
        from app.builderops.owner_fact_producers import OwnerFactRefusal

        _guard_idempotency_namespace(
            idempotency_key,
            envelope=envelope,
            object_kind="record",
            record_type=record_type,
        )
        if record_type == "IssueDeliveryApproval" and envelope.scope != "issue-delivery-approval":
            raise StateConflict("Issue-delivery approvals require exact owner admission")
        if envelope.scope == _ISSUE_DELIVERY_OPERATION_SCOPE or record_id.startswith(
            (
                "issue-delivery-reservation:",
                "issue-delivery-attempt:",
                "issue-delivery-entry:",
                "issue-delivery-terminal:",
            )
        ):
            raise StateConflict(
                "Issue-delivery operation records require the destination adapter"
            )
        if record_type == _ISSUE_DELIVERY_RECORD_TYPE and (
            issue_delivery_admission is not _ISSUE_DELIVERY_ADMISSION_CAPABILITY
        ):
            raise StateConflict(
                "Issue-delivery approvals require the service admission capability"
            )
        if owner_outcome is not None:
            return _commit_owner_outcome(self, envelope=envelope, admission=owner_outcome,
                                        idempotency_key=idempotency_key, fault_at=fault_at)
        if envelope.scope == "owner-outcome" or _is_owner_outcome(record_id, payload):
            raise OwnerFactRefusal("owner_confirmation_required", 403)
        return self._commit_authority_object(
            envelope=envelope,
            object_kind="record",
            object_id=record_id,
            state=state,
            payload=payload,
            idempotency_key=idempotency_key,
            secondary_id=record_type,
            lease=lease,
            lease_resource_id=f"record:{record_id}",
            expected_states=expected_states,
            fault_at=fault_at,
        )

    def get_owner_outcomes(
        self, repository: str, subject_ref: str, *, idempotency_key: str | None = None,
        grant_reader: Callable[[str, str], bool],
    ) -> dict[str, Any]:
        return _read_owner_outcomes(self, repository, subject_ref, idempotency_key=idempotency_key, grant_reader=grant_reader)

    def get_owner_asks(self, repository: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload, authority_envelope FROM builderops_records WHERE repository=%s "
                "AND record_type='BuilderOpsReceipt' AND record_id LIKE 'owner-ask:%%' "
                "AND (payload->'receipt_body'->'proposal'->'freshness'->>'expires_at')::timestamptz > clock_timestamp() LIMIT 65",
                (canonical_repository(repository),),
            ).fetchall()
        if len(rows) > 64:
            raise StateConflict("owner ask source collection is partial")
        return rows

    def commit_attempt(
        self,
        *,
        envelope: AuthorityEnvelope,
        task_id: str,
        attempt_id: str,
        state: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        lease: Lease,
        expected_states: tuple[str, ...] | None = None,
        expected_task_version: int | None = None,
        fault_at: str | None = None,
    ) -> AuthorityObjectResult:
        return self._commit_authority_object(
            envelope=envelope,
            object_kind="attempt",
            object_id=f"{task_id}:{attempt_id}",
            state=state,
            payload=payload,
            idempotency_key=idempotency_key,
            primary_id=task_id,
            secondary_id=attempt_id,
            lease=lease,
            lease_resource_id=task_id,
            require_lease_on_create=True,
            expected_states=expected_states,
            expected_task_version=expected_task_version,
            fault_at=fault_at,
        )

    def commit_promotion(
        self,
        *,
        envelope: AuthorityEnvelope,
        promotion_id: str,
        status: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        lease: Lease | None = None,
        expected_states: tuple[str, ...] | None = None,
        fault_at: str | None = None,
    ) -> AuthorityObjectResult:
        return self._commit_authority_object(
            envelope=envelope,
            object_kind="promotion",
            object_id=promotion_id,
            state=status,
            payload=payload,
            idempotency_key=idempotency_key,
            lease=lease,
            lease_resource_id=f"promotion:{promotion_id}",
            expected_states=expected_states,
            fault_at=fault_at,
        )

    def _commit_authority_object(
        self,
        *,
        envelope: AuthorityEnvelope,
        object_kind: str,
        object_id: str,
        state: str,
        payload: Mapping[str, Any],
        idempotency_key: str,
        primary_id: str | None = None,
        secondary_id: str | None = None,
        lease: Lease | None = None,
        lease_resource_id: str,
        require_lease_on_create: bool = False,
        expected_states: tuple[str, ...] | None = None,
        expected_task_version: int | None = None,
        fault_at: str | None = None,
        binding: Mapping[str, str] | None = None,
    ) -> AuthorityObjectResult:
        _guard_idempotency_namespace(
            idempotency_key,
            envelope=envelope,
            object_kind=object_kind,
            secondary_id=secondary_id,
        )
        if not object_id or not state or not idempotency_key:
            raise ValueError("object identity, state, and idempotency_key are mandatory")
        request_hash = _hash(
            {
                "authority_envelope": envelope.as_json(),
                "object_kind": object_kind,
                "object_id": object_id,
                "state": state,
                "payload": dict(payload),
                "primary_id": primary_id,
                "secondary_id": secondary_id,
                "lease_identity": self._lease_identity_json(lease) if lease is not None else None,
                "expected_states": list(expected_states) if expected_states is not None else None,
                "expected_task_version": expected_task_version,
            }
        )
        envelope_json = Jsonb(envelope.as_json())
        replayed = False
        with self._connect() as conn:
            conn.execute("SET LOCAL synchronous_commit = on")
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"idempotency:{envelope.repository}:{idempotency_key}",),
            )
            existing = conn.execute(
                "SELECT request_hash, result FROM builderops_idempotency "
                "WHERE repository = %s AND idempotency_key = %s FOR UPDATE",
                (envelope.repository, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict(
                        "idempotency key was already committed for another authority object"
                    )
                provisional = self._authority_result(existing["result"], replayed=True)
                if provisional.recovery_lsn != "0/0":
                    return provisional
                receipt_sequence = provisional.receipt_sequence
                replayed = True
            else:
                if binding is not None:
                    # Every operation record takes these locks in this order.
                    # They are intentionally separate from the record-id lock:
                    # a competing request may use a different reservation or
                    # entry id while still addressing the same operation.
                    operation_key = binding.get("operation_key")
                    approval_id = binding.get("approval_id")
                    manifest_hash = binding.get("approval_manifest_hash")
                    if not operation_key or not approval_id or not manifest_hash:
                        raise ValueError("Issue-delivery operation binding is incomplete")
                    conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (
                            f"issue-delivery-operation:{envelope.repository}:{operation_key}",
                        ),
                    )
                    conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (
                            f"issue-delivery-approval:{envelope.repository}:{approval_id}",
                        ),
                    )
                    bound = conn.execute(
                        "SELECT record_id, record_type, state, payload "
                        "FROM builderops_records WHERE repository = %s "
                        "AND (payload->>'operation_key' = %s "
                        "OR payload->>'approval_id' = %s) "
                        "ORDER BY record_id FOR UPDATE",
                        (envelope.repository, operation_key, approval_id),
                    ).fetchall()
                    for row in bound:
                        row_payload = row["payload"]
                        if not isinstance(row_payload, Mapping):
                            raise StateConflict(
                                "Issue-delivery operation binding is malformed"
                            )
                        if (
                            row_payload.get("operation_key") == operation_key
                            and row_payload.get("approval_id") == approval_id
                            and row_payload.get("approval_manifest_hash") == manifest_hash
                        ):
                            continue
                        # A durable approval record also carries operation_key;
                        # it is the source of truth for rejecting a changed
                        # operation or approval reuse.  Unrelated records are
                        # ignored unless they expose an operation binding.
                        if row_payload.get("operation_key") == operation_key:
                            raise IdempotencyConflict(
                                "Issue-delivery operation key is bound to another manifest"
                            )
                        if row_payload.get("approval_id") == approval_id:
                            raise IdempotencyConflict(
                                "Issue-delivery approval is already bound to another operation"
                            )
                conn.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                    (f"authority:{envelope.repository}:{object_kind}:{object_id}",),
                )
                if object_kind == "attempt":
                    assert primary_id is not None
                    conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        (f"task:{envelope.repository}:{primary_id}",),
                    )
                    task = conn.execute(
                        "SELECT state, version, payload FROM builderops_tasks WHERE repository = %s "
                        "AND task_id = %s FOR UPDATE",
                        (envelope.repository, primary_id),
                    ).fetchone()
                    if task is None or task["state"] != "claimed":
                        raise StateConflict("attempt writes require an existing claimed task")
                    if (
                        expected_task_version is not None
                        and int(task["version"]) != expected_task_version
                    ):
                        raise StateConflict(
                            f"expected task version {expected_task_version}, "
                            f"observed {int(task['version'])}"
                        )
                    task_payload = task["payload"]
                    seal = (
                        task_payload.get("attempt_write_seal")
                        if isinstance(task_payload, Mapping)
                        else None
                    )
                    if seal is not None:
                        if (
                            not isinstance(seal, Mapping)
                            or seal.get("contract")
                            != "builderops_attempt_write_seal.v1"
                            or not isinstance(
                                seal.get("operation_key"), str
                            )
                            or seal.get("effect_type")
                            not in {
                                "github.merge",
                                "github.merge.dry_run",
                            }
                        ):
                            raise StateConflict(
                                "task attempt-write seal is malformed"
                            )
                        sealed_effect = conn.execute(
                            "SELECT task_id, effect_type, status "
                            "FROM builderops_outbox WHERE repository = %s "
                            "AND operation_key = %s",
                            (
                                envelope.repository,
                                seal["operation_key"],
                            ),
                        ).fetchone()
                        if (
                            sealed_effect is None
                            or sealed_effect["task_id"] != primary_id
                            or sealed_effect["effect_type"]
                            != seal["effect_type"]
                        ):
                            raise StateConflict(
                                "task attempt-write seal is not bound to its "
                                "privileged merge intent"
                            )
                        raise StateConflict(
                            "attempt writes are sealed by privileged "
                            "merge authority"
                        )
                previous = self._authority_object_row(
                    conn,
                    object_kind=object_kind,
                    repository=envelope.repository,
                    object_id=object_id,
                    primary_id=primary_id,
                    secondary_id=secondary_id,
                    for_update=True,
                )
                previous_state = str(previous["state"]) if previous is not None else None
                if expected_states is not None and previous_state not in expected_states:
                    raise StateConflict(
                        f"expected {object_kind} state in {expected_states!r}, "
                        f"observed {previous_state!r}"
                    )
                if previous is not None and object_kind == "record":
                    assert secondary_id is not None
                    if previous["record_type"] != secondary_id:
                        raise StateConflict("record type is immutable")
                if previous is not None or require_lease_on_create:
                    if lease is None:
                        raise LeaseRequired(f"{object_kind} mutation requires a fenced lease")
                    self._assert_lease(
                        conn,
                        envelope.repository,
                        lease_resource_id,
                        lease,
                        lease_kind="task" if object_kind == "attempt" else "generic",
                    )
                    if object_kind == "attempt":
                        assert primary_id is not None
                        self._assert_task_lease_provenance(
                            conn, envelope.repository, primary_id, lease
                        )
                        conn.execute(
                            "UPDATE builderops_tasks SET version = version + 1, "
                            "updated_at = clock_timestamp() "
                            "WHERE repository = %s AND task_id = %s",
                            (envelope.repository, primary_id),
                        )
                self._write_authority_object(
                    conn,
                    envelope=envelope,
                    object_kind=object_kind,
                    object_id=object_id,
                    state=state,
                    payload=payload,
                    primary_id=primary_id,
                    secondary_id=secondary_id,
                )
                self._fault(fault_at, "after_authority_object")
                receipt_task_id = primary_id or object_id
                receipt = conn.execute(
                    "INSERT INTO builderops_receipts(repository, task_id, event_type, "
                    "idempotency_key, lease_holder, lease_fencing_token, authority_envelope) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING receipt_sequence",
                    (
                        envelope.repository,
                        receipt_task_id,
                        f"{object_kind}.{state}",
                        idempotency_key,
                        lease.holder if lease else None,
                        lease.fencing_token if lease else None,
                        envelope_json,
                    ),
                ).fetchone()
                assert receipt is not None
                receipt_sequence = int(receipt["receipt_sequence"])
                self._fault(fault_at, "after_authority_receipt")
                provisional = AuthorityObjectResult(
                    repository=envelope.repository,
                    object_kind=object_kind,
                    object_id=object_id,
                    state=state,
                    receipt_sequence=receipt_sequence,
                    recovery_lsn="0/0",
                )
                conn.execute(
                    "INSERT INTO builderops_idempotency(repository, idempotency_key, request_hash, "
                    "result, authority_envelope) VALUES (%s, %s, %s, %s, %s)",
                    (
                        envelope.repository,
                        idempotency_key,
                        request_hash,
                        Jsonb(self._authority_result_json(provisional)),
                        envelope_json,
                    ),
                )
                self._fault(fault_at, "after_authority_idempotency")
        self._fault(fault_at, "after_authority_commit")
        recovery_lsn = self._flushed_lsn()
        return self._finalize_authority_object(
            envelope.repository,
            idempotency_key,
            receipt_sequence,
            recovery_lsn,
            replayed=replayed,
        )

    @staticmethod
    def _authority_object_row(
        conn: psycopg.Connection[dict[str, Any]],
        *,
        object_kind: str,
        repository: str,
        object_id: str,
        primary_id: str | None,
        secondary_id: str | None,
        for_update: bool,
    ) -> Mapping[str, Any] | None:
        lock = " FOR UPDATE" if for_update else ""
        if object_kind == "record":
            return conn.execute(
                "SELECT state, record_type, payload, authority_envelope FROM builderops_records "
                f"WHERE repository = %s AND record_id = %s{lock}",
                (repository, object_id),
            ).fetchone()
        if object_kind == "attempt":
            return conn.execute(
                "SELECT state, payload, authority_envelope FROM builderops_attempts "
                f"WHERE repository = %s AND task_id = %s AND attempt_id = %s{lock}",
                (repository, primary_id, secondary_id),
            ).fetchone()
        if object_kind == "promotion":
            return conn.execute(
                "SELECT status AS state, payload, authority_envelope FROM builderops_promotions "
                f"WHERE repository = %s AND promotion_id = %s{lock}",
                (repository, object_id),
            ).fetchone()
        raise ValueError(f"unsupported authority object kind: {object_kind}")

    @staticmethod
    def _write_authority_object(
        conn: psycopg.Connection[dict[str, Any]],
        *,
        envelope: AuthorityEnvelope,
        object_kind: str,
        object_id: str,
        state: str,
        payload: Mapping[str, Any],
        primary_id: str | None,
        secondary_id: str | None,
    ) -> None:
        envelope_json = Jsonb(envelope.as_json())
        if object_kind == "record":
            assert secondary_id is not None
            conn.execute(
                "INSERT INTO builderops_records(repository, record_id, record_type, state, payload, "
                "authority_envelope) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (repository, record_id) DO UPDATE SET state = EXCLUDED.state, "
                "payload = EXCLUDED.payload, authority_envelope = EXCLUDED.authority_envelope",
                (
                    envelope.repository,
                    object_id,
                    secondary_id,
                    state,
                    Jsonb(dict(payload)),
                    envelope_json,
                ),
            )
            return
        if object_kind == "attempt":
            conn.execute(
                "INSERT INTO builderops_attempts(repository, task_id, attempt_id, state, payload, "
                "authority_envelope) VALUES (%s, %s, %s, %s, %s, %s) "
                "ON CONFLICT (repository, task_id, attempt_id) DO UPDATE SET state = EXCLUDED.state, "
                "payload = EXCLUDED.payload, authority_envelope = EXCLUDED.authority_envelope, "
                "updated_at = clock_timestamp()",
                (
                    envelope.repository,
                    primary_id,
                    secondary_id,
                    state,
                    Jsonb(dict(payload)),
                    envelope_json,
                ),
            )
            return
        if object_kind == "promotion":
            conn.execute(
                "INSERT INTO builderops_promotions(repository, promotion_id, status, payload, "
                "authority_envelope) VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (repository, promotion_id) DO UPDATE SET status = EXCLUDED.status, "
                "payload = EXCLUDED.payload, authority_envelope = EXCLUDED.authority_envelope, "
                "updated_at = clock_timestamp()",
                (
                    envelope.repository,
                    object_id,
                    state,
                    Jsonb(dict(payload)),
                    envelope_json,
                ),
            )
            return
        raise ValueError(f"unsupported authority object kind: {object_kind}")

    def _finalize_authority_object(
        self,
        repository: str,
        idempotency_key: str,
        receipt_sequence: int,
        recovery_lsn: str,
        *,
        replayed: bool,
    ) -> AuthorityObjectResult:
        with self._connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"idempotency:{repository}:{idempotency_key}",),
            )
            row = conn.execute(
                "SELECT result FROM builderops_idempotency WHERE repository = %s "
                "AND idempotency_key = %s FOR UPDATE",
                (repository, idempotency_key),
            ).fetchone()
            if row is None:
                raise RuntimeError("committed authority-object idempotency record disappeared")
            provisional = self._authority_result(row["result"], replayed=replayed)
            if provisional.recovery_lsn != "0/0":
                return provisional
            result = AuthorityObjectResult(
                repository=provisional.repository,
                object_kind=provisional.object_kind,
                object_id=provisional.object_id,
                state=provisional.state,
                receipt_sequence=receipt_sequence,
                recovery_lsn=recovery_lsn,
                replayed=replayed,
            )
            conn.execute(
                "UPDATE builderops_receipts SET recovery_lsn = %s WHERE receipt_sequence = %s",
                (recovery_lsn, receipt_sequence),
            )
            conn.execute(
                "UPDATE builderops_idempotency SET result = %s, recovery_lsn = %s "
                "WHERE repository = %s AND idempotency_key = %s",
                (
                    Jsonb(self._authority_result_json(result)),
                    recovery_lsn,
                    repository,
                    idempotency_key,
                ),
            )
        return result

    def get_record(self, repository: str, record_id: str) -> Mapping[str, Any]:
        repository = canonical_repository(repository)
        with self._connect() as conn:
            row = self._authority_object_row(
                conn,
                object_kind="record",
                repository=repository,
                object_id=record_id,
                primary_id=None,
                secondary_id=None,
                for_update=False,
            )
        if row is None:
            raise KeyError(record_id)
        return dict(row)

    def get_issue_delivery_by_operation_key(
        self, repository: str, operation_key: str
    ) -> Mapping[str, Any] | None:
        """Read the unique FCA-ID-A approval bound to ``operation_key``.

        This lookup is deliberately a narrow projection over the existing
        record owner.  It prevents a fresh approval id from reusing an
        already admitted operation key without adding another authority table.
        """

        repository = canonical_repository(repository)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT record_id, record_type, state, payload, authority_envelope "
                "FROM builderops_records WHERE repository = %s "
                "AND record_type = 'IssueDeliveryApproval' "
                "AND payload->>'operation_key' = %s LIMIT 2",
                (repository, operation_key),
            ).fetchall()
        if len(rows) > 1:
            raise StateConflict("Issue-delivery operation key is not unique")
        return dict(rows[0]) if rows else None

    def get_attempt(self, repository: str, task_id: str, attempt_id: str) -> Mapping[str, Any]:
        repository = canonical_repository(repository)
        with self._connect() as conn:
            row = self._authority_object_row(
                conn,
                object_kind="attempt",
                repository=repository,
                object_id=f"{task_id}:{attempt_id}",
                primary_id=task_id,
                secondary_id=attempt_id,
                for_update=False,
            )
        if row is None:
            raise KeyError(attempt_id)
        return dict(row)

    def get_promotion(self, repository: str, promotion_id: str) -> Mapping[str, Any]:
        repository = canonical_repository(repository)
        with self._connect() as conn:
            row = self._authority_object_row(
                conn,
                object_kind="promotion",
                repository=repository,
                object_id=promotion_id,
                primary_id=None,
                secondary_id=None,
                for_update=False,
            )
        if row is None:
            raise KeyError(promotion_id)
        return dict(row)

    def replay(
        self, repository: str, idempotency_key: str
    ) -> TransactionResult | AuthorityObjectResult | None:
        repository = canonical_repository(repository)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT result, recovery_lsn::text AS recovery_lsn FROM builderops_idempotency "
                "WHERE repository = %s AND idempotency_key = %s",
                (repository, idempotency_key),
            ).fetchone()
        if row is None or row["result"] is None:
            return None
        if row["result"].get("result_type") == "authority_object":
            authority_result = self._authority_result(
                row["result"], replayed=True
            )
            if authority_result.recovery_lsn == "0/0":
                return self._finalize_authority_object(
                    repository,
                    idempotency_key,
                    authority_result.receipt_sequence,
                    self._flushed_lsn(),
                    replayed=True,
                )
            return authority_result
        transaction_result = self._result(row["result"], replayed=True)
        if transaction_result.recovery_lsn == "0/0":
            return self._finalize_transition(
                repository,
                idempotency_key,
                transaction_result.receipt_sequence,
                transaction_result.operation_key,
                self._flushed_lsn(),
                replayed=True,
            )
        return transaction_result

    def _repair_outbox_bindings(self, repository: str, operation_key: str) -> None:
        """Finish local observability bindings left incomplete by a lost response."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT outbox.intent_lsn::text AS intent_lsn, "
                "outbox.intent_receipt_sequence, receipt.idempotency_key, "
                "outbox.claim_fencing_token, outbox.reconciliation_receipt_sequence, "
                "outbox.reconciliation_lsn::text AS reconciliation_lsn "
                "FROM builderops_outbox AS outbox "
                "LEFT JOIN builderops_receipts AS receipt "
                "ON receipt.receipt_sequence = outbox.intent_receipt_sequence "
                "WHERE outbox.repository = %s AND outbox.operation_key = %s",
                (repository, operation_key),
            ).fetchone()
        if row is None:
            return
        if row["intent_lsn"] is None:
            if not row["idempotency_key"]:
                raise DurabilityPending("outbox intent has no local idempotency binding")
            self._finalize_transition(
                repository,
                str(row["idempotency_key"]),
                int(row["intent_receipt_sequence"]),
                operation_key,
                self._flushed_lsn(),
                replayed=True,
            )
        if (
            row["reconciliation_receipt_sequence"] is not None
            and row["reconciliation_lsn"] is None
        ):
            self._finalize_reconciliation(
                repository,
                operation_key,
                int(row["claim_fencing_token"]),
                int(row["reconciliation_receipt_sequence"]),
                self._flushed_lsn(),
                replayed=True,
            )

    def claim_task(
        self,
        *,
        envelope: AuthorityEnvelope,
        task_id: str,
        holder: str,
        idempotency_key: str,
        request: Mapping[str, Any],
        ttl_seconds: int = 5400,
        require_new_fence: bool = False,
        fault_at: str | None = None,
    ) -> tuple[TransactionResult, Lease]:
        """Atomically bind task state, receipt, idempotency, and fenced ownership."""
        result = self._commit_transition(
            envelope=envelope,
            task_id=task_id,
            to_state="claimed",
            idempotency_key=idempotency_key,
            request=request,
            claim_holder=holder,
            claim_ttl_seconds=ttl_seconds,
            require_new_fence=require_new_fence,
            expected_states=("ready", "claimed"),
            fault_at=fault_at,
        )
        with self._connect() as conn:
            row = conn.execute(
                "SELECT result FROM builderops_idempotency "
                "WHERE repository = %s AND idempotency_key = %s",
                (envelope.repository, idempotency_key),
            ).fetchone()
        if row is None or row["result"].get("lease") is None:
            raise RuntimeError("claimed task result is missing its fenced lease binding")
        persisted_lease = self._lease(row["result"]["lease"])
        if (
            persisted_lease.holder != holder
            or persisted_lease.resource_id != task_id
            or persisted_lease.lease_kind != "task"
        ):
            raise IdempotencyConflict("claim result belongs to another holder or task")
        return result, persisted_lease

    def release_task(
        self,
        *,
        envelope: AuthorityEnvelope,
        lease: Lease,
        idempotency_key: str,
        request: Mapping[str, Any],
        expected_version: int | None = None,
        fault_at: str | None = None,
    ) -> TransactionResult:
        """Atomically return task state and terminate the exact fenced ownership."""
        return self._commit_transition(
            envelope=envelope,
            task_id=lease.resource_id,
            to_state="ready",
            idempotency_key=idempotency_key,
            request=request,
            lease=lease,
            release_on_commit=True,
            expected_states=("claimed",),
            expected_version=expected_version,
            fault_at=fault_at,
        )

    def complete_task(
        self,
        *,
        envelope: AuthorityEnvelope,
        lease: Lease,
        idempotency_key: str,
        request: Mapping[str, Any],
        expected_version: int | None = None,
        fault_at: str | None = None,
    ) -> TransactionResult:
        """Atomically record terminal state/receipt and terminate ownership."""
        return self._commit_transition(
            envelope=envelope,
            task_id=lease.resource_id,
            to_state="completed",
            idempotency_key=idempotency_key,
            request=request,
            lease=lease,
            release_on_commit=True,
            expected_states=("claimed",),
            expected_version=expected_version,
            fault_at=fault_at,
        )

    def claim_lease(
        self,
        *,
        envelope: AuthorityEnvelope,
        resource_id: str,
        holder: str,
        idempotency_key: str,
        request: Mapping[str, Any],
        ttl_seconds: int = 5400,
        fault_at: str | None = None,
    ) -> tuple[TransactionResult, Lease]:
        return self._commit_lease_operation(
            envelope=envelope,
            operation="claimed",
            resource_id=resource_id,
            holder=holder,
            idempotency_key=idempotency_key,
            request=request,
            ttl_seconds=ttl_seconds,
            fault_at=fault_at,
        )

    def heartbeat_lease(
        self,
        *,
        envelope: AuthorityEnvelope,
        lease: Lease,
        idempotency_key: str,
        request: Mapping[str, Any],
        ttl_seconds: int,
        fault_at: str | None = None,
    ) -> tuple[TransactionResult, Lease]:
        return self._commit_lease_operation(
            envelope=envelope,
            operation="heartbeat",
            resource_id=lease.resource_id,
            holder=lease.holder,
            idempotency_key=idempotency_key,
            request=request,
            ttl_seconds=ttl_seconds,
            lease=lease,
            fault_at=fault_at,
        )

    def release_lease(
        self,
        *,
        envelope: AuthorityEnvelope,
        lease: Lease,
        idempotency_key: str,
        request: Mapping[str, Any],
        fault_at: str | None = None,
    ) -> TransactionResult:
        if lease.lease_kind != "generic":
            raise ValueError("generic release cannot terminate task ownership")
        result, _ = self._commit_lease_operation(
            envelope=envelope,
            operation="released",
            resource_id=lease.resource_id,
            holder=lease.holder,
            idempotency_key=idempotency_key,
            request=request,
            lease=lease,
            fault_at=fault_at,
        )
        return result

    def _commit_lease_operation(
        self,
        *,
        envelope: AuthorityEnvelope,
        operation: str,
        resource_id: str,
        holder: str,
        idempotency_key: str,
        request: Mapping[str, Any],
        ttl_seconds: int | None = None,
        lease: Lease | None = None,
        fault_at: str | None = None,
    ) -> tuple[TransactionResult, Lease]:
        _guard_idempotency_namespace(idempotency_key, envelope=envelope)
        if (
            not resource_id
            or not holder
            or not idempotency_key
            or operation not in {"claimed", "heartbeat", "released"}
        ):
            raise ValueError(
                "resource_id, holder, idempotency_key, and a valid lease operation are mandatory"
            )
        if operation != "released" and (ttl_seconds is None or ttl_seconds <= 0):
            raise ValueError("positive ttl_seconds is mandatory")
        if operation == "claimed" and lease is not None:
            raise ValueError("claim cannot supply an existing lease")
        if operation != "claimed" and lease is None:
            raise ValueError("heartbeat/release require an existing lease")
        if lease is not None and lease.repository != envelope.repository:
            raise EnvelopeValidationError(
                "lease repository must match the authority envelope repository"
            )
        request_hash = _hash(
            {
                "authority_envelope": envelope.as_json(),
                "operation": operation,
                "resource_id": resource_id,
                "holder": holder,
                "ttl_seconds": ttl_seconds,
                "lease_identity": self._lease_identity_json(lease) if lease else None,
                "request": dict(request),
            }
        )
        envelope_json = Jsonb(envelope.as_json())
        replayed = False
        with self._connect() as conn:
            conn.execute("SET LOCAL synchronous_commit = on")
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"idempotency:{envelope.repository}:{idempotency_key}",),
            )
            existing = conn.execute(
                "SELECT request_hash, result FROM builderops_idempotency "
                "WHERE repository = %s AND idempotency_key = %s FOR UPDATE",
                (envelope.repository, idempotency_key),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict(
                        "lease idempotency key was already committed for another operation"
                    )
                provisional = self._result(existing["result"], replayed=True)
                persisted_lease = self._lease(existing["result"]["lease"])
                if provisional.recovery_lsn != "0/0":
                    return provisional, persisted_lease
                receipt_sequence = provisional.receipt_sequence
                operation_lease = persisted_lease
                replayed = True
            else:
                if operation == "claimed":
                    assert ttl_seconds is not None
                    operation_lease = self._claim_lease_in_tx(
                        conn,
                        envelope=envelope,
                        resource_id=resource_id,
                        holder=holder,
                        ttl_seconds=ttl_seconds,
                        lease_kind="generic",
                    )
                elif operation == "heartbeat":
                    assert lease is not None and ttl_seconds is not None
                    operation_lease = self._heartbeat_lease_in_tx(
                        conn,
                        repository=envelope.repository,
                        lease=lease,
                        ttl_seconds=ttl_seconds,
                    )
                else:
                    assert lease is not None
                    self._release_lease_in_tx(conn, repository=envelope.repository, lease=lease)
                    operation_lease = lease
                self._fault(fault_at, "after_lease_mutation")
                receipt = conn.execute(
                    "INSERT INTO builderops_receipts(repository, task_id, event_type, "
                    "idempotency_key, lease_holder, lease_fencing_token, authority_envelope) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING receipt_sequence",
                    (
                        envelope.repository,
                        resource_id,
                        f"lease.{operation}",
                        idempotency_key,
                        operation_lease.holder,
                        operation_lease.fencing_token,
                        envelope_json,
                    ),
                ).fetchone()
                assert receipt is not None
                receipt_sequence = int(receipt["receipt_sequence"])
                self._fault(fault_at, "after_lease_receipt")
                provisional = TransactionResult(
                    repository=envelope.repository,
                    task_id=resource_id,
                    state=f"lease.{operation}",
                    receipt_sequence=receipt_sequence,
                    recovery_lsn="0/0",
                    operation_key=None,
                )
                result_document = self._result_json(provisional)
                result_document["lease"] = self._lease_json(operation_lease)
                conn.execute(
                    "INSERT INTO builderops_idempotency(repository, idempotency_key, request_hash, "
                    "result, authority_envelope) VALUES (%s, %s, %s, %s, %s)",
                    (
                        envelope.repository,
                        idempotency_key,
                        request_hash,
                        Jsonb(result_document),
                        envelope_json,
                    ),
                )
                self._fault(fault_at, "after_lease_idempotency")
        self._fault(fault_at, "after_lease_commit")
        recovery_lsn = self._flushed_lsn()
        result = self._finalize_transition(
            envelope.repository,
            idempotency_key,
            receipt_sequence,
            None,
            recovery_lsn,
            replayed=replayed,
        )
        return result, operation_lease

    @staticmethod
    def _claim_lease_in_tx(
        conn: psycopg.Connection[dict[str, Any]],
        *,
        envelope: AuthorityEnvelope,
        resource_id: str,
        holder: str,
        ttl_seconds: int,
        lease_kind: str = "task",
        require_new_fence: bool = False,
    ) -> Lease:
        if not resource_id or not holder or ttl_seconds <= 0:
            raise ValueError("resource_id, holder, and positive ttl_seconds are mandatory")
        if lease_kind not in {"task", "generic"}:
            raise ValueError("lease_kind must be task or generic")
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"lease:{envelope.repository}:{lease_kind}:{resource_id}",),
        )
        row = conn.execute(
            "SELECT holder, fencing_token, expires_at FROM builderops_leases "
            "WHERE repository = %s AND lease_kind = %s AND resource_id = %s FOR UPDATE",
            (envelope.repository, lease_kind, resource_id),
        ).fetchone()
        effective_now = PostgresBuilderOpsStore._database_now(conn)
        expires_at = effective_now + timedelta(seconds=ttl_seconds)
        if row is not None and row["expires_at"] > effective_now:
            if require_new_fence:
                raise LeaseUnavailable(
                    "active lease must expire before a recovery claim"
                )
            if row["holder"] != holder:
                raise LeaseUnavailable(f"active lease belongs to {row['holder']}")
            return Lease(
                envelope.repository,
                resource_id,
                holder,
                int(row["fencing_token"]),
                row["expires_at"],
                lease_kind,
            )
        token = int(row["fencing_token"]) + 1 if row else 1
        conn.execute(
            "INSERT INTO builderops_leases(repository, lease_kind, resource_id, holder, fencing_token, "
            "expires_at, authority_envelope) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (repository, lease_kind, resource_id) DO UPDATE SET "
            "holder = EXCLUDED.holder, fencing_token = EXCLUDED.fencing_token, expires_at = EXCLUDED.expires_at, "
            "authority_envelope = EXCLUDED.authority_envelope, updated_at = clock_timestamp()",
            (
                envelope.repository,
                lease_kind,
                resource_id,
                holder,
                token,
                expires_at,
                Jsonb(envelope.as_json()),
            ),
        )
        return Lease(envelope.repository, resource_id, holder, token, expires_at, lease_kind)

    @staticmethod
    def _heartbeat_lease_in_tx(
        conn: psycopg.Connection[dict[str, Any]],
        *,
        repository: str,
        lease: Lease,
        ttl_seconds: int,
    ) -> Lease:
        if ttl_seconds <= 0:
            raise ValueError("positive ttl_seconds is mandatory")
        if lease.repository != repository:
            raise EnvelopeValidationError(
                "lease repository must match the authority envelope repository"
            )
        current = conn.execute(
            "SELECT holder, fencing_token, expires_at FROM builderops_leases "
            "WHERE repository = %s AND lease_kind = %s AND resource_id = %s FOR UPDATE",
            (repository, lease.lease_kind, lease.resource_id),
        ).fetchone()
        effective_now = PostgresBuilderOpsStore._database_now(conn)
        expires_at = effective_now + timedelta(seconds=ttl_seconds)
        if (
            current is None
            or current["holder"] != lease.holder
            or int(current["fencing_token"]) != lease.fencing_token
            or current["expires_at"] <= effective_now
        ):
            raise StaleFencingToken("lease expired or was reassigned")
        updated = conn.execute(
            "UPDATE builderops_leases SET expires_at = %s, updated_at = clock_timestamp() "
            "WHERE repository = %s AND lease_kind = %s AND resource_id = %s "
            "AND holder = %s AND fencing_token = %s "
            "AND expires_at > %s RETURNING resource_id",
            (
                expires_at,
                repository,
                lease.lease_kind,
                lease.resource_id,
                lease.holder,
                lease.fencing_token,
                effective_now,
            ),
        ).fetchone()
        if updated is None:
            raise StaleFencingToken("lease expired or was reassigned")
        return Lease(
            repository,
            lease.resource_id,
            lease.holder,
            lease.fencing_token,
            expires_at,
            lease.lease_kind,
        )

    @staticmethod
    def _release_lease_in_tx(
        conn: psycopg.Connection[dict[str, Any]], *, repository: str, lease: Lease
    ) -> None:
        if lease.repository != repository:
            raise EnvelopeValidationError(
                "lease repository must match the authority envelope repository"
            )
        current = conn.execute(
            "SELECT holder, fencing_token, expires_at FROM builderops_leases "
            "WHERE repository = %s AND lease_kind = %s AND resource_id = %s FOR UPDATE",
            (repository, lease.lease_kind, lease.resource_id),
        ).fetchone()
        effective_now = PostgresBuilderOpsStore._database_now(conn)
        if (
            current is None
            or current["holder"] != lease.holder
            or int(current["fencing_token"]) != lease.fencing_token
            or current["expires_at"] <= effective_now
        ):
            raise StaleFencingToken("lease expired, was released, or was reassigned")
        row = conn.execute(
            "UPDATE builderops_leases SET expires_at = %s, updated_at = clock_timestamp() "
            "WHERE repository = %s AND lease_kind = %s AND resource_id = %s "
            "AND holder = %s AND fencing_token = %s "
            "AND expires_at > %s RETURNING resource_id",
            (
                effective_now,
                repository,
                lease.lease_kind,
                lease.resource_id,
                lease.holder,
                lease.fencing_token,
                effective_now,
            ),
        ).fetchone()
        if row is None:
            raise StaleFencingToken("lease expired, was released, or was reassigned")

    @staticmethod
    def _assert_lease(
        conn: psycopg.Connection[dict[str, Any]],
        repository: str,
        resource_id: str,
        lease: Lease,
        lease_kind: str = "task",
    ) -> None:
        if lease.lease_kind != lease_kind:
            raise LeaseRequired(f"{lease_kind} mutation requires matching lease provenance")
        row = conn.execute(
            "SELECT holder, fencing_token, expires_at FROM builderops_leases "
            "WHERE repository = %s AND lease_kind = %s AND resource_id = %s FOR UPDATE",
            (repository, lease_kind, resource_id),
        ).fetchone()
        effective_now = PostgresBuilderOpsStore._database_now(conn)
        if (
            row is None
            or lease.repository != repository
            or lease.resource_id != resource_id
            or row["holder"] != lease.holder
            or int(row["fencing_token"]) != lease.fencing_token
            or row["expires_at"] <= effective_now
        ):
            raise StaleFencingToken("lease expired or fencing token is stale")

    @staticmethod
    def _assert_task_lease_provenance(
        conn: psycopg.Connection[dict[str, Any]],
        repository: str,
        task_id: str,
        lease: Lease,
    ) -> None:
        receipt = conn.execute(
            "SELECT 1 FROM builderops_receipts "
            "WHERE repository = %s AND task_id = %s AND event_type = 'task.claimed' "
            "AND lease_holder = %s AND lease_fencing_token = %s LIMIT 1",
            (repository, task_id, lease.holder, lease.fencing_token),
        ).fetchone()
        if receipt is None:
            raise LeaseRequired("task mutation requires lease provenance from an atomic task claim")

    def claim_outbox(
        self,
        *,
        envelope: AuthorityEnvelope,
        operation_key: str | None,
        worker_id: str,
        claim_ttl_seconds: int = 300,
        fault_at: str | None = None,
    ) -> OutboxClaim:
        if not operation_key or not worker_id or claim_ttl_seconds <= 0:
            raise ValueError(
                "operation_key, worker_id, and positive claim_ttl_seconds are mandatory"
            )
        self._repair_outbox_bindings(envelope.repository, operation_key)
        expired_attempt = False
        with self._connect() as conn:
            conn.execute("SET LOCAL synchronous_commit = on")
            self._assert_executor_enabled(conn)
            row = conn.execute(
                "SELECT task_id, status, intent_receipt_sequence, intent_lsn::text AS intent_lsn, "
                "claim_fencing_token, claim_expires_at, post_effect_phase, reconciliation_receipt_sequence, "
                "reconciliation_lsn::text AS reconciliation_lsn "
                "FROM builderops_outbox WHERE repository = %s AND operation_key = %s FOR UPDATE",
                (envelope.repository, operation_key),
            ).fetchone()
            if row is None:
                raise KeyError(operation_key)
            if row["status"] == "unknown":
                raise UnknownEffectNeedsReconciliation(
                    "external effect outcome is unknown; readback required"
                )
            if row["status"] == "succeeded":
                self._load_reconciliation(
                    conn,
                    envelope.repository,
                    operation_key,
                    int(row["claim_fencing_token"]),
                )
                raise LeaseUnavailable("outbox operation is terminal: succeeded")
            if row["status"] == "dead_letter":
                raise LeaseUnavailable("outbox operation is terminal: dead_letter")
            if row["status"] == "pending" and row["post_effect_phase"] == "pending":
                raise LeaseUnavailable("row-derived post-effect reconciliation must finish before reclaim")
            if row["status"] == "pending" and row["reconciliation_receipt_sequence"] is not None:
                self._load_reconciliation(
                    conn,
                    envelope.repository,
                    operation_key,
                    int(row["claim_fencing_token"]),
                )
            if row["intent_lsn"] is None:
                raise DurabilityPending("outbox intent durability binding is incomplete")
            effective_now = self._database_now(conn)
            if row["status"] == "claimed":
                if row["claim_expires_at"] and row["claim_expires_at"] > effective_now:
                    raise LeaseUnavailable("outbox operation already has an active claim")
                conn.execute(
                    "UPDATE builderops_outbox SET status = 'unknown', "
                    "unknown_detail = 'pre-effect claim expired; external readback required', "
                    "updated_at = clock_timestamp() WHERE repository = %s AND operation_key = %s",
                    (envelope.repository, operation_key),
                )
                expired_attempt = True
            else:
                token = int(row["claim_fencing_token"]) + 1
                expires_at = effective_now + timedelta(seconds=claim_ttl_seconds)
                receipt = conn.execute(
                    "INSERT INTO builderops_receipts(repository, task_id, event_type, idempotency_key, "
                    "lease_holder, lease_fencing_token, authority_envelope) "
                    "VALUES (%s, %s, 'outbox.claimed', %s, %s, %s, %s) "
                    "RETURNING receipt_sequence",
                    (
                        envelope.repository,
                        row["task_id"],
                        f"outbox:{operation_key}:claim:{token}",
                        worker_id,
                        token,
                        Jsonb(envelope.as_json()),
                    ),
                ).fetchone()
                assert receipt is not None
                receipt_sequence = int(receipt["receipt_sequence"])
                conn.execute(
                    "UPDATE builderops_outbox SET status = 'claimed', worker_id = %s, claim_fencing_token = %s, "
                    "claim_expires_at = %s, claim_lsn = NULL, claim_receipt_sequence = %s, "
                    "post_effect_phase = NULL, post_effect_fencing_token = NULL, "
                    "post_effect_intent_lsn = NULL, post_effect_claim_lsn = NULL, "
                    "post_effect_claim_receipt_sequence = NULL, post_effect_receipt_sequence = NULL, "
                    "post_effect_recovery_lsn = NULL, post_effect_evidence = NULL, "
                    "post_effect_observed_applied = NULL, post_effect_terminal_unknown = NULL, "
                    "authority_envelope = %s, "
                    "updated_at = clock_timestamp() WHERE repository = %s AND operation_key = %s",
                    (
                        worker_id,
                        token,
                        expires_at,
                        receipt_sequence,
                        Jsonb(envelope.as_json()),
                        envelope.repository,
                        operation_key,
                    ),
                )
        if expired_attempt:
            raise UnknownEffectNeedsReconciliation(
                "expired pre-effect claim may have executed; external readback required"
            )
        self._fault(fault_at, "after_claim_commit")
        claim_lsn = self._flushed_lsn()
        with self._connect() as conn:
            finalized = conn.execute(
                "UPDATE builderops_outbox SET claim_lsn = %s WHERE repository = %s AND operation_key = %s "
                "AND worker_id = %s AND claim_fencing_token = %s RETURNING operation_key",
                (claim_lsn, envelope.repository, operation_key, worker_id, token),
            ).fetchone()
            if finalized is None:
                raise StaleFencingToken("outbox claim was superseded before durability binding")
            conn.execute(
                "UPDATE builderops_receipts SET recovery_lsn = %s WHERE receipt_sequence = %s",
                (claim_lsn, receipt_sequence),
            )
        return OutboxClaim(
            envelope.repository,
            operation_key,
            worker_id,
            token,
            str(row["intent_lsn"]),
            claim_lsn,
            receipt_sequence,
            expires_at,
        )

    def outbox_intent(
        self, repository: str, operation_key: str
    ) -> Mapping[str, Any]:
        canonical = canonical_repository(repository)
        self._repair_outbox_bindings(canonical, operation_key)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT repository, operation_key, task_id, effect_type, payload, "
                "status, intent_receipt_sequence, intent_lsn::text AS intent_lsn, "
                "reconciliation_evidence, reconciliation_receipt_sequence, "
                "authority_envelope, post_effect_phase, post_effect_fencing_token, "
                "post_effect_intent_lsn::text AS post_effect_intent_lsn, "
                "post_effect_claim_lsn::text AS post_effect_claim_lsn, "
                "post_effect_observed_applied, post_effect_terminal_unknown "
                "FROM builderops_outbox "
                "WHERE repository = %s AND operation_key = %s",
                (canonical, operation_key),
            ).fetchone()
        if row is None:
            raise KeyError(operation_key)
        if row["intent_lsn"] is None:
            raise DurabilityPending("outbox intent durability binding is incomplete")
        return dict(row)

    def begin_post_effect_pending(
        self, *, repository: str, operation_key: str, minimum_fencing_token: int,
        expected_principal: str,
    ) -> Mapping[str, Any]:
        """Persist dormant phase identity from a locked row, never request evidence."""
        repository = canonical_repository(repository)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, worker_id, claim_fencing_token, intent_lsn::text AS intent_lsn, "
                "claim_lsn::text AS claim_lsn, claim_receipt_sequence, claim_expires_at, authority_envelope, "
                "post_effect_phase, post_effect_fencing_token, "
                "post_effect_intent_lsn::text AS post_effect_intent_lsn, "
                "post_effect_claim_lsn::text AS post_effect_claim_lsn, "
                "post_effect_claim_receipt_sequence, "
                "clock_timestamp() AS database_now FROM builderops_outbox "
                "WHERE repository = %s AND operation_key = %s FOR UPDATE",
                (repository, operation_key),
            ).fetchone()
            if (
                row is None or row["status"] not in {"claimed", "unknown"} or row["worker_id"] is None
                or row["intent_lsn"] is None or row["claim_lsn"] is None
                or row["claim_receipt_sequence"] is None or row["claim_expires_at"] is None
                or row["claim_expires_at"] <= row["database_now"]
                or int(row["claim_fencing_token"]) != minimum_fencing_token
            ):
                raise StaleFencingToken("post-effect pending requires current locked fence")
            if dict(row["authority_envelope"] or {}).get("actor") != expected_principal:
                raise PermissionError("post-effect claim does not belong to authenticated principal")
            derived = {
                "fencing_token": int(row["claim_fencing_token"]),
                "intent_lsn": str(row["intent_lsn"]),
                "claim_lsn": str(row["claim_lsn"]),
                "claim_receipt_sequence": int(row["claim_receipt_sequence"]),
            }
            if row["post_effect_phase"] is None:
                conn.execute(
                    "UPDATE builderops_outbox SET post_effect_phase = 'pending', "
                    "post_effect_fencing_token = %s, post_effect_intent_lsn = %s, "
                    "post_effect_claim_lsn = %s, post_effect_claim_receipt_sequence = %s "
                    "WHERE repository = %s AND operation_key = %s",
                    (derived["fencing_token"], derived["intent_lsn"], derived["claim_lsn"],
                     derived["claim_receipt_sequence"], repository, operation_key),
                )
            elif (
                row["post_effect_fencing_token"] != derived["fencing_token"]
                or row["post_effect_intent_lsn"] != derived["intent_lsn"]
                or row["post_effect_claim_lsn"] != derived["claim_lsn"]
                or row["post_effect_claim_receipt_sequence"] != derived["claim_receipt_sequence"]
            ):
                raise StaleFencingToken("post-effect identity drifted from locked row")
        return derived

    def reconcile_post_effect(
        self, *, repository: str, operation_key: str, minimum_fencing_token: int,
        observed_applied: bool, evidence: Mapping[str, Any], expected_principal: str,
        terminal_unknown: bool = False,
    ) -> Mapping[str, Any]:
        """Use the stored row-derived claim for dormant reconciliation only."""
        if terminal_unknown and observed_applied:
            raise ValueError("terminal-unknown reconciliation cannot claim an applied effect")
        _validate_row_derived_evidence(evidence, terminal_unknown=terminal_unknown)
        if not terminal_unknown:
            readback = evidence["readback"]
            expected_readback = "found" if observed_applied else "not-found"
            if readback != expected_readback:
                raise ValueError("readback evidence contradicts the requested outcome")
        repository = canonical_repository(repository)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, worker_id, claim_fencing_token, intent_lsn::text AS intent_lsn, "
                "claim_lsn::text AS claim_lsn, claim_receipt_sequence, claim_expires_at, authority_envelope, "
                "post_effect_phase, post_effect_fencing_token, "
                "post_effect_intent_lsn::text AS post_effect_intent_lsn, "
                "post_effect_claim_lsn::text AS post_effect_claim_lsn, "
                "post_effect_claim_receipt_sequence, post_effect_evidence, "
                "post_effect_observed_applied, post_effect_terminal_unknown, "
                "post_effect_receipt_sequence, post_effect_recovery_lsn::text AS post_effect_recovery_lsn, "
                "reconciliation_evidence, reconciliation_receipt_sequence, reconciliation_lsn::text AS reconciliation_lsn, "
                "clock_timestamp() AS database_now FROM builderops_outbox "
                "WHERE repository = %s AND operation_key = %s FOR UPDATE",
                (repository, operation_key),
            ).fetchone()
            if row is None or int(row["claim_fencing_token"]) != minimum_fencing_token:
                raise StaleFencingToken("post-effect reconciliation requires current locked fence")
            if dict(row["authority_envelope"] or {}).get("actor") != expected_principal:
                raise PermissionError("post-effect claim does not belong to authenticated principal")
            if row["post_effect_phase"] == "reconciled":
                if (
                    row["post_effect_fencing_token"] != row["claim_fencing_token"]
                    or row["post_effect_intent_lsn"] != row["intent_lsn"]
                    or row["post_effect_claim_lsn"] != row["claim_lsn"]
                    or row["post_effect_claim_receipt_sequence"] != row["claim_receipt_sequence"]
                ):
                    raise StaleFencingToken("reconciled post-effect identity drifted from locked row")
                if (
                    dict(row["post_effect_evidence"] or {}) != dict(evidence)
                    or row["post_effect_observed_applied"] is not observed_applied
                    or row["post_effect_terminal_unknown"] is not terminal_unknown
                ):
                    raise IdempotencyConflict("post-effect replay has conflicting evidence")
                return {"status": row["status"], "fencing_token": minimum_fencing_token,
                        "receipt_sequence": int(row["post_effect_receipt_sequence"]),
                        "recovery_lsn": str(row["post_effect_recovery_lsn"]), "replayed": True}
            if row["post_effect_phase"] == "pending" and row["status"] in {"pending", "succeeded", "dead_letter"}:
                expected_status = "dead_letter" if terminal_unknown else ("succeeded" if observed_applied else "pending")
                if (
                    row["status"] != expected_status
                    or row["post_effect_fencing_token"] != row["claim_fencing_token"]
                    or row["post_effect_intent_lsn"] != row["intent_lsn"]
                    or row["post_effect_claim_lsn"] != row["claim_lsn"]
                    or row["post_effect_claim_receipt_sequence"] != row["claim_receipt_sequence"]
                    or dict(row["reconciliation_evidence"] or {}) != dict(evidence)
                    or row["reconciliation_receipt_sequence"] is None
                    or row["reconciliation_lsn"] is None
                ):
                    raise IdempotencyConflict("post-effect recovery has conflicting reconciliation identity")
                result = {"status": expected_status, "fencing_token": minimum_fencing_token,
                          "receipt_sequence": int(row["reconciliation_receipt_sequence"]),
                          "recovery_lsn": str(row["reconciliation_lsn"]), "replayed": True}
            elif (
                row["status"] != "unknown" or row["post_effect_phase"] != "pending"
                or row["worker_id"] is None or row["intent_lsn"] is None or row["claim_lsn"] is None
                or row["claim_receipt_sequence"] is None or row["claim_expires_at"] is None
                or row["claim_expires_at"] <= row["database_now"]
                or row["post_effect_fencing_token"] != row["claim_fencing_token"]
                or row["post_effect_intent_lsn"] != row["intent_lsn"]
                or row["post_effect_claim_lsn"] != row["claim_lsn"]
                or row["post_effect_claim_receipt_sequence"] != row["claim_receipt_sequence"]
            ):
                raise StaleFencingToken("post-effect reconciliation is stale or reordered")
            else:
                claim = OutboxClaim(repository, operation_key, str(row["worker_id"]), minimum_fencing_token,
                                    str(row["intent_lsn"]), str(row["claim_lsn"]),
                                    int(row["claim_receipt_sequence"]), row["claim_expires_at"])
                result = None
        if result is None:
            reconciled = self.reconcile_outbox(claim, observed_applied=observed_applied,
                                               terminal_unknown=terminal_unknown, evidence=evidence)
            result = {"status": reconciled.status, "fencing_token": reconciled.fencing_token,
                      "receipt_sequence": reconciled.receipt_sequence, "recovery_lsn": reconciled.recovery_lsn,
                      "replayed": reconciled.replayed}
        race_retry = False
        with self._connect() as conn:
            updated = conn.execute(
                "UPDATE builderops_outbox SET post_effect_phase = 'reconciled', "
                "post_effect_evidence = %s, post_effect_receipt_sequence = %s, "
                "post_effect_recovery_lsn = %s, post_effect_observed_applied = %s, "
                "post_effect_terminal_unknown = %s WHERE repository = %s AND operation_key = %s "
                "AND post_effect_phase = 'pending' AND post_effect_fencing_token = %s RETURNING operation_key",
                (Jsonb(dict(evidence)), result["receipt_sequence"], result["recovery_lsn"], observed_applied,
                 terminal_unknown, repository, operation_key, minimum_fencing_token),
            ).fetchone()
            if updated is None:
                race_retry = True
        if race_retry:
            return self.reconcile_post_effect(
                repository=repository,
                operation_key=operation_key,
                minimum_fencing_token=minimum_fencing_token,
                expected_principal=expected_principal,
                observed_applied=observed_applied,
                terminal_unknown=terminal_unknown,
                evidence=evidence,
            )
        return result

    def _repair_outbox_claim_binding(self, repository: str, operation_key: str) -> None:
        """Bind a locally committed claim/receipt before recovery marks it unknown."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, worker_id, claim_fencing_token, claim_receipt_sequence, "
                "claim_lsn::text AS claim_lsn FROM builderops_outbox "
                "WHERE repository = %s AND operation_key = %s FOR UPDATE",
                (repository, operation_key),
            ).fetchone()
            if row is None or row["status"] not in {"claimed", "unknown"}:
                return
            if row["worker_id"] is None or row["claim_receipt_sequence"] is None:
                raise DurabilityPending("outbox claim has no local receipt binding")
            receipt = conn.execute(
                "SELECT recovery_lsn::text AS recovery_lsn FROM builderops_receipts "
                "WHERE repository = %s AND receipt_sequence = %s "
                "AND event_type IN ('outbox.claimed', 'outbox.recovered') "
                "AND lease_holder = %s "
                "AND lease_fencing_token = %s FOR UPDATE",
                (
                    repository,
                    int(row["claim_receipt_sequence"]),
                    str(row["worker_id"]),
                    int(row["claim_fencing_token"]),
                ),
            ).fetchone()
            if receipt is None:
                raise DurabilityPending("outbox claim receipt identity is missing")
            candidate_lsn = self._flushed_lsn()
            claim_lsn = str(row["claim_lsn"] or receipt["recovery_lsn"] or candidate_lsn)
            updated = conn.execute(
                "UPDATE builderops_outbox SET claim_lsn = %s "
                "WHERE repository = %s AND operation_key = %s AND worker_id = %s "
                "AND claim_fencing_token = %s AND claim_receipt_sequence = %s "
                "RETURNING operation_key",
                (
                    claim_lsn,
                    repository,
                    operation_key,
                    str(row["worker_id"]),
                    int(row["claim_fencing_token"]),
                    int(row["claim_receipt_sequence"]),
                ),
            ).fetchone()
            if updated is None:
                raise StaleFencingToken("outbox claim changed before local binding repair")
            conn.execute(
                "UPDATE builderops_receipts SET recovery_lsn = %s "
                "WHERE repository = %s AND receipt_sequence = %s",
                (claim_lsn, repository, int(row["claim_receipt_sequence"])),
            )

    def outbox_claim(
        self,
        *,
        envelope: AuthorityEnvelope,
        operation_key: str,
        worker_id: str,
        claim_ttl_seconds: int = 300,
    ) -> OutboxClaim:
        """Recover an expired/unknown attempt under a fresh fenced identity."""
        if (
            not operation_key
            or not worker_id
            or claim_ttl_seconds <= 0
        ):
            raise ValueError(
                "operation_key, worker_id, and positive claim_ttl_seconds "
                "are mandatory"
            )
        repository = canonical_repository(envelope.repository)
        self._repair_outbox_bindings(repository, operation_key)
        self._repair_outbox_claim_binding(repository, operation_key)
        with self._connect() as conn:
            conn.execute("SET LOCAL synchronous_commit = on")
            self._assert_executor_enabled(conn)
            row = conn.execute(
                "SELECT outbox.task_id, outbox.status, outbox.worker_id, "
                "outbox.claim_fencing_token, "
                "outbox.intent_lsn::text AS intent_lsn, "
                "outbox.claim_lsn::text AS claim_lsn, "
                "outbox.claim_receipt_sequence, outbox.claim_expires_at, outbox.post_effect_phase, "
                "clock_timestamp() AS database_now, receipt.event_type AS claim_event_type "
                "FROM builderops_outbox AS outbox "
                "JOIN builderops_receipts AS receipt "
                "ON receipt.repository = outbox.repository "
                "AND receipt.receipt_sequence = outbox.claim_receipt_sequence "
                "WHERE outbox.repository = %s AND outbox.operation_key = %s "
                "AND outbox.status IN ('claimed', 'unknown') "
                "FOR UPDATE OF outbox",
                (repository, operation_key),
            ).fetchone()
            if (
                row is None
                or row["worker_id"] is None
                or row["claim_receipt_sequence"] is None
                or row["claim_expires_at"] is None
            ):
                raise KeyError(operation_key)
            if row["intent_lsn"] is None:
                raise DurabilityPending("outbox intent durability binding is incomplete")
            if (
                row["claim_expires_at"] > row["database_now"]
            ):
                raise LeaseUnavailable(
                    "outbox operation still has an active claim"
                )
            token = int(row["claim_fencing_token"]) + 1
            expires_at = row["database_now"] + timedelta(
                seconds=claim_ttl_seconds
            )
            receipt = conn.execute(
                "INSERT INTO builderops_receipts("
                "repository, task_id, event_type, idempotency_key, "
                "lease_holder, lease_fencing_token, authority_envelope"
                ") VALUES (%s, %s, 'outbox.recovered', %s, %s, %s, %s) "
                "RETURNING receipt_sequence",
                (
                    repository,
                    row["task_id"],
                    f"outbox:{operation_key}:recover:{token}",
                    worker_id,
                    token,
                    Jsonb(envelope.as_json()),
                ),
            ).fetchone()
            assert receipt is not None
            receipt_sequence = int(receipt["receipt_sequence"])
            updated = conn.execute(
                "UPDATE builderops_outbox SET status = 'unknown', "
                "worker_id = %s, claim_fencing_token = %s, "
                "claim_expires_at = %s, claim_lsn = NULL, "
                "claim_receipt_sequence = %s, post_effect_phase = NULL, post_effect_fencing_token = NULL, "
                "post_effect_intent_lsn = NULL, post_effect_claim_lsn = NULL, "
                "post_effect_claim_receipt_sequence = NULL, post_effect_receipt_sequence = NULL, "
                "post_effect_recovery_lsn = NULL, post_effect_evidence = NULL, "
                "post_effect_observed_applied = NULL, post_effect_terminal_unknown = NULL, "
                "unknown_detail = 'worker process lost; external readback "
                "required', authority_envelope = %s, "
                "updated_at = clock_timestamp() "
                "WHERE repository = %s AND operation_key = %s "
                "AND claim_fencing_token = %s RETURNING operation_key",
                (
                    worker_id,
                    token,
                    expires_at,
                    receipt_sequence,
                    Jsonb(envelope.as_json()),
                    repository,
                    operation_key,
                    int(row["claim_fencing_token"]),
                ),
            ).fetchone()
            if updated is None:
                raise StaleFencingToken(
                    "outbox recovery fence was superseded"
                )
        claim_lsn = self._flushed_lsn()
        with self._connect() as conn:
            finalized = conn.execute(
                "UPDATE builderops_outbox SET claim_lsn = %s "
                "WHERE repository = %s AND operation_key = %s "
                "AND worker_id = %s AND claim_fencing_token = %s "
                "AND claim_receipt_sequence = %s "
                "RETURNING operation_key",
                (
                    claim_lsn,
                    repository,
                    operation_key,
                    worker_id,
                    token,
                    receipt_sequence,
                ),
            ).fetchone()
            if finalized is None:
                raise StaleFencingToken(
                    "outbox recovery was superseded before durability binding"
                )
            conn.execute(
                "UPDATE builderops_receipts SET recovery_lsn = %s "
                "WHERE repository = %s AND receipt_sequence = %s",
                (claim_lsn, repository, receipt_sequence),
            )
        return OutboxClaim(
            repository=repository,
            operation_key=operation_key,
            worker_id=worker_id,
            fencing_token=token,
            intent_lsn=str(row["intent_lsn"]),
            claim_lsn=claim_lsn,
            receipt_sequence=receipt_sequence,
            expires_at=expires_at,
        )

    def effect_eligible(
        self,
        claim: OutboxClaim,
    ) -> bool:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, worker_id, claim_fencing_token, claim_expires_at, "
                "claim_lsn::text AS claim_lsn, clock_timestamp() AS database_now FROM builderops_outbox "
                "WHERE repository = %s AND operation_key = %s",
                (claim.repository, claim.operation_key),
            ).fetchone()
        return bool(
            row is not None
            and row["status"] == "claimed"
            and row["worker_id"] == claim.worker_id
            and int(row["claim_fencing_token"]) == claim.fencing_token
            and row["claim_lsn"] == claim.claim_lsn
            and row["claim_expires_at"] is not None
            and row["claim_expires_at"] > row["database_now"]
        )

    def mark_effect_unknown(self, claim: OutboxClaim, *, detail: str) -> None:
        with self._connect() as conn:
            row = conn.execute(
                "UPDATE builderops_outbox SET status = 'unknown', unknown_detail = %s, updated_at = clock_timestamp() "
                "WHERE repository = %s AND operation_key = %s AND status = 'claimed' "
                "AND worker_id = %s AND claim_fencing_token = %s "
                "AND claim_expires_at > clock_timestamp() "
                "RETURNING operation_key",
                (
                    detail,
                    claim.repository,
                    claim.operation_key,
                    claim.worker_id,
                    claim.fencing_token,
                ),
            ).fetchone()
            if row is None:
                raise StaleFencingToken("outbox claim is stale")

    def reconcile_outbox(
        self,
        claim: OutboxClaim,
        *,
        observed_applied: bool,
        terminal_unknown: bool = False,
        evidence: Mapping[str, Any],
        fault_at: str | None = None,
    ) -> OutboxReconciliation:
        if terminal_unknown and observed_applied:
            raise ValueError(
                "terminal-unknown reconciliation cannot claim an applied effect"
            )
        status = (
            "dead_letter"
            if terminal_unknown
            else ("succeeded" if observed_applied else "pending")
        )
        request_hash = _hash(
            {
                "repository": claim.repository,
                "operation_key": claim.operation_key,
                "worker_id": claim.worker_id,
                "fencing_token": claim.fencing_token,
                "claim_receipt_sequence": claim.receipt_sequence,
                "claim_lsn": claim.claim_lsn,
                "observed_applied": observed_applied,
                "terminal_unknown": terminal_unknown,
                "evidence": dict(evidence),
            }
        )
        replayed = False
        with self._connect() as conn:
            conn.execute("SET LOCAL synchronous_commit = on")
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (
                    f"outbox-reconcile:{claim.repository}:{claim.operation_key}:"
                    f"{claim.fencing_token}",
                ),
            )
            if terminal_unknown:
                effect = conn.execute(
                    "SELECT outbox.effect_type, outbox.payload AS effect_payload, "
                    "task.payload AS task_payload FROM builderops_outbox AS outbox "
                    "JOIN builderops_tasks AS task ON task.repository = outbox.repository "
                    "AND task.task_id = outbox.task_id "
                    "WHERE outbox.repository = %s AND outbox.operation_key = %s "
                    "FOR UPDATE OF outbox, task",
                    (claim.repository, claim.operation_key),
                ).fetchone()
                if effect is None:
                    raise StaleFencingToken(
                        "unknown effect was already reconciled or superseded"
                    )
                _assert_terminal_unknown_model_evidence(
                    effect_type=str(effect["effect_type"]),
                    effect_payload=dict(effect["effect_payload"]),
                    task_payload=dict(effect["task_payload"]),
                    evidence=evidence,
                )
            existing = conn.execute(
                "SELECT request_hash, receipt_sequence FROM builderops_outbox_reconciliations "
                "WHERE repository = %s AND operation_key = %s AND claim_fencing_token = %s "
                "FOR UPDATE",
                (claim.repository, claim.operation_key, claim.fencing_token),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise IdempotencyConflict(
                        "outbox reconciliation claim was reused with different readback evidence"
                    )
                receipt_sequence = int(existing["receipt_sequence"])
                replayed = True
            else:
                outbox = conn.execute(
                    "SELECT task_id, authority_envelope FROM builderops_outbox "
                    "WHERE repository = %s AND operation_key = %s AND status = 'unknown' "
                    "AND worker_id = %s AND claim_fencing_token = %s "
                    "AND claim_receipt_sequence = %s "
                    "AND COALESCE(claim_lsn::text, '0/0') = %s "
                    "AND claim_expires_at > clock_timestamp() FOR UPDATE",
                    (
                        claim.repository,
                        claim.operation_key,
                        claim.worker_id,
                        claim.fencing_token,
                        claim.receipt_sequence,
                        claim.claim_lsn,
                    ),
                ).fetchone()
                if outbox is None:
                    raise StaleFencingToken("unknown effect was already reconciled or superseded")
                receipt = conn.execute(
                    "INSERT INTO builderops_receipts(repository, task_id, event_type, idempotency_key, "
                    "lease_holder, lease_fencing_token, authority_envelope) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING receipt_sequence",
                    (
                        claim.repository,
                        outbox["task_id"],
                        f"outbox.reconciled.{status}",
                        f"outbox:{claim.operation_key}:reconcile:{claim.fencing_token}",
                        claim.worker_id,
                        claim.fencing_token,
                        Jsonb(dict(outbox["authority_envelope"])),
                    ),
                ).fetchone()
                assert receipt is not None
                receipt_sequence = int(receipt["receipt_sequence"])
                self._fault(fault_at, "after_reconciliation_receipt")
                updated = conn.execute(
                    "UPDATE builderops_outbox SET status = %s, reconciliation_evidence = %s, "
                    "reconciliation_receipt_sequence = %s, reconciliation_lsn = NULL, "
                    "worker_id = NULL, claim_expires_at = NULL, updated_at = clock_timestamp() "
                    "WHERE repository = %s AND operation_key = %s AND status = 'unknown' "
                    "AND worker_id = %s AND claim_fencing_token = %s "
                    "AND claim_receipt_sequence = %s "
                    "AND COALESCE(claim_lsn::text, '0/0') = %s RETURNING operation_key",
                    (
                        status,
                        Jsonb(dict(evidence)),
                        receipt_sequence,
                        claim.repository,
                        claim.operation_key,
                        claim.worker_id,
                        claim.fencing_token,
                        claim.receipt_sequence,
                        claim.claim_lsn,
                    ),
                ).fetchone()
                if updated is None:
                    raise StaleFencingToken("unknown effect was already reconciled or superseded")
                self._fault(fault_at, "after_reconciliation_state")
                if terminal_unknown:
                    conn.execute(
                        "INSERT INTO builderops_dead_letters("
                        "repository, operation_key, outcome, authority_envelope) "
                        "VALUES (%s, %s, %s, %s)",
                        (
                            claim.repository,
                            claim.operation_key,
                            Jsonb(dict(evidence)),
                            Jsonb(dict(outbox["authority_envelope"])),
                        ),
                    )
                conn.execute(
                    "INSERT INTO builderops_outbox_reconciliations("
                    "repository, operation_key, claim_fencing_token, task_id, worker_id, "
                    "claim_receipt_sequence, claim_lsn, observed_applied, evidence, request_hash, "
                    "status, receipt_sequence, authority_envelope) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        claim.repository,
                        claim.operation_key,
                        claim.fencing_token,
                        outbox["task_id"],
                        claim.worker_id,
                        claim.receipt_sequence,
                        claim.claim_lsn,
                        observed_applied,
                        Jsonb(dict(evidence)),
                        request_hash,
                        status,
                        receipt_sequence,
                        Jsonb(dict(outbox["authority_envelope"])),
                    ),
                )
                self._fault(fault_at, "after_reconciliation_record")
        self._fault(fault_at, "after_reconciliation_commit")
        recovery_lsn = self._flushed_lsn()
        return self._finalize_reconciliation(
            claim.repository,
            claim.operation_key,
            claim.fencing_token,
            receipt_sequence,
            recovery_lsn,
            replayed=replayed,
        )

    def _finalize_reconciliation(
        self,
        repository: str,
        operation_key: str,
        fencing_token: int,
        receipt_sequence: int,
        recovery_lsn: str,
        *,
        replayed: bool,
    ) -> OutboxReconciliation:
        with self._connect() as conn:
            conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (f"outbox-reconcile:{repository}:{operation_key}:{fencing_token}",),
            )
            row = conn.execute(
                "SELECT task_id, worker_id, claim_receipt_sequence, status, receipt_sequence, "
                "recovery_lsn::text AS recovery_lsn "
                "FROM builderops_outbox_reconciliations WHERE repository = %s "
                "AND operation_key = %s AND claim_fencing_token = %s FOR UPDATE",
                (repository, operation_key, fencing_token),
            ).fetchone()
            if row is None:
                raise RuntimeError("committed outbox reconciliation disappeared")
            if row["recovery_lsn"] is not None:
                return self._reconciliation(row, repository, operation_key, fencing_token, replayed)
            conn.execute(
                "UPDATE builderops_receipts SET recovery_lsn = %s WHERE receipt_sequence = %s",
                (recovery_lsn, receipt_sequence),
            )
            conn.execute(
                "UPDATE builderops_outbox_reconciliations SET recovery_lsn = %s "
                "WHERE repository = %s AND operation_key = %s AND claim_fencing_token = %s",
                (recovery_lsn, repository, operation_key, fencing_token),
            )
            bound = conn.execute(
                "UPDATE builderops_outbox SET reconciliation_lsn = %s "
                "WHERE repository = %s AND operation_key = %s "
                "AND reconciliation_receipt_sequence = %s AND claim_fencing_token = %s "
                "RETURNING operation_key",
                (recovery_lsn, repository, operation_key, receipt_sequence, fencing_token),
            ).fetchone()
            if bound is None:
                raise RuntimeError("outbox reconciliation was superseded before durability binding")
            row = dict(row)
            row["recovery_lsn"] = recovery_lsn
        return self._reconciliation(row, repository, operation_key, fencing_token, replayed)

    @staticmethod
    def _reconciliation(
        row: Mapping[str, Any],
        repository: str,
        operation_key: str,
        fencing_token: int,
        replayed: bool,
    ) -> OutboxReconciliation:
        return OutboxReconciliation(
            repository=repository,
            operation_key=operation_key,
            task_id=str(row["task_id"]),
            status=str(row["status"]),
            worker_id=str(row["worker_id"]),
            fencing_token=fencing_token,
            claim_receipt_sequence=int(row["claim_receipt_sequence"]),
            receipt_sequence=int(row["receipt_sequence"]),
            recovery_lsn=str(row["recovery_lsn"] or "0/0"),
            replayed=replayed,
        )

    def _load_reconciliation(
        self,
        conn: Any,
        repository: str,
        operation_key: str,
        fencing_token: int,
    ) -> OutboxReconciliation:
        row = conn.execute(
            "SELECT task_id, worker_id, claim_receipt_sequence, status, receipt_sequence, "
            "recovery_lsn::text AS recovery_lsn FROM builderops_outbox_reconciliations "
            "WHERE repository = %s AND operation_key = %s AND claim_fencing_token = %s",
            (repository, operation_key, fencing_token),
        ).fetchone()
        if row is None or row["recovery_lsn"] is None:
            raise DurabilityPending("outbox reconciliation durability binding is incomplete")
        return self._reconciliation(row, repository, operation_key, fencing_token, False)

    def outbox_status(
        self,
        repository: str,
        operation_key: str | None,
    ) -> str:
        repository = canonical_repository(repository)
        if not operation_key:
            raise ValueError("operation_key is mandatory")
        self._repair_outbox_bindings(repository, operation_key)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status, claim_fencing_token, reconciliation_receipt_sequence "
                "FROM builderops_outbox "
                "WHERE repository = %s AND operation_key = %s",
                (repository, operation_key),
            ).fetchone()
            if row is None:
                raise KeyError(operation_key)
            if row["status"] == "succeeded" or (
                row["status"] == "pending" and row["reconciliation_receipt_sequence"] is not None
            ):
                self._load_reconciliation(
                    conn,
                    repository,
                    str(operation_key),
                    int(row["claim_fencing_token"]),
                )
        return str(row["status"])

    def authority_counts(self, repository: str) -> dict[str, int]:
        repository = canonical_repository(repository)
        tables = {
            "tasks": "builderops_tasks",
            "attempts": "builderops_attempts",
            "records": "builderops_records",
            "promotions": "builderops_promotions",
            "receipts": "builderops_receipts",
            "idempotency": "builderops_idempotency",
            "outbox": "builderops_outbox",
        }
        counts: dict[str, int] = {}
        with self._connect() as conn:
            for name, table in tables.items():
                row = conn.execute(
                    f"SELECT count(*) AS count FROM {table} WHERE repository = %s",  # noqa: S608
                    (repository,),
                ).fetchone()
                assert row is not None
                counts[name] = int(row["count"])
        return counts

    def receipt(self, repository: str, sequence: int) -> dict[str, Any]:
        repository = canonical_repository(repository)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT task_id, event_type, idempotency_key, lease_holder, lease_fencing_token, "
                "recovery_lsn::text AS recovery_lsn "
                "FROM builderops_receipts WHERE repository = %s AND receipt_sequence = %s",
                (repository, sequence),
            ).fetchone()
        if row is None:
            raise KeyError(sequence)
        return dict(row)


# FCA-09 specializes the existing record/receipt transaction in this data layer.
# Source validation stays lazy; clients never import or open a database here.
def _is_owner_outcome(record_id: str, payload: Mapping[str, Any]) -> bool:
    from app.builderops.owner_fact_producers import CONTRACT, OUTCOME_PREFIX

    body = payload.get("receipt_body")
    return record_id.startswith(OUTCOME_PREFIX) or payload.get("contract") == CONTRACT or (
        isinstance(body, Mapping) and body.get("contract") == CONTRACT
    )


def _owner_outcome_lock(conn: Any, repository: str, subject: str, binding_hash: str) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                 (f"owner-outcome:{repository}:{subject}:{binding_hash}",))


def _owner_outcome_epoch(conn: Any) -> int:
    from app.builderops.owner_fact_producers import OwnerFactRefusal

    row = conn.execute("SELECT authority_epoch FROM builderops_authority_metadata WHERE singleton FOR SHARE").fetchone()
    if row is None:
        raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
    return int(row["authority_epoch"])


def _owner_outcome_history(conn: Any, repository: str, subject: str) -> list[dict[str, Any]]:
    # Every committed journal entry and idempotency result must still resolve
    # its immutable record. Starting only from surviving records could silently
    # select an older acceptance after a terminal correction disappeared.
    from app.builderops.owner_fact_producers import CONTRACT, OwnerFactRefusal, outcome_request_hash, receipt_hash

    lineage = conn.execute(
        "SELECT journal.task_id, journal.receipt_sequence, journal.idempotency_key, "
        "record.record_id, record.payload, idem.request_hash, idem.result "
        "FROM builderops_receipts AS journal "
        "LEFT JOIN builderops_records AS record ON record.repository=journal.repository AND record.record_id=journal.task_id "
        "LEFT JOIN builderops_idempotency AS idem ON idem.repository=journal.repository AND idem.idempotency_key=journal.idempotency_key "
        "WHERE journal.repository=%s AND journal.authority_envelope->>'scope'='owner-outcome' "
        "AND journal.event_type IN ('owner_outcome_recorded','owner_outcome_corrected') "
        "AND journal.authority_envelope->'source_refs' ? %s",
        (repository, subject),
    ).fetchall()
    journal_keys = set()
    for row in lineage:
        if row["record_id"] is None or row["result"] is None:
            raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
        if row["result"].get("object_id") != row["task_id"] or row["result"].get("receipt_sequence") != row["receipt_sequence"] or row["request_hash"] != row["payload"].get("receipt_body", {}).get("request_sha256"):
            raise OwnerFactRefusal("owner_history_conflict", 409)
        journal_keys.add(row["idempotency_key"])
    idem_rows = conn.execute(
        "SELECT idempotency_key FROM builderops_idempotency WHERE repository=%s "
        "AND authority_envelope->>'scope'='owner-outcome' AND authority_envelope->'source_refs' ? %s",
        (repository, subject),
    ).fetchall()
    if {row["idempotency_key"] for row in idem_rows} != journal_keys:
        raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
    rows = conn.execute(
        "SELECT record.record_id, record.payload, record.authority_envelope, receipt.receipt_sequence "
        "FROM builderops_records AS record LEFT JOIN builderops_receipts AS receipt "
        "ON receipt.repository = record.repository AND receipt.task_id = record.record_id "
        "AND receipt.receipt_sequence::text = record.payload->>'receipt_sequence' "
        "AND receipt.authority_envelope->>'scope' = 'owner-outcome' "
        "AND receipt.event_type IN ('owner_outcome_recorded','owner_outcome_corrected') "
        "WHERE record.repository = %s AND record.record_type = 'BuilderOpsReceipt' "
        "AND record.payload->'receipt_body'->>'contract' = %s "
        "AND record.payload->'receipt_body'->'request'->>'subject_ref' = %s",
        (repository, CONTRACT, subject),
    ).fetchall()
    receipts = []
    seen = set()
    for row in rows:
        value = row["payload"]
        try:
            body, request = value["receipt_body"], value["receipt_body"]["request"]
            confirmation = body["confirmation_ref"]
            if (
                row["record_id"] in seen or row["receipt_sequence"] is None
                or row["record_id"] != value["id"]
                or value["receipt_sequence"] != row["receipt_sequence"]
                or value["hash"] != receipt_hash(value)
                or body["request_sha256"] != outcome_request_hash(request)
                or confirmation["request_sha256"] != body["request_sha256"]
                or confirmation["id"] != value["id"] + "#confirmation"
                or confirmation["human_principal"] != request["owner_actor"]["id"]
                or confirmation["authorization_ref"] != request["authorization_ref"]
                or request["repository"] != repository
                or value["actor"] != request["owner_actor"]
                or row["authority_envelope"]["actor"] != request["owner_actor"]["id"]
                or row["authority_envelope"]["scope"] != "owner-outcome"
                or request["fact_kind"] not in {"owner_trial", "owner_acceptance"}
                or datetime.fromisoformat(confirmation["confirmed_at"]) > datetime.fromisoformat(body["recorded_at"])
            ):
                raise ValueError
            seen.add(row["record_id"])
            receipts.append(value)
        except Exception as exc:
            raise OwnerFactRefusal("owner_history_incompatible", 409) from exc
    return receipts


def _owner_outcome_selection(history: list[dict[str, Any]], binding_hash: str, kind: str) -> dict[str, Any] | None:
    from app.builderops.owner_fact_producers import OwnerFactRefusal

    slot = {r["id"]: r for r in history if r["binding_hash"] == binding_hash and r["receipt_body"]["request"]["fact_kind"] == kind}
    if not slot:
        return None
    roots = [r for r in slot.values() if r["receipt_body"]["request"]["expected_previous_receipt_id"] is None]
    if len(roots) != 1:
        raise OwnerFactRefusal("owner_history_conflict", 409)
    current = roots[0]
    visited = {current["id"]}
    while True:
        children = [r for r in slot.values() if r["receipt_body"]["request"]["expected_previous_receipt_id"] == current["id"]]
        if not children:
            if visited != set(slot):
                raise OwnerFactRefusal("owner_history_conflict", 409)
            return current
        if len(children) != 1 or children[0]["id"] in visited:
            raise OwnerFactRefusal("owner_history_conflict", 409)
        child = children[0]
        request = child["receipt_body"]["request"]
        if request["supersedes_receipt_id"] != current["id"] or request["correction_reason"] != "owner_correction" or child["receipt_sequence"] <= current["receipt_sequence"]:
            raise OwnerFactRefusal("owner_history_conflict", 409)
        current = child
        visited.add(current["id"])


def _owner_outcome_valid_trial(trial: dict[str, Any] | None, trial_ref: Any) -> bool:
    return trial is not None and trial["id"] == trial_ref and trial["receipt_body"]["request"]["outcome"] == "tried"


def _owner_outcome_projection(receipt: dict[str, Any], history: list[dict[str, Any]], binding: dict[str, Any]) -> dict[str, str]:
    if receipt["binding_hash"] != binding["binding_hash"]:
        return {"status": "withdrawn", "reason": "source_binding_changed"}
    kind = receipt["receipt_body"]["request"]["fact_kind"]
    selected = _owner_outcome_selection(history, binding["binding_hash"], kind)
    if selected is None or selected["id"] != receipt["id"]:
        return {"status": "superseded", "reason": "owner_correction"}
    request = receipt["receipt_body"]["request"]
    if binding["owner_grant_status"] != "available":
        return {"status": "withdrawn", "reason": "owner_grant_unavailable"}
    if binding["readiness_status"] != "current" and request["outcome"] != "unable_to_try":
        return {"status": "withdrawn", "reason": "readiness_withdrawn"}
    if kind == "owner_acceptance" and request["trial_receipt_ref"] is not None:
        trial = _owner_outcome_selection(history, binding["binding_hash"], "owner_trial")
        if not _owner_outcome_valid_trial(trial, request["trial_receipt_ref"]):
            return {"status": "withdrawn", "reason": "trial_corrected"}
    return {"status": "current", "reason": "source_and_lineage_verified"}


def _commit_owner_outcome(
    store: PostgresBuilderOpsStore, *, envelope: AuthorityEnvelope,
    admission: OwnerOutcomeAdmission, idempotency_key: str, fault_at: str | None,
) -> AuthorityObjectResult:
    from app.builderops.owner_fact_producers import CONTRACT, OwnerFactRefusal, digest, outcome_record_id, receipt_hash, validate_current_binding

    request = admission.request
    repository, subject = request["repository"], request["subject_ref"]
    if envelope.repository != repository or envelope.actor != request["owner_actor"]["id"]:
        raise OwnerFactRefusal("owner_principal_mismatch", 403)
    record_id = outcome_record_id(repository, idempotency_key)
    key = "owner-outcome:" + idempotency_key
    replayed = False
    with store._connect() as conn:
        conn.execute("SET LOCAL synchronous_commit = on")
        conn.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (f"idempotency:{repository}:{key}",))
        existing = conn.execute("SELECT request_hash, result FROM builderops_idempotency WHERE repository = %s AND idempotency_key = %s FOR UPDATE", (repository, key)).fetchone()
        if existing is not None:
            if existing["request_hash"] != admission.request_sha256:
                raise OwnerFactRefusal("idempotency_conflict", 409)
            history = _owner_outcome_history(conn, repository, subject)
            original = next((r for r in history if r["id"] == record_id), None)
            if original is None:
                raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
            provisional = store._authority_result(existing["result"], replayed=True)
            receipt_sequence = provisional.receipt_sequence
            replayed = True
        else:
            epoch = _owner_outcome_epoch(conn)
            binding = admission.revalidate(epoch)
            _owner_outcome_lock(conn, repository, subject, binding["binding_hash"])
            current_binding = admission.revalidate(epoch)
            validate_current_binding(request, binding)
            if binding["binding_hash"] != current_binding["binding_hash"]:
                raise OwnerFactRefusal("owner_binding_changed", 409)
            history = _owner_outcome_history(conn, repository, subject)
            previous = _owner_outcome_selection(history, binding["binding_hash"], request["fact_kind"])
            if request["expected_previous_receipt_id"] != (previous["id"] if previous else None):
                raise OwnerFactRefusal("current_receipt_conflict", 409)
            trial = _owner_outcome_selection(history, binding["binding_hash"], "owner_trial")
            if request["fact_kind"] == "owner_acceptance" and (
                request["outcome"] == "accepted" or request["trial_receipt_ref"] is not None
            ) and not _owner_outcome_valid_trial(trial, request["trial_receipt_ref"]):
                raise OwnerFactRefusal("trial_receipt_conflict", 409)
            # Recheck mutable permission and external source versions after all
            # guarded reads, immediately before generating commit metadata.
            store._fault(fault_at, "before_owner_outcome_commit")
            latest = admission.revalidate(epoch)
            if latest["binding_hash"] != binding["binding_hash"]:
                raise OwnerFactRefusal("owner_binding_changed", 409)
            recorded_at = store._database_now(conn)
            if datetime.fromisoformat(admission.confirmed_at) > recorded_at:
                raise OwnerFactRefusal("owner_confirmation_clock_unavailable", 503)
            stamp = recorded_at.isoformat()
            event = "owner_outcome_corrected" if previous else "owner_outcome_recorded"
            log = conn.execute(
                "INSERT INTO builderops_receipts(repository, task_id, event_type, idempotency_key, authority_envelope) VALUES (%s,%s,%s,%s,%s) RETURNING receipt_sequence",
                (repository, record_id, event, key, Jsonb(envelope.as_json())),
            ).fetchone()
            assert log is not None
            receipt_sequence = int(log["receipt_sequence"])
            body = {"contract": CONTRACT, "request": request, "request_sha256": admission.request_sha256,
                    "confirmation_ref": {"id": record_id + "#confirmation", "request_sha256": admission.request_sha256,
                                         "human_principal": envelope.actor, "confirmed_at": admission.confirmed_at,
                                         "authorization_ref": request["authorization_ref"]}, "recorded_at": stamp}
            sources = [{"ref_type": "source", "ref": ref, "authority_surface": "builderops"} for ref in envelope.source_refs]
            receipt = {"id": record_id, "object_type": "BuilderOpsReceipt", "authority_class": "receipt",
                "lifecycle_state": "active", "promotion_status": "not_promotable", "created_at": stamp, "updated_at": stamp,
                "created_by": {"actor_type": "service", "id": "builderops-control-plane"},
                "source_refs": sources, "target_refs": [{"ref_type": "subject", "ref": subject, "authority_surface": "github"}],
                "summary": "Explicit owner outcome recorded", "event_type": event, "actor": request["owner_actor"],
                "occurred_at": stamp, "action": "record_" + request["fact_kind"], "outcome": "succeeded",
                "receipt_body": body, "idempotency_key": idempotency_key, "binding_hash": binding["binding_hash"],
                "receipt_sequence": receipt_sequence}
            receipt["hash"] = receipt_hash(receipt)
            conn.execute("INSERT INTO builderops_records(repository, record_id, record_type, state, payload, authority_envelope) VALUES (%s,%s,'BuilderOpsReceipt','active',%s,%s)", (repository, record_id, Jsonb(receipt), Jsonb(envelope.as_json())))
            store._fault(fault_at, "after_owner_outcome_receipt")
            provisional = AuthorityObjectResult(repository=repository, object_kind="record", object_id=record_id,
                                                state="active", receipt_sequence=receipt_sequence, recovery_lsn="0/0")
            conn.execute("INSERT INTO builderops_idempotency(repository,idempotency_key,request_hash,result,authority_envelope) VALUES (%s,%s,%s,%s,%s)", (repository,key,admission.request_sha256,Jsonb(store._authority_result_json(provisional)),Jsonb(envelope.as_json())))
            # An intent is a rebuild request, not a stored projection. Rebuild
            # always rechecks the current chain, including trial withdrawal.
            intent = {"subject_ref": subject, "binding_hash": binding["binding_hash"], "receipt_id": record_id}
            conn.execute("INSERT INTO builderops_outbox(repository,operation_key,task_id,effect_type,payload,intent_receipt_sequence,authority_envelope) VALUES (%s,%s,%s,'owner_outcomes.project',%s,%s,%s)",
                         (repository,digest(intent),record_id,Jsonb(intent),receipt_sequence,Jsonb(envelope.as_json())))
            store._fault(fault_at, "after_owner_outcome_intent")
    store._fault(fault_at, "after_owner_outcome_commit")
    result = store._finalize_authority_object(repository,key,receipt_sequence,store._flushed_lsn(),replayed=replayed)
    with store._connect() as conn:
        conn.execute("UPDATE builderops_outbox SET intent_lsn=COALESCE(intent_lsn,%s) WHERE repository=%s AND intent_receipt_sequence=%s AND effect_type='owner_outcomes.project'", (result.recovery_lsn,repository,receipt_sequence))
    return result


def _read_owner_outcomes(
    store: PostgresBuilderOpsStore, repository: str, subject_ref: str, *, idempotency_key: str | None,
    grant_reader: Callable[[str, str], bool],
) -> dict[str, Any]:
    from app.builderops.owner_fact_producers import OwnerFactRefusal, read_owner_binding

    repository = canonical_repository(repository)
    with store._connect() as conn:
        epoch = _owner_outcome_epoch(conn)
        historical = _owner_outcome_history(conn, repository, subject_ref)
        original = None
        if idempotency_key is not None:
            existing = conn.execute("SELECT result FROM builderops_idempotency WHERE repository=%s AND idempotency_key=%s", (repository,"owner-outcome:" + idempotency_key)).fetchone()
            if existing is None:
                raise OwnerFactRefusal("owner_outcome_not_found", 404)
            original = next((r for r in historical if r["id"] == existing["result"]["object_id"]), None)
            if original is None:
                raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
        try:
            binding = read_owner_binding(repository, subject_ref, authority_epoch=epoch, allow_withdrawn_readiness=True)
        except OwnerFactRefusal:
            if original is None:
                raise
            return {"contract": "builder_owner_facts.v1", "repository": repository, "subject_ref": subject_ref,
                    "receipt": original, "projection": {"status": "unavailable", "reason": "current_source_unavailable"},
                    "authority_epoch": epoch, "observed_at": store._database_now(conn).isoformat()}
        _owner_outcome_lock(conn, repository, subject_ref, binding["binding_hash"])
        current_binding = read_owner_binding(repository, subject_ref, authority_epoch=epoch, allow_withdrawn_readiness=True)
        if current_binding["binding_hash"] != binding["binding_hash"]:
            raise OwnerFactRefusal("owner_binding_changed", 409)
        binding = current_binding
        binding["owner_grant_status"] = "available" if grant_reader(repository, binding["owner_actor"]["id"]) else "unavailable"
        history = _owner_outcome_history(conn, repository, subject_ref)
        facts: dict[str, Any] = {"ready_to_try": binding if binding["readiness_status"] == "current" else None, "owner_trial": None, "owner_acceptance": None}
        for kind in ("owner_trial", "owner_acceptance"):
            current = _owner_outcome_selection(history, binding["binding_hash"], kind)
            if current is not None and _owner_outcome_projection(current, history, binding)["status"] == "current":
                facts[kind] = current
        result: dict[str, Any] = {"contract": "builder_owner_facts.v1", "repository": repository,
            "subject_ref": subject_ref, "binding": binding, "facts": facts, "history": history,
            "authority_epoch": epoch, "observed_at": store._database_now(conn).isoformat()}
        if idempotency_key is not None:
            existing = conn.execute("SELECT result FROM builderops_idempotency WHERE repository=%s AND idempotency_key=%s", (repository,"owner-outcome:" + idempotency_key)).fetchone()
            if existing is None:
                raise OwnerFactRefusal("owner_outcome_not_found", 404)
            receipt = next((r for r in history if r["id"] == existing["result"]["object_id"]), None)
            if receipt is None:
                raise OwnerFactRefusal("owner_authority_history_unavailable", 503)
            result.update(receipt=receipt, projection=_owner_outcome_projection(receipt, history, binding))
        return result
