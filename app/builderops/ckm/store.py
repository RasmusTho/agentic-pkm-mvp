"""SQLite-backed store for the Capability Evidence Graph (CEG).

Follows the pattern of ``app/builderops/store.py``: a thin class over a
shared SQLite connection with idempotent upserts on natural keys
(INV-CKM-7), an append-only assessment write path (INV-CKM-5), and a
``rebuild()`` that drops and recreates only the ``ckm_*`` tables
(INV-CKM-4). Schema creation and rebuild events are recorded as BuilderOps
receipts through the existing receipt mechanism
(``app.builderops.store.SqliteBuilderOpsStore.append_receipt``) so the CKM
never invents its own receipt/authority path.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Mapping
from uuid import uuid4

from app.builderops.config import BuilderOpsPaths, load_paths, validate_db_path_outside_vault
from app.builderops.store import SqliteBuilderOpsStore

from app.builderops.ckm.models import (
    MATURITY_DIMENSIONS,
    CkmArtifact,
    CkmAssessment,
    CkmCapability,
    CkmEvidenceEdge,
    CkmFinding,
    CkmValidationError,
    new_id,
    utc_now,
)
from app.builderops.ckm.schema import CKM_DDL_STATEMENTS, CKM_TABLE_NAMES

JsonDict = dict[str, Any]


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _loads(value: str) -> Any:
    return json.loads(value)


class CkmStore:
    """Durable store for the CEG, additive to the BuilderOps SQLite substrate."""

    def __init__(
        self,
        db_path: Path,
        *,
        receipt_store: SqliteBuilderOpsStore | None = None,
    ) -> None:
        validate_db_path_outside_vault(Path(db_path))
        self._db_path = Path(db_path)
        self._receipt_store = receipt_store or SqliteBuilderOpsStore(self._db_path)

    @property
    def db_path(self) -> Path:
        return self._db_path

    @classmethod
    def open_default(cls, paths: BuilderOpsPaths | None = None) -> "CkmStore":
        resolved_paths = paths or load_paths()
        resolved_paths.ensure()
        return cls(resolved_paths.db_path)

    def _connect(self) -> sqlite3.Connection:
        validate_db_path_outside_vault(self._db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    # --- Schema lifecycle ----------------------------------------------------

    def ensure_schema(self) -> dict[str, Any]:
        """Create ``ckm_*`` tables if absent and receipt the first ensure."""

        # Ensure the shared BuilderOps substrate (builderops_records, etc.)
        # exists first: receipt writes below depend on it.
        self._receipt_store.initialize()
        with self._connect() as conn:
            self._migrate_evidence_edge_basis(conn)
            for statement in CKM_DDL_STATEMENTS:
                conn.execute(statement)
            conn.commit()
        prior_receipts = [
            receipt
            for receipt in self._receipt_store.list_records("BuilderOpsReceipt")
            if receipt.get("event_type") == "ckm_schema_ensured"
        ]
        if prior_receipts:
            return prior_receipts[-1]
        return self._emit_schema_receipt(event_type="ckm_schema_ensured", action="ensure_schema")

    @staticmethod
    def _migrate_evidence_edge_basis(conn: sqlite3.Connection) -> None:
        columns = conn.execute("PRAGMA table_info(ckm_evidence_edge)").fetchall()
        if not columns or any(row["name"] == "basis" for row in columns):
            return
        conn.execute("ALTER TABLE ckm_evidence_edge RENAME TO ckm_evidence_edge_v1")
        edge_ddl = next(
            statement for statement in CKM_DDL_STATEMENTS
            if "CREATE TABLE IF NOT EXISTS ckm_evidence_edge" in statement
        )
        conn.execute(edge_ddl)
        conn.execute(
            """
            INSERT INTO ckm_evidence_edge (
                id, artifact_id, capability_id, evidence_kind, polarity,
                maturity_dimension, confidence, extraction_method, model,
                provider, lifecycle, source_ref, basis, created_at, updated_at
            )
            SELECT id, artifact_id, capability_id, evidence_kind, polarity,
                   maturity_dimension, confidence, extraction_method, model,
                   provider, lifecycle,
                   CASE WHEN json_valid(source_ref)
                        THEN COALESCE(json_extract(source_ref, '$.artifact_source_ref'), source_ref)
                        ELSE source_ref END,
                   (CASE WHEN json_valid(source_ref)
                         THEN COALESCE(json_extract(source_ref, '$.basis'), source_ref)
                         ELSE 'legacy:' || source_ref END)
                   || ':legacy:' || evidence_kind || ':' || maturity_dimension,
                   created_at, updated_at
            FROM ckm_evidence_edge_v1
            """
        )
        conn.execute("DROP TABLE ckm_evidence_edge_v1")

    def rebuild(self) -> dict[str, Any]:
        """Drop and recreate ``ckm_*`` tables only (INV-CKM-4). Emits a receipt."""

        self._receipt_store.initialize()
        with self._connect() as conn:
            conn.execute("PRAGMA foreign_keys = OFF")
            for table in reversed(CKM_TABLE_NAMES):
                conn.execute(f"DROP TABLE IF EXISTS {table}")
            conn.execute("PRAGMA foreign_keys = ON")
            for statement in CKM_DDL_STATEMENTS:
                conn.execute(statement)
            conn.commit()
        return self._emit_schema_receipt(event_type="ckm_schema_rebuilt", action="rebuild")

    def table_names(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'ckm_%'"
            ).fetchall()
        return sorted(row["name"] for row in rows)

    def _emit_schema_receipt(self, *, event_type: str, action: str) -> dict[str, Any]:
        now = utc_now()
        return self._receipt_store.append_receipt(
            source_refs=[
                {"ref_type": "ckm_schema", "ref": "app/builderops/ckm/schema.py"},
            ],
            summary=f"CKM {action} ran against {len(CKM_TABLE_NAMES)} ckm_* tables",
            event_type=event_type,
            actor={"actor_type": "agent", "id": "ckm_store"},
            occurred_at=now,
            target_refs=[
                {"ref_type": "ckm_tables", "ref": table} for table in CKM_TABLE_NAMES
            ],
            action=action,
            receipt_body=_dumps({"tables": list(CKM_TABLE_NAMES)}),
            idempotency_key=f"ckm-{action}-{uuid4().hex}",
        )

    # --- Capability ------------------------------------------------------------

    def upsert_capability(
        self,
        *,
        name: str,
        definition: str,
        existence_provenance: str,
        parent_id: str | None = None,
        lifecycle: str = "candidate",
        boundary_ref: str | None = None,
    ) -> CkmCapability:
        now = utc_now()
        candidate_id = new_id("cap")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO ckm_capability (
                    id, name, definition, parent_id, lifecycle,
                    existence_provenance, boundary_ref, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(name) DO UPDATE SET
                    definition = excluded.definition,
                    parent_id = excluded.parent_id,
                    lifecycle = excluded.lifecycle,
                    existence_provenance = excluded.existence_provenance,
                    boundary_ref = excluded.boundary_ref,
                    updated_at = excluded.updated_at
                """,
                (
                    candidate_id,
                    name,
                    definition,
                    parent_id,
                    lifecycle,
                    existence_provenance,
                    boundary_ref,
                    now,
                    now,
                ),
            )
            conn.commit()
        capability = self.get_capability_by_name(name)
        if capability is None:  # pragma: no cover - defensive, upsert always leaves a row
            raise CkmValidationError(f"capability upsert did not persist: {name}")
        return capability

    def get_capability_by_name(self, name: str) -> CkmCapability | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ckm_capability WHERE name = ?", (name,)
            ).fetchone()
        return CkmCapability.from_row(row) if row is not None else None

    def get_capability(self, capability_id: str) -> CkmCapability | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ckm_capability WHERE id = ?", (capability_id,)
            ).fetchone()
        return CkmCapability.from_row(row) if row is not None else None

    def list_capabilities(self) -> list[CkmCapability]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM ckm_capability ORDER BY name").fetchall()
        return [CkmCapability.from_row(row) for row in rows]

    # --- Artifact --------------------------------------------------------------

    def upsert_artifact(
        self,
        *,
        source_ref: str,
        artifact_kind: str,
        source: str,
        watermark: str,
        provenance: str,
    ) -> CkmArtifact:
        now = utc_now()
        candidate_id = new_id("art")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO ckm_artifact (
                    id, source_ref, artifact_kind, source, watermark, provenance,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(source_ref) DO UPDATE SET
                    artifact_kind = excluded.artifact_kind,
                    source = excluded.source,
                    watermark = excluded.watermark,
                    provenance = excluded.provenance,
                    updated_at = excluded.updated_at
                """,
                (candidate_id, source_ref, artifact_kind, source, watermark, provenance, now, now),
            )
            conn.commit()
        artifact = self.get_artifact_by_source_ref(source_ref)
        if artifact is None:  # pragma: no cover - defensive
            raise CkmValidationError(f"artifact upsert did not persist: {source_ref}")
        return artifact

    def get_artifact_by_source_ref(self, source_ref: str) -> CkmArtifact | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ckm_artifact WHERE source_ref = ?", (source_ref,)
            ).fetchone()
        return CkmArtifact.from_row(row) if row is not None else None

    def list_artifacts(self) -> list[CkmArtifact]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM ckm_artifact ORDER BY source_ref").fetchall()
        return [CkmArtifact.from_row(row) for row in rows]

    def delete_artifacts_not_in(self, source: str, source_refs: set[str]) -> int:
        """Remove stale projections for one fully enumerated repository source."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, source_ref FROM ckm_artifact WHERE source = ?", (source,)
            ).fetchall()
            stale = [row for row in rows if row["source_ref"] not in source_refs]
            for row in stale:
                conn.execute("DELETE FROM ckm_evidence_edge WHERE artifact_id = ?", (row["id"],))
                conn.execute("DELETE FROM ckm_artifact WHERE id = ?", (row["id"],))
            conn.commit()
        return len(stale)

    # --- Source watermarks ---------------------------------------------------

    def get_watermark(self, source: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM ckm_watermark WHERE source = ?", (source,)
            ).fetchone()
        return str(row["value"]) if row is not None else None

    def set_watermark(self, source: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ckm_watermark (source, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (source, value, utc_now()),
            )
            conn.commit()

    # --- Evidence edge ---------------------------------------------------------

    def upsert_evidence_edge(
        self,
        *,
        artifact_id: str,
        capability_id: str,
        evidence_kind: str,
        polarity: str,
        maturity_dimension: str,
        confidence: float,
        extraction_method: str,
        lifecycle: str,
        source_ref: str,
        basis: str | None = None,
        model: str | None = None,
        provider: str | None = None,
    ) -> CkmEvidenceEdge:
        now = utc_now()
        candidate_id = new_id("edge")
        resolved_basis = basis or source_ref
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO ckm_evidence_edge (
                    id, artifact_id, capability_id, evidence_kind, polarity,
                    maturity_dimension, confidence, extraction_method, model,
                    provider, lifecycle, source_ref, basis, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(artifact_id, capability_id, basis)
                DO UPDATE SET
                    evidence_kind = excluded.evidence_kind,
                    polarity = excluded.polarity,
                    maturity_dimension = excluded.maturity_dimension,
                    confidence = excluded.confidence,
                    extraction_method = excluded.extraction_method,
                    model = excluded.model,
                    provider = excluded.provider,
                    lifecycle = excluded.lifecycle,
                    source_ref = excluded.source_ref,
                    updated_at = excluded.updated_at
                """,
                (
                    candidate_id,
                    artifact_id,
                    capability_id,
                    evidence_kind,
                    polarity,
                    maturity_dimension,
                    confidence,
                    extraction_method,
                    model,
                    provider,
                    lifecycle,
                    source_ref,
                    resolved_basis,
                    now,
                    now,
                ),
            )
            conn.commit()
        edge = self.get_evidence_edge(
            artifact_id=artifact_id,
            capability_id=capability_id,
            evidence_kind=evidence_kind,
            maturity_dimension=maturity_dimension,
            basis=resolved_basis,
        )
        if edge is None:  # pragma: no cover - defensive
            raise CkmValidationError("evidence edge upsert did not persist")
        return edge

    def get_evidence_edge(
        self,
        *,
        artifact_id: str,
        capability_id: str,
        evidence_kind: str,
        maturity_dimension: str,
        basis: str | None = None,
    ) -> CkmEvidenceEdge | None:
        with self._connect() as conn:
            if basis is None:
                row = conn.execute(
                    """
                    SELECT * FROM ckm_evidence_edge
                    WHERE artifact_id = ? AND capability_id = ?
                      AND evidence_kind = ? AND maturity_dimension = ?
                    ORDER BY basis LIMIT 1
                    """,
                    (artifact_id, capability_id, evidence_kind, maturity_dimension),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT * FROM ckm_evidence_edge
                    WHERE artifact_id = ? AND capability_id = ? AND basis = ?
                    """,
                    (artifact_id, capability_id, basis),
                ).fetchone()
        return CkmEvidenceEdge.from_row(row) if row is not None else None

    def list_evidence_edges_for_capability(self, capability_id: str) -> list[CkmEvidenceEdge]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ckm_evidence_edge WHERE capability_id = ? ORDER BY created_at",
                (capability_id,),
            ).fetchall()
        return [CkmEvidenceEdge.from_row(row) for row in rows]

    def list_evidence_edges(self) -> list[CkmEvidenceEdge]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ckm_evidence_edge ORDER BY artifact_id, capability_id"
            ).fetchall()
        return [CkmEvidenceEdge.from_row(row) for row in rows]

    def delete_deterministic_edges_not_in(
        self,
        edge_keys: set[tuple[str, str, str]],
        *,
        owned_basis_prefixes: tuple[str, ...],
    ) -> int:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, artifact_id, capability_id, basis
                FROM ckm_evidence_edge
                WHERE extraction_method = 'deterministic'
                """
            ).fetchall()
            stale = [
                row["id"]
                for row in rows
                if str(row["basis"]).startswith(owned_basis_prefixes)
                if (row["artifact_id"], row["capability_id"], row["basis"])
                not in edge_keys
            ]
            for edge_id in stale:
                conn.execute("DELETE FROM ckm_evidence_edge WHERE id = ?", (edge_id,))
            conn.commit()
        return len(stale)

    # --- Assessment (append-only, bitemporal) -----------------------------------

    def append_assessment(
        self,
        *,
        capability_id: str,
        scores: Mapping[str, float],
        citations: Mapping[str, list[JsonDict]],
        aggregate: float,
        watermark_set: Mapping[str, str],
        valid_from: str | None = None,
        asserted_at: str | None = None,
    ) -> CkmAssessment:
        missing = set(MATURITY_DIMENSIONS) - set(scores)
        if missing:
            raise CkmValidationError(f"assessment missing dimension score(s): {sorted(missing)}")
        missing_citations = [d for d in MATURITY_DIMENSIONS if not citations.get(d)]
        if missing_citations:
            raise CkmValidationError(
                f"assessment dimension(s) missing citations: {sorted(missing_citations)}"
            )
        if not watermark_set:
            raise CkmValidationError("watermark_set must not be empty")

        now = utc_now()
        resolved_valid_from = valid_from or now
        resolved_asserted_at = asserted_at or now
        assessment_id = new_id("assess")

        columns = ["id", "capability_id"]
        values: list[Any] = [assessment_id, capability_id]
        for dimension in MATURITY_DIMENSIONS:
            columns.append(dimension)
            values.append(scores[dimension])
            columns.append(f"{dimension}_citations")
            values.append(_dumps(citations[dimension]))
        columns += ["aggregate", "watermark_set", "valid_from", "asserted_at"]
        values += [aggregate, _dumps(watermark_set), resolved_valid_from, resolved_asserted_at]

        placeholders = ",".join("?" for _ in values)
        column_list = ",".join(columns)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                f"INSERT INTO ckm_assessment ({column_list}) VALUES ({placeholders})",
                values,
            )
            conn.commit()

        assessment = self.get_assessment(assessment_id)
        if assessment is None:  # pragma: no cover - defensive
            raise CkmValidationError("assessment append did not persist")
        return assessment

    def get_assessment(self, assessment_id: str) -> CkmAssessment | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ckm_assessment WHERE id = ?", (assessment_id,)
            ).fetchone()
        if row is None:
            return None
        return self._assessment_from_row(row)

    def list_assessments_for_capability(self, capability_id: str) -> list[CkmAssessment]:
        """All assessments for a capability, ordered oldest -> newest by asserted_at."""

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ckm_assessment
                WHERE capability_id = ?
                ORDER BY asserted_at ASC, rowid ASC
                """,
                (capability_id,),
            ).fetchall()
        return [self._assessment_from_row(row) for row in rows]

    def latest_assessment_for_capability(self, capability_id: str) -> CkmAssessment | None:
        assessments = self.list_assessments_for_capability(capability_id)
        return assessments[-1] if assessments else None

    @staticmethod
    def _assessment_from_row(row: sqlite3.Row) -> CkmAssessment:
        scores = {dimension: row[dimension] for dimension in MATURITY_DIMENSIONS}
        citations = {
            dimension: _loads(row[f"{dimension}_citations"]) for dimension in MATURITY_DIMENSIONS
        }
        watermark_set = _loads(row["watermark_set"])
        return CkmAssessment.from_row(
            dict(row), scores=scores, citations=citations, watermark_set=watermark_set
        )

    # --- Finding -----------------------------------------------------------------

    def upsert_finding(
        self,
        *,
        kind: str,
        capability_id: str,
        dimension: str,
        statement: str,
        citations: list[JsonDict],
    ) -> CkmFinding:
        if not citations:
            raise CkmValidationError("citations must not be empty")
        now = utc_now()
        candidate_id = new_id("find")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                INSERT INTO ckm_finding (
                    id, kind, capability_id, dimension, statement, citations,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(kind, capability_id, dimension) DO UPDATE SET
                    statement = excluded.statement,
                    citations = excluded.citations,
                    updated_at = excluded.updated_at
                """,
                (candidate_id, kind, capability_id, dimension, statement, _dumps(citations), now, now),
            )
            conn.commit()
        finding = self.get_finding(kind=kind, capability_id=capability_id, dimension=dimension)
        if finding is None:  # pragma: no cover - defensive
            raise CkmValidationError("finding upsert did not persist")
        return finding

    def get_finding(self, *, kind: str, capability_id: str, dimension: str) -> CkmFinding | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM ckm_finding
                WHERE kind = ? AND capability_id = ? AND dimension = ?
                """,
                (kind, capability_id, dimension),
            ).fetchone()
        if row is None:
            return None
        return CkmFinding.from_row(row, citations=_loads(row["citations"]))

    def list_findings_for_capability(self, capability_id: str) -> list[CkmFinding]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM ckm_finding WHERE capability_id = ? ORDER BY created_at",
                (capability_id,),
            ).fetchall()
        return [CkmFinding.from_row(row, citations=_loads(row["citations"])) for row in rows]
