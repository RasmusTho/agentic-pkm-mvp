"""Read-only, transport-neutral CKM snapshot queries.

This module intentionally does not use :class:`CkmStore`: that store owns
schema/bootstrap and mutation behaviour.  A supported query must instead be
able to prove that it opened an already-existing database without creating or
repairing any BuilderOps surface.
"""

from __future__ import annotations

import sqlite3
import stat
from pathlib import Path
from typing import Any, Callable, Mapping

from app.builderops.ckm.contracts import (
    CkmContractError,
    CkmStateIdentity,
    CompletenessManifest,
    ErrorEnvelope,
    ObjectClassCompleteness,
    ResourceDto,
    ResultEnvelope,
    SnapshotManifest,
    TaggedValue,
    canonical_digest,
    canonical_query_digest,
    validate_contract_request,
)
from app.builderops.ckm.schema import (
    CKM_REQUIRED_COLUMNS,
    CKM_REQUIRED_QUERY_INDEXES,
    CKM_SCHEMA_VERSION,
    CKM_TABLE_NAMES,
)


DEFAULT_CAPTURE_LIMIT = 500
_SUPPORTED_FILTERS = {
    "capability": frozenset({"public_ids", "subtree_root_public_id"}),
    "artifact": frozenset({"unlinked"}),
    "evidence_edge": frozenset({"capability_public_id"}),
    "assessment": frozenset({"capability_public_id"}),
    "finding": frozenset({"capability_public_id"}),
}
_SQLITE_RECOVERY_SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
_SQLITE_WAL_SIDECAR_SUFFIXES = ("-wal", "-shm")
_SQLITE_HEADER_MAGIC = b"SQLite format 3\x00"
_SQLITE_ROLLBACK_HEADER_VERSIONS = b"\x01\x01"
_SQLITE_WAL_HEADER_VERSIONS = b"\x02\x02"


