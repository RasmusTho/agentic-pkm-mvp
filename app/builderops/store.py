"""SQLite-backed BuilderOps Vault store."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from app.builderops.models import (
    BuilderOpsConflictError,
    BuilderOpsLeaseError,
    BuilderOpsValidationError,
    normalize_actor,
    normalize_record,
    utc_now,
    validate_source_refs,
)
from app.builderops.schema import DDL_STATEMENTS, SCHEMA_VERSION


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str) -> Any:
    return json.loads(value)


def _request_hash(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_dumps(value).encode("utf-8")).hexdigest()


def _future_utc(seconds: int) -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        + timedelta(seconds=seconds)
    ).isoformat().replace("+00:00", "Z")


def _idempotency_key(record: Mapping[str, Any]) -> str | None:
    key = record.get("idempotency_key")
    if key is None:
        return None
    if not isinstance(key, str) or not key.strip():
        raise BuilderOpsValidationError("idempotency_key must be a non-empty string")
    return key.strip()


class SqliteBuilderOpsStore:
    """Durable BuilderOps store with local multi-agent safety semantics.

    The store persists BuilderOps records as validated JSON envelopes and
    exposes narrow create/read/list operations. It also provides local
    idempotency, per-record leases, and receipt-backed state transitions. It
    does not implement promotion execution, API/MCP access, projections, or
    migrations.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self) -> None:
        with self._connect() as conn:
            for stmt in DDL_STATEMENTS:
                conn.execute(stmt)
            conn.execute(
                "INSERT OR REPLACE INTO builderops_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.commit()

    def create_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        key = _idempotency_key(record)
        request = {"operation": "create_record", "record": dict(record)}
        request_hash = _request_hash(request)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if key is not None:
                existing = self._idempotency_response(
                    conn,
                    key=key,
                    operation="create_record",
                    request_hash=request_hash,
                )
                if existing is not None:
                    return dict(existing)

            payload = normalize_record(record)
            try:
                self._insert_record_payload(conn, payload)
            except sqlite3.IntegrityError as exc:
                raise BuilderOpsValidationError(
                    f"BuilderOps record already exists: {payload['id']}"
                ) from exc
            if key is not None:
                self._store_idempotency_response(
                    conn,
                    key=key,
                    operation="create_record",
                    request_hash=request_hash,
                    result_record_id=payload["id"],
                    created_by=payload["created_by"],
                    response=payload,
                )
            conn.commit()
        return payload

    def get_record(self, record_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM builderops_records WHERE id = ?", (record_id,)
            ).fetchone()
        if row is None:
            return None
        return dict(_loads(row["payload"]))

    def list_records(self, object_type: str | None = None) -> list[dict[str, Any]]:
        params: tuple[Any, ...] = ()
        query = "SELECT payload FROM builderops_records"
        if object_type is not None:
            normalize_record({
                "object_type": object_type,
                "summary": "validation probe",
                "source_refs": [{"ref_type": "builderops_object", "ref": "validation"}],
                **_minimal_probe_fields(object_type),
            })
            query += " WHERE object_type = ?"
            params = (object_type,)
        query += " ORDER BY created_at ASC, rowid ASC"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(_loads(row["payload"])) for row in rows]

    def create_agent_worklog(self, **fields: Any) -> dict[str, Any]:
        return self.create_record({"object_type": "AgentWorklog", **fields})

    def create_learning_signal(self, **fields: Any) -> dict[str, Any]:
        return self.create_record({"object_type": "LearningSignal", **fields})

    def create_promotion_intent(self, **fields: Any) -> dict[str, Any]:
        return self.create_record({"object_type": "PromotionIntent", **fields})

    def create_docs_freshness_record(self, **fields: Any) -> dict[str, Any]:
        return self.create_record({"object_type": "DocsFreshnessRecord", **fields})

    def create_roadmap_execution_item(self, **fields: Any) -> dict[str, Any]:
        return self.create_record({"object_type": "RoadmapExecutionItem", **fields})

    def create_retro_cluster(self, **fields: Any) -> dict[str, Any]:
        return self.create_record({"object_type": "RetroCluster", **fields})

    def create_builder_decision(self, **fields: Any) -> dict[str, Any]:
        return self.create_record({"object_type": "BuilderDecision", **fields})

    def append_receipt(self, **fields: Any) -> dict[str, Any]:
        return self.create_record({"object_type": "BuilderOpsReceipt", **fields})

    def acquire_lease(
        self,
        resource_id: str,
        *,
        actor: Mapping[str, Any] | str,
        ttl_seconds: int = 5400,
    ) -> dict[str, Any]:
        if not resource_id:
            raise BuilderOpsValidationError("resource_id must not be empty")
        if ttl_seconds <= 0:
            raise BuilderOpsValidationError("ttl_seconds must be positive")
        actor_ref = normalize_actor(actor)
        now = utc_now()
        expires_at = _future_utc(ttl_seconds)
        lease_id = f"lease_{uuid4().hex[:16]}"

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            record = self._get_record_payload(conn, resource_id)
            if record is None:
                raise BuilderOpsValidationError(
                    f"BuilderOps record not found: {resource_id}"
                )
            existing = conn.execute(
                """
                SELECT lease_id, actor, expires_at
                FROM builderops_leases
                WHERE resource_id = ?
                """,
                (resource_id,),
            ).fetchone()
            if existing is not None and existing["expires_at"] > now:
                existing_actor = _loads(existing["actor"])
                if existing_actor != actor_ref:
                    raise BuilderOpsLeaseError(
                        f"active lease already exists for {resource_id}"
                    )
            conn.execute(
                """
                INSERT INTO builderops_leases (
                    resource_id, lease_id, actor, acquired_at, expires_at
                ) VALUES (?,?,?,?,?)
                ON CONFLICT(resource_id) DO UPDATE SET
                    lease_id=excluded.lease_id,
                    actor=excluded.actor,
                    acquired_at=excluded.acquired_at,
                    expires_at=excluded.expires_at
                """,
                (resource_id, lease_id, _dumps(actor_ref), now, expires_at),
            )
            conn.commit()

        return {
            "resource_id": resource_id,
            "lease_id": lease_id,
            "actor": actor_ref,
            "acquired_at": now,
            "expires_at": expires_at,
        }

    def release_lease(
        self,
        lease_id: str,
        *,
        actor: Mapping[str, Any] | str,
    ) -> dict[str, Any]:
        if not lease_id:
            raise BuilderOpsValidationError("lease_id must not be empty")
        actor_ref = normalize_actor(actor)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT resource_id, actor
                FROM builderops_leases
                WHERE lease_id = ?
                """,
                (lease_id,),
            ).fetchone()
            if row is None:
                return {"released": False, "lease_id": lease_id}
            if _loads(row["actor"]) != actor_ref:
                raise BuilderOpsLeaseError("lease actor does not match")
            conn.execute("DELETE FROM builderops_leases WHERE lease_id = ?", (lease_id,))
            conn.commit()
        return {
            "released": True,
            "lease_id": lease_id,
            "resource_id": row["resource_id"],
        }

    def transition_record_state(
        self,
        record_id: str,
        *,
        actor: Mapping[str, Any] | str,
        lease_id: str,
        idempotency_key: str,
        source_refs: list[dict[str, Any]],
        summary: str,
        action: str,
        receipt_body: str,
        lifecycle_state: str | None = None,
        promotion_status: str | None = None,
        receipt_extra: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if lifecycle_state is None and promotion_status is None:
            raise BuilderOpsValidationError(
                "transition requires lifecycle_state or promotion_status"
            )
        key = _idempotency_key({"idempotency_key": idempotency_key})
        if key is None:
            raise BuilderOpsValidationError("idempotency_key must be a non-empty string")
        if not lease_id:
            raise BuilderOpsValidationError("lease_id must not be empty")
        validate_source_refs(source_refs)
        actor_ref = normalize_actor(actor)
        request = {
            "operation": "transition_record_state",
            "record_id": record_id,
            "actor": actor_ref,
            "lease_id": lease_id,
            "idempotency_key": key,
            "source_refs": source_refs,
            "summary": summary,
            "action": action,
            "receipt_body": receipt_body,
            "lifecycle_state": lifecycle_state,
            "promotion_status": promotion_status,
            "receipt_extra": dict(receipt_extra or {}),
        }
        request_hash = _request_hash(request)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = self._idempotency_response(
                conn,
                key=key,
                operation="transition_record_state",
                request_hash=request_hash,
            )
            if existing is not None:
                return dict(existing)

            self._require_active_lease(conn, record_id, lease_id, actor_ref)
            current = self._get_record_payload(conn, record_id)
            if current is None:
                raise BuilderOpsValidationError(
                    f"BuilderOps record not found: {record_id}"
                )
            if current["object_type"] == "BuilderOpsReceipt":
                raise BuilderOpsValidationError(
                    "BuilderOpsReceipt records are append-only and cannot be transitioned"
                )

            updated = dict(current)
            previous_state = {
                "lifecycle_state": current["lifecycle_state"],
                "promotion_status": current["promotion_status"],
            }
            if lifecycle_state is not None:
                updated["lifecycle_state"] = lifecycle_state
            if promotion_status is not None:
                updated["promotion_status"] = promotion_status
            new_state = {
                "lifecycle_state": updated["lifecycle_state"],
                "promotion_status": updated["promotion_status"],
            }
            if new_state == previous_state:
                raise BuilderOpsConflictError("transition does not change record state")

            now = utc_now()
            receipt_payload = {
                "object_type": "BuilderOpsReceipt",
                "summary": summary,
                "event_type": "state_transition",
                "actor": actor_ref,
                "occurred_at": now,
                "target_refs": [
                    {
                        "ref_type": "builderops_object",
                        "ref": record_id,
                        "authority_surface": "builderops",
                    }
                ],
                "action": action,
                "receipt_body": receipt_body,
                "idempotency_key": key,
                "source_refs": source_refs,
                "created_by": actor_ref,
                "previous_state": previous_state,
                "new_state": new_state,
            }
            if receipt_extra:
                receipt_payload.update(dict(receipt_extra))
            receipt = normalize_record(receipt_payload)
            receipt_refs = list(updated.get("receipt_refs", []))
            receipt_refs.append(receipt["id"])
            updated.update({
                "receipt_refs": receipt_refs,
                "updated_at": now,
                "updated_by": actor_ref,
            })
            updated = normalize_record(updated)

            self._insert_record_payload(conn, receipt)
            self._replace_record_payload(conn, updated)
            response = {"record": updated, "receipt": receipt}
            self._store_idempotency_response(
                conn,
                key=key,
                operation="transition_record_state",
                request_hash=request_hash,
                result_record_id=receipt["id"],
                created_by=actor_ref,
                response=response,
            )
            conn.commit()

        return response

    def _get_record_payload(
        self, conn: sqlite3.Connection, record_id: str
    ) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT payload FROM builderops_records WHERE id = ?", (record_id,)
        ).fetchone()
        if row is None:
            return None
        return dict(_loads(row["payload"]))

    def _insert_record_payload(
        self, conn: sqlite3.Connection, payload: Mapping[str, Any]
    ) -> None:
        conn.execute(
            """
            INSERT INTO builderops_records (
                id, object_type, authority_class, lifecycle_state,
                promotion_status, created_at, updated_at, created_by,
                summary, source_refs, payload
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                payload["id"],
                payload["object_type"],
                payload["authority_class"],
                payload["lifecycle_state"],
                payload["promotion_status"],
                payload["created_at"],
                payload["updated_at"],
                _dumps(payload["created_by"]),
                payload["summary"],
                _dumps(payload["source_refs"]),
                _dumps(payload),
            ),
        )

    def _replace_record_payload(
        self, conn: sqlite3.Connection, payload: Mapping[str, Any]
    ) -> None:
        conn.execute(
            """
            UPDATE builderops_records
            SET authority_class = ?,
                lifecycle_state = ?,
                promotion_status = ?,
                updated_at = ?,
                summary = ?,
                source_refs = ?,
                payload = ?
            WHERE id = ?
            """,
            (
                payload["authority_class"],
                payload["lifecycle_state"],
                payload["promotion_status"],
                payload["updated_at"],
                payload["summary"],
                _dumps(payload["source_refs"]),
                _dumps(payload),
                payload["id"],
            ),
        )

    def _idempotency_response(
        self,
        conn: sqlite3.Connection,
        *,
        key: str,
        operation: str,
        request_hash: str,
    ) -> Any | None:
        row = conn.execute(
            """
            SELECT operation, request_hash, response_payload
            FROM builderops_idempotency_keys
            WHERE key = ?
            """,
            (key,),
        ).fetchone()
        if row is None:
            return None
        if row["operation"] != operation or row["request_hash"] != request_hash:
            raise BuilderOpsConflictError(
                f"idempotency key already used for different operation or payload: {key}"
            )
        return _loads(row["response_payload"])

    def _store_idempotency_response(
        self,
        conn: sqlite3.Connection,
        *,
        key: str,
        operation: str,
        request_hash: str,
        result_record_id: str,
        created_by: Mapping[str, Any],
        response: Any,
    ) -> None:
        conn.execute(
            """
            INSERT INTO builderops_idempotency_keys (
                key, operation, request_hash, result_record_id, response_payload,
                created_by, created_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                key,
                operation,
                request_hash,
                result_record_id,
                _dumps(response),
                _dumps(created_by),
                utc_now(),
            ),
        )

    def _require_active_lease(
        self,
        conn: sqlite3.Connection,
        resource_id: str,
        lease_id: str,
        actor: Mapping[str, Any],
    ) -> None:
        row = conn.execute(
            """
            SELECT actor, expires_at
            FROM builderops_leases
            WHERE resource_id = ? AND lease_id = ?
            """,
            (resource_id, lease_id),
        ).fetchone()
        if row is None:
            raise BuilderOpsLeaseError(
                f"active lease required for BuilderOps record: {resource_id}"
            )
        now = utc_now()
        if row["expires_at"] <= now:
            conn.execute(
                "DELETE FROM builderops_leases WHERE resource_id = ? AND lease_id = ?",
                (resource_id, lease_id),
            )
            raise BuilderOpsLeaseError(f"lease expired for BuilderOps record: {resource_id}")
        if _loads(row["actor"]) != dict(actor):
            raise BuilderOpsLeaseError("lease actor does not match")


def _minimal_probe_fields(object_type: str) -> dict[str, Any]:
    if object_type == "AgentWorklog":
        return {"body": "probe", "task_context": {}}
    if object_type == "LearningSignal":
        return {"content": "probe", "signal_type": "probe"}
    if object_type == "RetroCluster":
        return {
            "analysis": "probe",
            "cluster_subject": "probe",
            "member_refs": ["lrn_probe"],
        }
    if object_type == "BuilderDecision":
        return {
            "decision_statement": "probe",
            "decision_scope": "probe",
            "rationale": "probe",
        }
    if object_type == "PromotionIntent":
        return {
            "target_authority_surface": "github_issue",
            "target_action": "create",
            "target_ref": "pending",
            "target_authority_class": "operational",
            "intended_output": "probe",
        }
    if object_type == "DocsFreshnessRecord":
        return {
            "doc_ref": {"ref_type": "repo_doc", "ref": "docs/probe.md"},
            "owner": "probe",
            "review_cadence": "event-driven",
            "freshness_posture": "current",
            "last_reviewed_at": "2026-06-01T00:00:00Z",
            "next_review_due_at": "2026-06-08T00:00:00Z",
        }
    if object_type == "RoadmapExecutionItem":
        return {
            "roadmap_ref": {"ref_type": "repo_doc", "ref": "docs/ROADMAP.md"},
            "execution_state": "probe",
            "owner": "probe",
            "next_decision": "probe",
        }
    if object_type == "BuilderOpsReceipt":
        return {
            "actor": {"actor_type": "agent", "id": "probe"},
            "event_type": "probe",
            "occurred_at": "2026-06-01T00:00:00Z",
            "target_refs": [{"ref_type": "builderops_object", "ref": "probe"}],
            "action": "probe",
            "receipt_body": "probe",
            "idempotency_key": "probe",
        }
    raise BuilderOpsValidationError(f"unsupported object_type: {object_type}")
