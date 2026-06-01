"""SQLite-backed BuilderOps Vault store."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping

from app.builderops.models import BuilderOpsValidationError, normalize_record
from app.builderops.schema import DDL_STATEMENTS, SCHEMA_VERSION


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str) -> Any:
    return json.loads(value)


class SqliteBuilderOpsStore:
    """Minimal durable BuilderOps store.

    The store persists BuilderOps records as validated JSON envelopes and
    exposes narrow create/read/list operations. It does not implement leases,
    idempotency, promotion execution, API/MCP access, or migrations.
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
        payload = normalize_record(record)
        with self._connect() as conn:
            try:
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
            except sqlite3.IntegrityError as exc:
                raise BuilderOpsValidationError(
                    f"BuilderOps record already exists: {payload['id']}"
                ) from exc
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