class CkmQueryService:
    """The Q1b query seam.  It has no write-capable store dependency."""

    def __init__(
        self,
        db_path: Path,
        *,
        capture_limit: int = DEFAULT_CAPTURE_LIMIT,
        _connection_factory: Callable[[str], sqlite3.Connection] | None = None,
    ) -> None:
        if capture_limit < 1:
            raise ValueError("capture_limit must be positive")
        self._db_path = Path(db_path)
        self._capture_limit = capture_limit
        self._connection_factory = _connection_factory or (
            lambda uri: sqlite3.connect(uri, uri=True)
        )

    def list_capabilities(self, **request: Any) -> ResultEnvelope | ErrorEnvelope:
        return self._query(resource_type="capability", public_id=None, **request)

    def get_capability(self, public_id: str, **request: Any) -> ResultEnvelope | ErrorEnvelope:
        return self._query(resource_type="capability", public_id=public_id, **request)

    def list_resources(self, resource_type: str, **request: Any) -> ResultEnvelope | ErrorEnvelope:
        return self._query(resource_type=resource_type, public_id=None, **request)

    def _query(self, *, resource_type: str, public_id: str | None, **request: Any) -> ResultEnvelope | ErrorEnvelope:
        try:
            raw_filters = request.get("filters")
            filters = self._canonical_filters(resource_type, raw_filters)
            if raw_filters is not None:
                request["filters"] = filters
            operation = (
                "get_capability"
                if public_id
                else "list_capabilities"
                if resource_type == "capability" and raw_filters is None
                else "list_resources"
            )
            query = {
                "operation": operation,
                "public_id": public_id,
            }
            if operation == "list_resources":
                query["resource_type"] = resource_type
            query.update({key: value for key, value in request.items() if value is not None})
            validate_contract_request(resource_type=resource_type, supported_filters=_SUPPORTED_FILTERS.get(resource_type, frozenset()), **request)
            if not self._db_path.is_file():
                raise CkmContractError("missing_store", "CKM database does not exist", {"path": str(self._db_path)})
            snapshot_identity = self._snapshot_identity()
            self._refuse_recovery_sidecars()
            self._validate_readable_header()
            # ``mode=ro`` is the important guard: SQLite cannot create the DB,
            # WAL, schema, or parent directory through this connection.  Build
            # the file URI through pathlib so reserved path characters cannot
            # be parsed as URI query or fragment delimiters. WAL-mode stores are
            # refused from their header before SQLite opens the live path.
            try:
                conn = self._connection_factory(f"{self._db_path.absolute().as_uri()}?mode=ro")
            except sqlite3.Error as exc:
                raise CkmContractError(
                    "unsupported_store",
                    "CKM store could not be opened read-only",
                    {"reason": str(exc)},
                ) from exc
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA query_only = ON")
                conn.execute("BEGIN")  # exactly one explicit read transaction
                self._validate_schema(conn)
                result = self._read_resources(conn, resource_type=resource_type, public_id=public_id, filters=filters, query=query)
                self._refuse_recovery_sidecars(include_rollback_journal=False)
                if self._snapshot_identity() != snapshot_identity:
                    raise CkmContractError(
                        "unsupported_store",
                        "CKM database changed during immutable snapshot capture",
                        {},
                    )
                conn.commit()
                return result
            except CkmContractError:
                conn.rollback()
                raise
            except (sqlite3.Error, ValueError) as exc:
                conn.rollback()
                raise CkmContractError("unsupported_store", "CKM store is unavailable or unsupported", {"reason": str(exc)}) from exc
            finally:
                conn.close()
        except CkmContractError as exc:
            return ErrorEnvelope(exc)

    def _canonical_filters(self, resource_type: str, raw: Any) -> dict[str, Any]:
        if raw is None:
            return {}
        if not isinstance(raw, Mapping):
            raise CkmContractError("unsupported_filter", "filters must be an object", {})
        unknown = sorted(set(raw) - set(_SUPPORTED_FILTERS.get(resource_type, frozenset())))
        if unknown:
            raise CkmContractError("unsupported_filter", "unsupported CKM filter", {"filters": unknown})
        filters: dict[str, Any] = {}
        for key in sorted(raw):
            value = raw[key]
            if key == "public_ids":
                if not isinstance(value, (list, tuple)) or not value or len(value) > self._capture_limit or any(not isinstance(item, str) or not item for item in value):
                    raise CkmContractError("unsupported_filter", "public_ids must be a non-empty bounded string list", {"limit": self._capture_limit})
                filters[key] = sorted(set(value))
            elif key in {"subtree_root_public_id", "capability_public_id"}:
                if not isinstance(value, str) or not value:
                    raise CkmContractError("unsupported_filter", f"{key} must be a public ID", {})
                filters[key] = value
            elif key == "unlinked":
                if value is not True:
                    raise CkmContractError("unsupported_filter", "unlinked only supports true", {})
                filters[key] = True
        if "public_ids" in filters and "subtree_root_public_id" in filters:
            raise CkmContractError("unsupported_filter", "capability filters cannot combine public_ids and subtree", {})
        return filters

    def _snapshot_identity(self) -> tuple[int, int, int, int]:
        try:
            snapshot_stat = self._db_path.lstat()
        except OSError as exc:
            raise CkmContractError(
                "unsupported_store",
                "CKM database identity could not be verified",
                {"reason": str(exc)},
            ) from exc
        if not stat.S_ISREG(snapshot_stat.st_mode):
            raise CkmContractError(
                "unsupported_store",
                "CKM database path is not a regular file",
                {},
            )
        return (snapshot_stat.st_dev, snapshot_stat.st_ino, snapshot_stat.st_size, snapshot_stat.st_mtime_ns)

    def _validate_readable_header(self) -> None:
        try:
            with self._db_path.open("rb") as stream:
                header = stream.read(20)
        except OSError as exc:
            raise CkmContractError(
                "unsupported_store",
                "CKM database header could not be read",
                {"reason": str(exc)},
            ) from exc
        if len(header) < 20 or header[:16] != _SQLITE_HEADER_MAGIC:
            raise CkmContractError("unsupported_store", "CKM database header is unsupported", {})
        versions = header[18:20]
        if versions == _SQLITE_WAL_HEADER_VERSIONS:
            raise CkmContractError(
                "unsupported_store",
                "CKM WAL-mode stores require a separately fenced snapshot",
                {"journal_mode": "wal"},
            )
        if versions != _SQLITE_ROLLBACK_HEADER_VERSIONS:
            raise CkmContractError(
                "unsupported_store",
                "CKM database journaling mode is unsupported",
                {"header_versions": list(versions)},
            )

    def _refuse_recovery_sidecars(self, *, include_rollback_journal: bool = True) -> None:
        suffixes = _SQLITE_RECOVERY_SIDECAR_SUFFIXES if include_rollback_journal else _SQLITE_WAL_SIDECAR_SUFFIXES
        sidecars = [
            path.name
            for suffix in suffixes
            if (path := Path(f"{self._db_path}{suffix}")).exists()
        ]
        if sidecars:
            raise CkmContractError(
                "unsupported_store",
                "CKM store has SQLite recovery sidecars that cannot be consumed without write risk",
                {"sidecars": sidecars},
            )

    @staticmethod
    def _validate_schema(conn: sqlite3.Connection) -> None:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not set(CKM_TABLE_NAMES).issubset(tables):
            raise CkmContractError("unsupported_store", "CKM schema is incomplete", {"missing_tables": sorted(set(CKM_TABLE_NAMES) - tables)})
        for table, required in CKM_REQUIRED_COLUMNS.items():
            columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
            if not required.issubset(columns):
                raise CkmContractError("unsupported_store", "CKM schema is unsupported", {"table": table})
        indexes = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        missing_indexes = sorted(CKM_REQUIRED_QUERY_INDEXES - indexes)
        if missing_indexes:
            raise CkmContractError("unsupported_store", "CKM query indexes are incomplete", {"missing_indexes": missing_indexes})
        state_rows = conn.execute("SELECT epoch, state_revision, schema_version FROM ckm_state WHERE singleton = 1").fetchall()
        if len(state_rows) != 1 or int(state_rows[0]["schema_version"]) != CKM_SCHEMA_VERSION:
            raise CkmContractError("unsupported_version", "CKM state schema version is unsupported", {})

    def _read_resources(
        self,
        conn: sqlite3.Connection,
        *,
        resource_type: str,
        public_id: str | None,
        filters: Mapping[str, Any],
        query: Mapping[str, Any],
    ) -> ResultEnvelope:
        if resource_type == "capability":
            return self._read_capabilities(conn, public_id=public_id, filters=filters, query=query)
        if public_id is not None:
            raise CkmContractError("unsupported_filter", "exact lookup is supported only for capability", {})
        return self._read_related_resources(conn, resource_type=resource_type, filters=filters, query=query)

    def _read_capabilities(self, conn: sqlite3.Connection, *, public_id: str | None, filters: Mapping[str, Any], query: Mapping[str, Any]) -> ResultEnvelope:
        state_row = conn.execute("SELECT epoch, state_revision, schema_version FROM ckm_state WHERE singleton = 1").fetchone()
        assert state_row is not None
        state = CkmStateIdentity(str(state_row["epoch"]), int(state_row["state_revision"]), int(state_row["schema_version"]))
        total = int(conn.execute("SELECT COUNT(*) FROM ckm_capability").fetchone()[0])
        if public_id is None and not filters and total > self._capture_limit:
            raise CkmContractError("snapshot_too_large", "complete capability snapshot exceeds configured bound", {"limit": self._capture_limit, "total": total})
        if public_id is None:
            if "public_ids" in filters:
                values = filters["public_ids"]
                placeholders = ",".join("?" for _ in values)
                rows = conn.execute(
                    f"""SELECT capability.*, EXISTS(SELECT 1 FROM ckm_assessment AS assessment WHERE assessment.capability_id = capability.id) AS has_assessment
                    FROM ckm_capability AS capability
                    JOIN ckm_public_identity AS identity
                      ON identity.public_id = capability.public_id
                     AND identity.resource_type = 'capability'
                     AND identity.status = 'active'
                    WHERE capability.public_id IN ({placeholders})
                    ORDER BY capability.public_id
                    """,
                    tuple(values),
                ).fetchall()
                returned = {str(row["public_id"]) for row in rows}
                for requested in values:
                    if requested not in returned:
                        self._raise_missing_capability_identity(conn, requested)
            elif "subtree_root_public_id" in filters:
                subtree_root_public_id = str(filters["subtree_root_public_id"])
                active_root = conn.execute(
                    """
                    SELECT 1
                    FROM ckm_capability AS capability
                    JOIN ckm_public_identity AS identity
                      ON identity.public_id = capability.public_id
                     AND identity.resource_type = 'capability'
                     AND identity.status = 'active'
                    WHERE capability.public_id = ?
                    """,
                    (subtree_root_public_id,),
                ).fetchone()
                if active_root is None:
                    self._raise_missing_capability_identity(conn, subtree_root_public_id)
                rows = conn.execute(
                    """
                    WITH RECURSIVE subtree(id) AS (
                        SELECT id FROM ckm_capability WHERE public_id = ?
                        UNION
                        SELECT child.id FROM ckm_capability AS child JOIN subtree ON child.parent_id = subtree.id
                    )
                    SELECT capability.*, EXISTS(SELECT 1 FROM ckm_assessment AS assessment WHERE assessment.capability_id = capability.id) AS has_assessment
                    FROM ckm_capability AS capability
                    JOIN subtree ON subtree.id = capability.id
                    JOIN ckm_public_identity AS identity
                      ON identity.public_id = capability.public_id
                     AND identity.resource_type = 'capability'
                     AND identity.status = 'active'
                    ORDER BY capability.public_id
                    """,
                    (subtree_root_public_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """SELECT capability.*, EXISTS(SELECT 1 FROM ckm_assessment AS assessment WHERE assessment.capability_id = capability.id) AS has_assessment
                    FROM ckm_capability AS capability
                    JOIN ckm_public_identity AS identity
                      ON identity.public_id = capability.public_id
                     AND identity.resource_type = 'capability'
                     AND identity.status = 'active'
                    ORDER BY capability.public_id
                    """
                ).fetchall()
            if len(rows) > self._capture_limit:
                raise CkmContractError("snapshot_too_large", "filtered capability snapshot exceeds configured bound", {"limit": self._capture_limit, "total": len(rows)})
            if not filters and len(rows) != total:
                active_total = self._active_capability_identity_count(conn)
                if active_total != total:
                    raise CkmContractError(
                        "unsupported_store",
                        "CKM capability public identities do not match capability rows",
                        {"declared_total": total, "active_identity_total": active_total},
                    )
                raise CkmContractError(
                    "incomplete_snapshot",
                    "complete capability snapshot could not be captured",
                    {"declared_total": total, "captured_total": len(rows)},
                )
        else:
            rows = conn.execute(
                """SELECT capability.*, EXISTS(SELECT 1 FROM ckm_assessment AS assessment WHERE assessment.capability_id = capability.id) AS has_assessment
                FROM ckm_capability AS capability
                JOIN ckm_public_identity AS identity
                  ON identity.public_id = capability.public_id
                 AND identity.resource_type = 'capability'
                 AND identity.status = 'active'
                WHERE capability.public_id = ?
                ORDER BY capability.public_id
                """,
                (public_id,),
            ).fetchall()
            if not rows:
                self._raise_missing_capability_identity(conn, public_id)
        # A state revision must be stable over the complete read set.  The
        # transaction gives the snapshot guarantee; the second read makes an
        # accidental mixed-epoch fixture fail closed rather than look valid.
        end_state = conn.execute("SELECT epoch, state_revision FROM ckm_state WHERE singleton = 1").fetchone()
        if end_state is None or (str(end_state["epoch"]), int(end_state["state_revision"])) != (state.epoch, state.state_revision):
            raise CkmContractError("mixed_epoch", "CKM state changed during snapshot capture", {})
        resources = tuple(self._dto(row, has_assessment=bool(row["has_assessment"])) for row in rows)
        read_set = {"capability": tuple(item.public_id for item in resources)}
        completeness = CompletenessManifest((ObjectClassCompleteness("capability", included=len(resources), filtered=total - len(resources)),), complete=True)
        watermarks = {str(row["source"]): str(row["value"]) for row in conn.execute("SELECT source, value FROM ckm_watermark ORDER BY source")}
        provenance = tuple({"source_ref": item.provenance[0]["source_ref"]} for item in resources)
        # Taxonomy identity belongs to the state, not to one query subset.
        # In particular, exact lookup and complete capture at the same revision
        # must bind the same taxonomy digest.
        taxonomy = [
            {
                "public_id": str(row["public_id"]),
                "parent_public_id": str(row["parent_public_id"] or ""),
                "lifecycle": str(row["lifecycle"]),
            }
            for row in conn.execute(
                """
                SELECT child.public_id, parent.public_id AS parent_public_id, child.lifecycle
                FROM ckm_capability AS child
                LEFT JOIN ckm_capability AS parent ON parent.id = child.parent_id
                ORDER BY child.public_id
                """
            )
        ]
        snapshot = SnapshotManifest.build(state=state, taxonomy_digest=canonical_digest(taxonomy), watermarks=watermarks, provenance=provenance, completeness=completeness, read_set=read_set)
        return ResultEnvelope(resource_type="capability", query_digest=canonical_query_digest(query), snapshot=snapshot, resources=resources)

    @staticmethod
    def _active_capability_identity_count(conn: sqlite3.Connection) -> int:
        return int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM ckm_capability AS capability
                JOIN ckm_public_identity AS identity
                  ON identity.public_id = capability.public_id
                 AND identity.resource_type = 'capability'
                 AND identity.status = 'active'
                """
            ).fetchone()[0]
        )

    @staticmethod
    def _raise_missing_capability_identity(conn: sqlite3.Connection, public_id: str) -> None:
        identity = conn.execute(
            "SELECT status FROM ckm_public_identity WHERE public_id = ? AND resource_type = 'capability'",
            (public_id,),
        ).fetchone()
        if identity is not None and identity["status"] == "tombstone":
            successors = conn.execute(
                "SELECT successor_public_id, relation FROM ckm_identity_successor WHERE source_public_id = ? ORDER BY successor_public_id",
                (public_id,),
            ).fetchall()
            raise CkmContractError(
                "tombstoned_resource",
                "CKM capability public ID is tombstoned",
                {"public_id": public_id, "successors": [dict(row) for row in successors]},
            )
        raise CkmContractError("missing_resource", "CKM capability public ID was not found", {"public_id": public_id})

    def _read_related_resources(self, conn: sqlite3.Connection, *, resource_type: str, filters: Mapping[str, Any], query: Mapping[str, Any]) -> ResultEnvelope:
        table = {
            "artifact": "ckm_artifact",
            "evidence_edge": "ckm_evidence_edge",
            "assessment": "ckm_assessment",
            "finding": "ckm_finding",
        }.get(resource_type)
        if table is None:
            raise CkmContractError("unsupported_resource", "unsupported CKM resource type", {"resource_type": resource_type})
        state_row = conn.execute("SELECT epoch, state_revision, schema_version FROM ckm_state WHERE singleton = 1").fetchone()
        assert state_row is not None
        state = CkmStateIdentity(str(state_row["epoch"]), int(state_row["state_revision"]), int(state_row["schema_version"]))
        total = int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        parameters: tuple[Any, ...] = ()
        if resource_type == "artifact" and filters.get("unlinked") is True:
            sql = "SELECT artifact.* FROM ckm_artifact AS artifact WHERE NOT EXISTS (SELECT 1 FROM ckm_evidence_edge AS edge WHERE edge.artifact_id = artifact.id) ORDER BY artifact.public_id"
        elif "capability_public_id" in filters:
            sql = f"SELECT resource.* FROM {table} AS resource JOIN ckm_capability AS capability ON capability.id = resource.capability_id WHERE capability.public_id = ? ORDER BY resource.public_id"
            parameters = (filters["capability_public_id"],)
        else:
            sql = f"SELECT resource.* FROM {table} AS resource ORDER BY resource.public_id"
        count_sql = f"SELECT COUNT(*) FROM ({sql.rsplit(' ORDER BY ', 1)[0]}) AS bounded_scope"
        selected_total = int(conn.execute(count_sql, parameters).fetchone()[0])
        if selected_total > self._capture_limit:
            raise CkmContractError("snapshot_too_large", "complete filtered snapshot exceeds configured bound", {"limit": self._capture_limit, "total": selected_total, "resource_type": resource_type})
        rows = conn.execute(sql, parameters).fetchall()
        end_state = conn.execute("SELECT epoch, state_revision FROM ckm_state WHERE singleton = 1").fetchone()
        if end_state is None or (str(end_state["epoch"]), int(end_state["state_revision"])) != (state.epoch, state.state_revision):
            raise CkmContractError("mixed_epoch", "CKM state changed during snapshot capture", {})
        resources = tuple(self._related_dto(resource_type, row) for row in rows)
        read_set = {resource_type: tuple(item.public_id for item in resources)}
        completeness = CompletenessManifest((ObjectClassCompleteness(resource_type, included=len(resources), filtered=total - len(resources)),), complete=True)
        watermarks = {str(row["source"]): str(row["value"]) for row in conn.execute("SELECT source, value FROM ckm_watermark ORDER BY source")}
        provenance = tuple({"source_ref": item.provenance[0]["source_ref"]} for item in resources)
        taxonomy = [
            {"public_id": str(row["public_id"]), "parent_public_id": str(row["parent_public_id"] or ""), "lifecycle": str(row["lifecycle"])}
            for row in conn.execute("SELECT child.public_id, parent.public_id AS parent_public_id, child.lifecycle FROM ckm_capability AS child LEFT JOIN ckm_capability AS parent ON parent.id = child.parent_id ORDER BY child.public_id")
        ]
        snapshot = SnapshotManifest.build(state=state, taxonomy_digest=canonical_digest(taxonomy), watermarks=watermarks, provenance=provenance, completeness=completeness, read_set=read_set)
        return ResultEnvelope(resource_type=resource_type, query_digest=canonical_query_digest(query), snapshot=snapshot, resources=resources)

    @staticmethod
    def _related_dto(resource_type: str, row: sqlite3.Row) -> ResourceDto:
        if resource_type == "artifact":
            return ResourceDto(public_id=str(row["public_id"]), resource_type=resource_type, display_name=str(row["source_ref"]), lifecycle="confirmed", candidate=False, provenance=({"source_ref": str(row["source_ref"])},), values={"artifact_kind": TaggedValue.measured(str(row["artifact_kind"])), "source": TaggedValue.measured(str(row["source"])), "watermark": TaggedValue.measured(str(row["watermark"]))})
        if resource_type == "evidence_edge":
            lifecycle = str(row["lifecycle"])
            return ResourceDto(public_id=str(row["public_id"]), resource_type=resource_type, display_name=str(row["evidence_kind"]), lifecycle=lifecycle, candidate=lifecycle == "candidate", provenance=({"source_ref": str(row["source_ref"])},), values={"polarity": TaggedValue.measured(str(row["polarity"])), "maturity_dimension": TaggedValue.measured(str(row["maturity_dimension"])), "confidence": TaggedValue.measured(float(row["confidence"]))})
        if resource_type == "assessment":
            return ResourceDto(public_id=str(row["public_id"]), resource_type=resource_type, display_name=str(row["aggregate_formula_id"]), lifecycle="confirmed", candidate=False, provenance=({"source_ref": f"assessment:{row['asserted_at']}"},), values={"aggregate": TaggedValue.measured(float(row["aggregate"])), "low_confidence": TaggedValue.measured(bool(row["low_confidence"]))})
        return ResourceDto(public_id=str(row["public_id"]), resource_type=resource_type, display_name=str(row["kind"]), lifecycle="confirmed", candidate=False, provenance=({"source_ref": f"finding:{row['public_id']}"},), values={"dimension": TaggedValue.measured(str(row["dimension"])), "statement": TaggedValue.measured(str(row["statement"]))})

    @staticmethod
    def _dto(row: sqlite3.Row, *, has_assessment: bool) -> ResourceDto:
        lifecycle = str(row["lifecycle"])
        assessment = (
            TaggedValue.unsupported("Q1 query does not expose persisted assessment history")
            if has_assessment
            else TaggedValue.unassessed("capability has no persisted assessment")
        )
        return ResourceDto(
            public_id=str(row["public_id"]), resource_type="capability", display_name=str(row["name"]), lifecycle=lifecycle,
            candidate=lifecycle == "candidate", provenance=({"source_ref": str(row["existence_provenance"])},),
            values={"definition": TaggedValue.measured(str(row["definition"])), "boundary_ref": TaggedValue.measured(str(row["boundary_ref"])) if row["boundary_ref"] else TaggedValue.missing("capability has no boundary reference"), "assessment": assessment},
        )
