"""Privacy-safe BuilderOps observations over already-returned CKM outcomes.

This outer adapter never invokes the CKM query/store path and never emits a
Product/runtime event. It persists bounded structural evidence in a separate
adjacent SQLite store with no policy, promotion, or control authority.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from app.builderops.ckm.contracts import (
    ACCESS_POLICY_VERSION,
    ENVELOPE_SCHEMA_VERSION,
    RESOURCE_SCHEMA_VERSION,
    ErrorEnvelope,
    ResultEnvelope,
    SUPPORTED_RESOURCE_TYPES,
    canonical_digest,
    canonical_json,
)

OBSERVATION_SCHEMA_VERSION = 1
OBSERVATION_TABLE = "ckm_query_observation_v1"
RETENTION_POLICY_VERSION = "ckm-query-observation-retention-v1"
RETENTION_DAYS = 365
EVENT_KINDS = frozenset(
    {
        "supported_result",
        "typed_refusal",
        "unsupported_history_request",
        "accepted_question",
    }
)
PRUNE_LIFECYCLES = frozenset(
    {
        "retention_expired",
        "operator_pruned",
        "storage_count_cap",
        "storage_byte_cap",
        "storage_count_and_byte_cap",
    }
)
QUERY_FAMILIES = frozenset(
    {
        "capability_list",
        "capability_lookup",
        "resource_list",
        "historical_request",
        "accepted_question",
    }
)
FILTER_KINDS = frozenset(
    {
        "none",
        "public_ids",
        "subtree_root_public_id",
        "capability_public_id",
        "unlinked",
        "history_mode",
        "unknown",
    }
)
QUESTION_KINDS = frozenset(
    {
        "evidence_coverage_change",
        "source_freshness_change",
        "citation_confidence_change",
        "candidate_finding_composition_change",
    }
)
HUMAN_AUTHORITIES = frozenset({"owner_accepted", "governance_accepted"})
SOURCE_AUTHORITY_KINDS = frozenset(
    {"github_issue", "builderops_inquiry", "owner_decision"}
)
_COLUMN_CONTRACT = (
    ("observation_id", "TEXT", 1, None, 1),
    ("schema_version", "INTEGER", 1, None, 0),
    ("event_kind", "TEXT", 1, None, 0),
    ("observation_json", "TEXT", 0, None, 0),
    ("semantic_digest", "TEXT", 1, None, 0),
    ("policy_version", "TEXT", 1, None, 0),
    ("observed_at", "TEXT", 1, None, 0),
    ("expires_at", "TEXT", 1, None, 0),
    ("lifecycle", "TEXT", 1, None, 0),
    ("lifecycle_marker_json", "TEXT", 1, None, 0),
    ("supersedes_observation_id", "TEXT", 0, None, 0),
    ("deleted_at", "TEXT", 0, None, 0),
)
_TABLE_DDL = f"""
CREATE TABLE {OBSERVATION_TABLE} (
    observation_id TEXT PRIMARY KEY NOT NULL,
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    event_kind TEXT NOT NULL,
    observation_json TEXT,
    semantic_digest TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    lifecycle_marker_json TEXT NOT NULL,
    supersedes_observation_id TEXT,
    deleted_at TEXT
)
"""
_INDEX_CONTRACT = {
    "idx_ckm_query_observation_expiry": ("expires_at", "observation_id"),
    "idx_ckm_query_observation_lifecycle": (
        "lifecycle",
        "observed_at",
        "observation_id",
    ),
}
_PAYLOAD_BYTES_SQL = (
    "COALESCE(length(CAST(observation_json AS BLOB)), 0) + "
    "COALESCE(length(CAST(semantic_digest AS BLOB)), 0)"
)


@dataclass(frozen=True)
class QueryObservationError(ValueError):
    code: str
    message: str
    details: Mapping[str, Any]

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": dict(self.details),
        }


@dataclass(frozen=True)
class QueryObservationInput:
    query_family: str
    resource_type: str
    filter_kinds: tuple[str, ...] = ("none",)
    latency_ms: float = 0.0
    query_digest: str | None = None
    question_kind: str | None = None
    human_authority: str | None = None
    source_authority_kind: str | None = None
    source_authority_ref: str | None = None


@dataclass(frozen=True)
class QueryObservationReceipt:
    observation_id: str
    event_kind: str
    lifecycle: str
    payload_available: bool


@dataclass(frozen=True)
class _PreparedObservation:
    observation_id: str
    schema_version: int
    event_kind: str
    observation_json: str
    semantic_digest: str
    policy_version: str
    observed_at: str
    expires_at: str
    lifecycle: str
    lifecycle_marker_json: str
    supersedes_observation_id: str | None
    deleted_at: str | None

    def row(self) -> tuple[Any, ...]:
        return (
            self.observation_id,
            self.schema_version,
            self.event_kind,
            self.observation_json,
            self.semantic_digest,
            self.policy_version,
            self.observed_at,
            self.expires_at,
            self.lifecycle,
            self.lifecycle_marker_json,
            self.supersedes_observation_id,
            self.deleted_at,
        )


def observation_store_path(ckm_db_path: Path) -> Path:
    path = Path(ckm_db_path)
    return path.with_name(f"{path.stem}-query-observations.sqlite")


def _normalized_timestamp(value: str | None) -> str:
    if value is None:
        parsed = datetime.now(timezone.utc)
    else:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise QueryObservationError(
                "invalid_observation",
                "observed_at must be an ISO-8601 timestamp",
                {},
            ) from exc
        if parsed.tzinfo is None:
            raise QueryObservationError(
                "invalid_observation",
                "observed_at must include a timezone",
                {},
            )
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _expiry(observed_at: str) -> str:
    parsed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    return (parsed + timedelta(days=RETENTION_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%S.%fZ"
    )


def _latency_bucket(latency_ms: float) -> str:
    if isinstance(latency_ms, bool) or not isinstance(latency_ms, (int, float)):
        raise QueryObservationError(
            "invalid_observation", "latency_ms must be a non-negative number", {}
        )
    if not math.isfinite(latency_ms) or latency_ms < 0:
        raise QueryObservationError(
            "invalid_observation", "latency_ms must be a non-negative number", {}
        )
    if latency_ms < 10:
        return "under_10ms"
    if latency_ms < 100:
        return "10_to_99ms"
    if latency_ms < 1_000:
        return "100_to_999ms"
    return "at_least_1s"


def _count_bucket(count: int) -> str:
    if count == 0:
        return "zero"
    if count == 1:
        return "one"
    if count <= 10:
        return "two_to_ten"
    if count <= 100:
        return "eleven_to_one_hundred"
    return "over_one_hundred"


def _validate_digest(value: str | None, *, field_name: str) -> None:
    if value is None:
        return
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise QueryObservationError(
            "invalid_observation", f"{field_name} must be a canonical SHA-256 digest", {}
        )


def _normalized_ddl(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


class QueryObservationStore:
    """Versioned local evidence store beside, never inside, the CKM database."""

    def __init__(self, ckm_db_path: Path) -> None:
        self.ckm_db_path = Path(ckm_db_path)
        self.path = observation_store_path(self.ckm_db_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                create_table = _TABLE_DDL.replace(
                    "CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1
                )
                connection.execute(create_table)
                self._preflight_table(connection)
                for index_name, columns in _INDEX_CONTRACT.items():
                    connection.execute(
                        f"CREATE INDEX IF NOT EXISTS {index_name} "
                        f"ON {OBSERVATION_TABLE}({', '.join(columns)})"
                    )
                self._preflight(connection)
                connection.commit()
        except sqlite3.Error as exc:
            raise QueryObservationError(
                "observation_store_unsupported",
                "query observation store could not be initialized safely",
                {"reason": str(exc)},
            ) from exc

    @staticmethod
    def _preflight_table(connection: sqlite3.Connection) -> None:
        rows = connection.execute(
            f"PRAGMA table_info({OBSERVATION_TABLE})"
        ).fetchall()
        actual_columns = tuple(
            (
                str(row["name"]),
                str(row["type"]).upper(),
                int(row["notnull"]),
                row["dflt_value"],
                int(row["pk"]),
            )
            for row in rows
        )
        if actual_columns != _COLUMN_CONTRACT:
            raise QueryObservationError(
                "observation_store_unsupported",
                "query observation schema does not match version 1",
                {
                    "expected_columns": _COLUMN_CONTRACT,
                    "actual_columns": actual_columns,
                },
            )
        ddl_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (OBSERVATION_TABLE,),
        ).fetchone()
        actual_ddl = "" if ddl_row is None or ddl_row["sql"] is None else str(ddl_row["sql"])
        if _normalized_ddl(actual_ddl) != _normalized_ddl(_TABLE_DDL):
            raise QueryObservationError(
                "observation_store_unsupported",
                "query observation table constraints do not match version 1",
                {},
            )

    @classmethod
    def _preflight(cls, connection: sqlite3.Connection) -> None:
        cls._preflight_table(connection)
        index_rows = connection.execute(
            f"PRAGMA index_list({OBSERVATION_TABLE})"
        ).fetchall()
        primary_indexes = [row for row in index_rows if row["origin"] == "pk"]
        if (
            len(primary_indexes) != 1
            or int(primary_indexes[0]["unique"]) != 1
            or int(primary_indexes[0]["partial"]) != 0
        ):
            raise QueryObservationError(
                "observation_store_unsupported",
                "query observation primary-key index does not match version 1",
                {},
            )
        primary_columns = tuple(
            str(row["name"])
            for row in connection.execute(
                f"PRAGMA index_info({primary_indexes[0]['name']})"
            ).fetchall()
        )
        if primary_columns != ("observation_id",):
            raise QueryObservationError(
                "observation_store_unsupported",
                "query observation primary-key columns do not match version 1",
                {},
            )
        user_indexes = {
            str(row["name"]): row for row in index_rows if row["origin"] == "c"
        }
        if set(user_indexes) != set(_INDEX_CONTRACT):
            raise QueryObservationError(
                "observation_store_unsupported",
                "query observation index set does not match version 1",
                {
                    "expected_indexes": sorted(_INDEX_CONTRACT),
                    "actual_indexes": sorted(user_indexes),
                },
            )
        for index_name, expected_columns in _INDEX_CONTRACT.items():
            index_row = user_indexes[index_name]
            actual_columns = tuple(
                str(row["name"])
                for row in connection.execute(
                    f"PRAGMA index_info({index_name})"
                ).fetchall()
            )
            ddl_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
                (index_name,),
            ).fetchone()
            actual_ddl = (
                "" if ddl_row is None or ddl_row["sql"] is None else str(ddl_row["sql"])
            )
            expected_ddl = (
                f"CREATE INDEX {index_name} ON {OBSERVATION_TABLE}"
                f"({', '.join(expected_columns)})"
            )
            if (
                int(index_row["unique"]) != 0
                or int(index_row["partial"]) != 0
                or actual_columns != expected_columns
                or _normalized_ddl(actual_ddl) != _normalized_ddl(expected_ddl)
            ):
                raise QueryObservationError(
                    "observation_store_unsupported",
                    "query observation index definition does not match version 1",
                    {"index": index_name},
                )
        rows = connection.execute(
            f"SELECT DISTINCT schema_version, policy_version FROM {OBSERVATION_TABLE}"
        ).fetchall()
        unsupported = [
            {"schema_version": row[0], "policy_version": row[1]}
            for row in rows
            if row[0] != OBSERVATION_SCHEMA_VERSION
            or row[1] != RETENTION_POLICY_VERSION
        ]
        if unsupported:
            raise QueryObservationError(
                "observation_store_unsupported",
                "query observation store contains unsupported versions",
                {"versions": unsupported},
            )
        unknown_kinds = sorted(
            str(row[0])
            for row in connection.execute(
                f"SELECT DISTINCT event_kind FROM {OBSERVATION_TABLE}"
            ).fetchall()
            if row[0] not in EVENT_KINDS
        )
        if unknown_kinds:
            raise QueryObservationError(
                "observation_store_unsupported",
                "query observation store contains unsupported event kinds",
                {"event_kinds": unknown_kinds},
            )

    def _prepare(
        self,
        outcome: ResultEnvelope | ErrorEnvelope | None,
        *,
        event_kind: str,
        metadata: QueryObservationInput,
        observed_at: str | None,
        supersedes_observation_id: str | None,
    ) -> _PreparedObservation:
        if event_kind not in EVENT_KINDS:
            raise QueryObservationError(
                "unsupported_observation_kind",
                "unsupported query observation kind",
                {"event_kind": event_kind},
            )
        if metadata.query_family not in QUERY_FAMILIES:
            raise QueryObservationError(
                "invalid_observation", "unsupported query family", {}
            )
        if metadata.resource_type not in SUPPORTED_RESOURCE_TYPES:
            raise QueryObservationError(
                "invalid_observation", "unsupported resource type", {}
            )
        filter_kinds = tuple(sorted(set(metadata.filter_kinds)))
        if (
            not filter_kinds
            or len(filter_kinds) > len(FILTER_KINDS)
            or any(item not in FILTER_KINDS for item in filter_kinds)
        ):
            raise QueryObservationError(
                "invalid_observation", "unsupported structural filter metadata", {}
            )
        _validate_digest(metadata.query_digest, field_name="query_digest")
        observation_time = _normalized_timestamp(observed_at)
        snapshot_digest: str | None = None
        query_digest = metadata.query_digest
        refusal_kind: str | None = None
        result_count = 0
        truncated = False
        envelope_version = ENVELOPE_SCHEMA_VERSION

        if event_kind == "supported_result":
            if not isinstance(outcome, ResultEnvelope):
                raise QueryObservationError(
                    "invalid_observation",
                    "supported_result requires an immutable result envelope",
                    {},
                )
            result = outcome.to_dict()
            if result["resource_type"] != metadata.resource_type:
                raise QueryObservationError(
                    "invalid_observation", "resource type does not match result", {}
                )
            envelope_version = int(result["schema_version"])
            query_digest = str(result["query_digest"])
            snapshot_digest = str(result["snapshot"]["snapshot_digest"])
            result_count = len(result["resources"])
            truncated = any(
                int(item["truncated"]) > 0
                for item in result["snapshot"]["completeness"]["object_classes"]
            )
        elif event_kind in {"typed_refusal", "unsupported_history_request"}:
            if not isinstance(outcome, ErrorEnvelope):
                raise QueryObservationError(
                    "invalid_observation",
                    "refusal observations require an immutable error envelope",
                    {},
                )
            envelope_version = outcome.schema_version
            refusal_kind = outcome.error.code
            if (
                event_kind == "unsupported_history_request"
                and refusal_kind != "unsupported_historical_semantics"
            ):
                raise QueryObservationError(
                    "invalid_observation",
                    "unsupported history observations require the typed history refusal",
                    {},
                )
        else:
            if outcome is not None:
                raise QueryObservationError(
                    "invalid_observation",
                    "accepted_question does not retain a query payload",
                    {},
                )
            if (
                metadata.query_family != "accepted_question"
                or metadata.question_kind not in QUESTION_KINDS
                or metadata.human_authority not in HUMAN_AUTHORITIES
                or metadata.source_authority_kind not in SOURCE_AUTHORITY_KINDS
                or not isinstance(metadata.source_authority_ref, str)
                or not metadata.source_authority_ref.strip()
            ):
                raise QueryObservationError(
                    "invalid_observation",
                    "accepted questions require bounded human and source authority",
                    {},
                )

        _validate_digest(query_digest, field_name="query_digest")
        _validate_digest(snapshot_digest, field_name="snapshot_digest")
        payload: dict[str, Any] = {
            "projection": {
                "status": "derived_projection",
                "authoritative": False,
                "authority_effects": "none",
            },
            "versions": {
                "observation": OBSERVATION_SCHEMA_VERSION,
                "envelope": envelope_version,
                "resource": RESOURCE_SCHEMA_VERSION,
                "access_policy": ACCESS_POLICY_VERSION,
            },
            "query": {
                "family": metadata.query_family,
                "resource_type": metadata.resource_type,
                "filter_kinds": list(filter_kinds),
                "digest": query_digest,
            },
            "snapshot_digest": snapshot_digest,
            "outcome": {
                "kind": event_kind,
                "refusal_kind": refusal_kind,
                "result_count_bucket": _count_bucket(result_count),
                "truncated": truncated,
            },
            "performance": {"latency_bucket": _latency_bucket(metadata.latency_ms)},
            "authority": {
                "effect": "none",
                "m2_authorized": False,
                "o2_authorized": False,
                "automatic_action": False,
            },
        }
        if event_kind == "accepted_question":
            payload["accepted_question"] = {
                "question_kind": metadata.question_kind,
                "human_authority": metadata.human_authority,
                "source_authority_kind": metadata.source_authority_kind,
                "source_authority_digest": canonical_digest(
                    metadata.source_authority_ref
                ),
                "history_support_enabled": False,
            }
        semantic_record = {
            "schema_version": OBSERVATION_SCHEMA_VERSION,
            "event_kind": event_kind,
            "observation": payload,
            "policy_version": RETENTION_POLICY_VERSION,
            "observed_at": observation_time,
            "supersedes_observation_id": supersedes_observation_id,
        }
        semantic_digest = canonical_digest(semantic_record)
        observation_id = f"ckm_query_observation_{semantic_digest[:24]}"
        marker = {
            "event": "retained",
            "payload_removed": False,
            "policy_version": RETENTION_POLICY_VERSION,
        }
        return _PreparedObservation(
            observation_id=observation_id,
            schema_version=OBSERVATION_SCHEMA_VERSION,
            event_kind=event_kind,
            observation_json=canonical_json(payload),
            semantic_digest=semantic_digest,
            policy_version=RETENTION_POLICY_VERSION,
            observed_at=observation_time,
            expires_at=_expiry(observation_time),
            lifecycle="retained",
            lifecycle_marker_json=canonical_json(marker),
            supersedes_observation_id=supersedes_observation_id,
            deleted_at=None,
        )

    @staticmethod
    def _receipt_for_row(
        prepared: _PreparedObservation, row: sqlite3.Row | None
    ) -> QueryObservationReceipt:
        if row is None:
            raise QueryObservationError(
                "observation_persistence_failed",
                "query observation was not persisted",
                {},
            )
        if row["observation_json"] is None or not row["semantic_digest"]:
            raise QueryObservationError(
                "observation_unavailable",
                "query observation payload is unavailable for idempotent retry",
                {"lifecycle": row["lifecycle"]},
            )
        immutable_fields = (
            "observation_id",
            "schema_version",
            "event_kind",
            "observation_json",
            "semantic_digest",
            "policy_version",
            "observed_at",
            "expires_at",
            "supersedes_observation_id",
        )
        persisted_semantics = tuple(row[field] for field in immutable_fields)
        prepared_semantics = (
            prepared.observation_id,
            prepared.schema_version,
            prepared.event_kind,
            prepared.observation_json,
            prepared.semantic_digest,
            prepared.policy_version,
            prepared.observed_at,
            prepared.expires_at,
            prepared.supersedes_observation_id,
        )
        if persisted_semantics != prepared_semantics:
            raise QueryObservationError(
                "observation_identity_collision",
                "query observation identity resolves to different persisted semantics",
                {"observation_id": prepared.observation_id},
            )
        return QueryObservationReceipt(
            prepared.observation_id,
            str(row["event_kind"]),
            str(row["lifecycle"]),
            row["observation_json"] is not None,
        )

    @classmethod
    def _insert(
        cls, connection: sqlite3.Connection, prepared: _PreparedObservation
    ) -> QueryObservationReceipt:
        connection.execute(
            f"INSERT OR IGNORE INTO {OBSERVATION_TABLE} VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            prepared.row(),
        )
        row = connection.execute(
            f"SELECT * FROM {OBSERVATION_TABLE} WHERE observation_id = ?",
            (prepared.observation_id,),
        ).fetchone()
        return cls._receipt_for_row(prepared, row)

    def capture(
        self,
        outcome: ResultEnvelope | ErrorEnvelope | None,
        *,
        event_kind: str,
        metadata: QueryObservationInput,
        observed_at: str | None = None,
    ) -> QueryObservationReceipt:
        """Persist structural evidence only after the caller has an outcome."""
        prepared = self._prepare(
            outcome,
            event_kind=event_kind,
            metadata=metadata,
            observed_at=observed_at,
            supersedes_observation_id=None,
        )
        self.initialize()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._preflight(connection)
                receipt = self._insert(connection, prepared)
                connection.commit()
                return receipt
        except QueryObservationError:
            raise
        except sqlite3.Error as exc:
            raise QueryObservationError(
                "observation_persistence_failed",
                "query observation transaction failed",
                {"reason": str(exc)},
            ) from exc

    def storage_usage(self) -> dict[str, int]:
        self.initialize()
        with self._connect() as connection:
            count, bytes_ = connection.execute(
                f"SELECT COUNT(*), COALESCE(SUM({_PAYLOAD_BYTES_SQL}), 0) "
                f"FROM {OBSERVATION_TABLE} WHERE observation_json IS NOT NULL"
            ).fetchone()
        return {"count": int(count), "bytes": int(bytes_)}

    def replay(self, observation_id: str) -> dict[str, Any]:
        self.initialize()
        with self._connect() as connection:
            row = connection.execute(
                f"SELECT * FROM {OBSERVATION_TABLE} WHERE observation_id = ?",
                (observation_id,),
            ).fetchone()
        if row is None:
            raise QueryObservationError(
                "missing_observation", "query observation is unknown", {}
            )
        if row["observation_json"] is None:
            raise QueryObservationError(
                "observation_unavailable",
                "query observation payload is unavailable",
                {"lifecycle": row["lifecycle"]},
            )
        try:
            payload = json.loads(str(row["observation_json"]))
        except json.JSONDecodeError as exc:
            raise QueryObservationError(
                "corrupt_observation", "query observation payload is corrupt", {}
            ) from exc
        semantic_record = {
            "schema_version": row["schema_version"],
            "event_kind": row["event_kind"],
            "observation": payload,
            "policy_version": row["policy_version"],
            "observed_at": row["observed_at"],
            "supersedes_observation_id": row["supersedes_observation_id"],
        }
        expected_digest = canonical_digest(semantic_record)
        expected_id = f"ckm_query_observation_{expected_digest[:24]}"
        if (
            row["semantic_digest"] != expected_digest
            or row["observation_id"] != expected_id
        ):
            raise QueryObservationError(
                "corrupt_observation", "query observation integrity check failed", {}
            )
        return payload

    def preview_prune(
        self,
        *,
        now: str,
        earlier_than_365_days: bool = False,
        max_count: int | None = None,
        max_bytes: int | None = None,
    ) -> list[dict[str, str]]:
        self.initialize()
        if max_count is not None and max_count < 0:
            raise ValueError("max_count must be non-negative")
        if max_bytes is not None and max_bytes < 0:
            raise ValueError("max_bytes must be non-negative")
        current = _normalized_timestamp(now)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT observation_id, expires_at, {_PAYLOAD_BYTES_SQL} AS bytes "
                f"FROM {OBSERVATION_TABLE} WHERE observation_json IS NOT NULL "
                "ORDER BY observed_at, observation_id"
            ).fetchall()
        if earlier_than_365_days:
            return [
                {
                    "observation_id": str(row["observation_id"]),
                    "reason": "explicit_operator_prune_preview",
                }
                for row in rows
            ]
        selected = {
            str(row["observation_id"]): "retention_expired"
            for row in rows
            if str(row["expires_at"]) <= current
        }
        remaining = [
            row for row in rows if str(row["observation_id"]) not in selected
        ]
        remaining_count = len(remaining)
        remaining_bytes = sum(int(row["bytes"]) for row in remaining)
        for row in remaining:
            over_count = max_count is not None and remaining_count > max_count
            over_bytes = max_bytes is not None and remaining_bytes > max_bytes
            if not over_count and not over_bytes:
                break
            selected[str(row["observation_id"])] = (
                "storage_count_and_byte_cap"
                if over_count and over_bytes
                else "storage_count_cap"
                if over_count
                else "storage_byte_cap"
            )
            remaining_count -= 1
            remaining_bytes -= int(row["bytes"])
        return [
            {
                "observation_id": str(row["observation_id"]),
                "reason": selected[str(row["observation_id"])],
            }
            for row in rows
            if str(row["observation_id"]) in selected
        ]

    def prune(
        self,
        observation_ids: list[str],
        *,
        reason: str,
        at: str,
        previewed_observation_ids: list[str] | None = None,
    ) -> None:
        self.initialize()
        if reason not in PRUNE_LIFECYCLES:
            raise QueryObservationError(
                "invalid_prune_reason",
                "query observation pruning requires a bounded lifecycle reason",
                {},
            )
        current = _normalized_timestamp(at)
        previewed = set(previewed_observation_ids or [])
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._preflight(connection)
                for observation_id in observation_ids:
                    row = connection.execute(
                        f"SELECT expires_at, lifecycle, observation_json "
                        f"FROM {OBSERVATION_TABLE} WHERE observation_id = ?",
                        (observation_id,),
                    ).fetchone()
                    if row is None:
                        raise QueryObservationError(
                            "missing_observation", "query observation is unknown", {}
                        )
                    if row["observation_json"] is None:
                        raise QueryObservationError(
                            "observation_unavailable",
                            "query observation payload is already unavailable",
                            {"lifecycle": row["lifecycle"]},
                        )
                    if (
                        reason == "retention_expired"
                        and str(row["expires_at"]) > current
                    ):
                        raise QueryObservationError(
                            "retention_not_expired",
                            "query observation cannot expire before its retention cutoff",
                            {"observation_id": observation_id},
                        )
                    if str(row["expires_at"]) > current and observation_id not in previewed:
                        raise QueryObservationError(
                            "prune_preview_required",
                            "early observation pruning requires explicit preview",
                            {"observation_id": observation_id},
                        )
                    self._remove_payload(
                        connection, observation_id, lifecycle=reason, at=current
                    )
                connection.commit()
        except QueryObservationError:
            raise
        except sqlite3.Error as exc:
            raise QueryObservationError(
                "observation_persistence_failed",
                "query observation pruning failed",
                {"reason": str(exc)},
            ) from exc

    @staticmethod
    def _remove_payload(
        connection: sqlite3.Connection,
        observation_id: str,
        *,
        lifecycle: str,
        at: str,
    ) -> None:
        marker = {
            "event": lifecycle,
            "payload_removed": True,
            "at": at,
            "policy_version": RETENTION_POLICY_VERSION,
        }
        connection.execute(
            f"UPDATE {OBSERVATION_TABLE} SET observation_json = NULL, "
            "semantic_digest = '', lifecycle = ?, lifecycle_marker_json = ?, "
            "deleted_at = ? WHERE observation_id = ? AND observation_json IS NOT NULL",
            (lifecycle, canonical_json(marker), at, observation_id),
        )

    def delete(self, observation_id: str, *, at: str) -> None:
        self.initialize()
        current = _normalized_timestamp(at)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    f"SELECT observation_json FROM {OBSERVATION_TABLE} "
                    "WHERE observation_id = ?",
                    (observation_id,),
                ).fetchone()
                if row is None:
                    raise QueryObservationError(
                        "missing_observation", "query observation is unknown", {}
                    )
                if row["observation_json"] is None:
                    raise QueryObservationError(
                        "observation_unavailable",
                        "query observation payload is already unavailable",
                        {},
                    )
                self._remove_payload(
                    connection,
                    observation_id,
                    lifecycle="required_deletion",
                    at=current,
                )
                connection.commit()
        except QueryObservationError:
            raise
        except sqlite3.Error as exc:
            raise QueryObservationError(
                "observation_persistence_failed",
                "query observation deletion failed",
                {"reason": str(exc)},
            ) from exc

    def correct(
        self,
        observation_id: str,
        outcome: ResultEnvelope | ErrorEnvelope | None,
        *,
        event_kind: str,
        metadata: QueryObservationInput,
        observed_at: str,
    ) -> QueryObservationReceipt:
        prepared = self._prepare(
            outcome,
            event_kind=event_kind,
            metadata=metadata,
            observed_at=observed_at,
            supersedes_observation_id=observation_id,
        )
        self.initialize()
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                self._preflight(connection)
                prior = connection.execute(
                    f"SELECT lifecycle, observation_json, lifecycle_marker_json "
                    f"FROM {OBSERVATION_TABLE} "
                    "WHERE observation_id = ?",
                    (observation_id,),
                ).fetchone()
                if prior is None:
                    raise QueryObservationError(
                        "missing_observation", "query observation is unknown", {}
                    )
                if prior["observation_json"] is None:
                    raise QueryObservationError(
                        "observation_unavailable",
                        "query observation payload is unavailable for correction",
                        {"lifecycle": prior["lifecycle"]},
                    )
                if prior["lifecycle"] == "superseded":
                    try:
                        marker = json.loads(str(prior["lifecycle_marker_json"]))
                    except json.JSONDecodeError as exc:
                        raise QueryObservationError(
                            "observation_store_unsupported",
                            "query observation lifecycle marker is corrupt",
                            {},
                        ) from exc
                    if not isinstance(marker, dict):
                        raise QueryObservationError(
                            "observation_store_unsupported",
                            "query observation lifecycle marker is corrupt",
                            {},
                        )
                    existing = connection.execute(
                        f"SELECT * FROM {OBSERVATION_TABLE} WHERE observation_id = ?",
                        (prepared.observation_id,),
                    ).fetchone()
                    if marker.get("successor") == prepared.observation_id:
                        receipt = self._receipt_for_row(prepared, existing)
                        connection.commit()
                        return receipt
                if prior["lifecycle"] != "retained":
                    raise QueryObservationError(
                        "correction_not_allowed",
                        "only a retained observation may be corrected",
                        {"lifecycle": prior["lifecycle"]},
                    )
                receipt = self._insert(connection, prepared)
                connection.execute(
                    f"UPDATE {OBSERVATION_TABLE} SET lifecycle = 'superseded', "
                    "lifecycle_marker_json = ? WHERE observation_id = ?",
                    (
                        canonical_json(
                            {
                                "event": "superseded",
                                "successor": receipt.observation_id,
                                "payload_removed": False,
                            }
                        ),
                        observation_id,
                    ),
                )
                connection.commit()
                return receipt
        except QueryObservationError:
            raise
        except sqlite3.Error as exc:
            raise QueryObservationError(
                "observation_persistence_failed",
                "query observation correction failed",
                {"reason": str(exc)},
            ) from exc
