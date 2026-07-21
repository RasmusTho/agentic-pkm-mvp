"""Read-only, transport-neutral CKM snapshot queries.

This module intentionally does not use :class:`CkmStore`: that store owns
schema/bootstrap and mutation behaviour.  A supported query must instead be
able to prove that it opened an already-existing database without creating or
repairing any BuilderOps surface.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Mapping

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
from app.builderops.ckm.schema import CKM_REQUIRED_COLUMNS, CKM_SCHEMA_VERSION, CKM_TABLE_NAMES


DEFAULT_CAPTURE_LIMIT = 500


class CkmQueryService:
    """The Q1b query seam.  It has no write-capable store dependency."""

    def __init__(self, db_path: Path, *, capture_limit: int = DEFAULT_CAPTURE_LIMIT) -> None:
        if capture_limit < 1:
            raise ValueError("capture_limit must be positive")
        self._db_path = Path(db_path)
        self._capture_limit = capture_limit

    def list_capabilities(self, **request: Any) -> ResultEnvelope | ErrorEnvelope:
        return self._query(public_id=None, **request)

    def get_capability(self, public_id: str, **request: Any) -> ResultEnvelope | ErrorEnvelope:
        return self._query(public_id=public_id, **request)

    def _query(self, *, public_id: str | None, **request: Any) -> ResultEnvelope | ErrorEnvelope:
        query = {"operation": "get_capability" if public_id else "list_capabilities", "public_id": public_id}
        query.update({key: value for key, value in request.items() if value is not None})
        try:
            validate_contract_request(resource_type="capability", **request)
            if not self._db_path.is_file():
                raise CkmContractError("missing_store", "CKM database does not exist", {"path": str(self._db_path)})
            # ``mode=ro`` is the important guard: SQLite cannot create the DB,
            # WAL, schema, or parent directory through this connection.
            conn = sqlite3.connect(f"file:{self._db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            try:
                conn.execute("PRAGMA query_only = ON")
                conn.execute("BEGIN")  # exactly one explicit read transaction
                self._validate_schema(conn)
                result = self._read_capabilities(conn, public_id=public_id, query=query)
                conn.commit()
                return result
            except sqlite3.Error as exc:
                conn.rollback()
                raise CkmContractError("unsupported_store", "CKM store is unavailable or unsupported", {"reason": str(exc)}) from exc
            finally:
                conn.close()
        except CkmContractError as exc:
            return ErrorEnvelope(exc)

    @staticmethod
    def _validate_schema(conn: sqlite3.Connection) -> None:
        tables = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not set(CKM_TABLE_NAMES).issubset(tables):
            raise CkmContractError("unsupported_store", "CKM schema is incomplete", {"missing_tables": sorted(set(CKM_TABLE_NAMES) - tables)})
        for table, required in CKM_REQUIRED_COLUMNS.items():
            columns = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
            if not required.issubset(columns):
                raise CkmContractError("unsupported_store", "CKM schema is unsupported", {"table": table})
        state_rows = conn.execute("SELECT epoch, state_revision, schema_version FROM ckm_state WHERE singleton = 1").fetchall()
        if len(state_rows) != 1 or int(state_rows[0]["schema_version"]) != CKM_SCHEMA_VERSION:
            raise CkmContractError("unsupported_version", "CKM state schema version is unsupported", {})

    def _read_capabilities(self, conn: sqlite3.Connection, *, public_id: str | None, query: Mapping[str, Any]) -> ResultEnvelope:
        state_row = conn.execute("SELECT epoch, state_revision, schema_version FROM ckm_state WHERE singleton = 1").fetchone()
        assert state_row is not None
        state = CkmStateIdentity(str(state_row["epoch"]), int(state_row["state_revision"]), int(state_row["schema_version"]))
        total = int(conn.execute("SELECT COUNT(*) FROM ckm_capability").fetchone()[0])
        if public_id is None and total > self._capture_limit:
            raise CkmContractError("snapshot_too_large", "complete capability snapshot exceeds configured bound", {"limit": self._capture_limit, "total": total})
        if public_id is None:
            rows = conn.execute("SELECT * FROM ckm_capability ORDER BY public_id").fetchall()
        else:
            rows = conn.execute("SELECT * FROM ckm_capability WHERE public_id = ? ORDER BY public_id", (public_id,)).fetchall()
            if not rows:
                raise CkmContractError("missing_resource", "CKM capability public ID was not found", {"public_id": public_id})
        # A state revision must be stable over the complete read set.  The
        # transaction gives the snapshot guarantee; the second read makes an
        # accidental mixed-epoch fixture fail closed rather than look valid.
        end_state = conn.execute("SELECT epoch, state_revision FROM ckm_state WHERE singleton = 1").fetchone()
        if end_state is None or (str(end_state["epoch"]), int(end_state["state_revision"])) != (state.epoch, state.state_revision):
            raise CkmContractError("mixed_epoch", "CKM state changed during snapshot capture", {})
        resources = tuple(self._dto(row) for row in rows)
        read_set = {"capability": tuple(item.public_id for item in resources)}
        completeness = CompletenessManifest((ObjectClassCompleteness("capability", included=len(resources), filtered=(total - len(resources)) if public_id else 0),), complete=True)
        watermarks = {str(row["source"]): str(row["value"]) for row in conn.execute("SELECT source, value FROM ckm_watermark ORDER BY source")}
        provenance = tuple({"source_ref": item.provenance[0]["source_ref"]} for item in resources) or ({"source_ref": "ckm:empty"},)
        snapshot = SnapshotManifest.build(state=state, taxonomy_digest=canonical_digest([item.public_id for item in resources]), watermarks=watermarks, provenance=provenance, completeness=completeness, read_set=read_set)
        return ResultEnvelope(resource_type="capability", query_digest=canonical_query_digest(query), snapshot=snapshot, resources=resources)

    @staticmethod
    def _dto(row: sqlite3.Row) -> ResourceDto:
        lifecycle = str(row["lifecycle"])
        return ResourceDto(
            public_id=str(row["public_id"]), resource_type="capability", display_name=str(row["name"]), lifecycle=lifecycle,
            candidate=lifecycle == "candidate", provenance=({"source_ref": str(row["existence_provenance"])},),
            values={"definition": TaggedValue.measured(str(row["definition"])), "boundary_ref": TaggedValue.measured(str(row["boundary_ref"])) if row["boundary_ref"] else TaggedValue.missing("capability has no boundary reference"), "assessment": TaggedValue.unassessed("Q1 query does not reconstruct assessment history")},
        )
