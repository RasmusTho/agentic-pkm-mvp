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
import secrets
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4

from app.builderops.config import BuilderOpsPaths, load_paths, validate_db_path_outside_vault
from app.builderops.store import SqliteBuilderOpsStore

from app.builderops.ckm.contracts import CkmStateIdentity, canonical_digest, stable_public_id
from app.builderops.ckm.models import (
    MATURITY_DIMENSIONS,
    CkmArtifact,
    CkmAssessment,
    CkmAssessmentProjection,
    CkmCapability,
    CkmEvidenceEdge,
    CkmFinding,
    CkmValidationError,
    new_id,
    utc_now,
)
from app.builderops.ckm.schema import CKM_DDL_STATEMENTS, CKM_SCHEMA_VERSION, CKM_TABLE_NAMES

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
            conn.execute("BEGIN IMMEDIATE")
            existing_tables = {
                str(row["name"])
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'ckm_%'"
                ).fetchall()
            }
            current_tables = set(CKM_TABLE_NAMES)
            legacy_tables = current_tables - {"ckm_state"}
            if existing_tables and existing_tables != current_tables and existing_tables != legacy_tables:
                raise CkmValidationError(
                    "unsupported partial CKM schema; refusing to half-initialize identity/state metadata"
                )
            self._add_public_identity_columns(conn)
            self._migrate_evidence_edge_basis(conn)
            self._migrate_assessment_explainability(conn)
            for statement in CKM_DDL_STATEMENTS:
                if "CREATE UNIQUE INDEX" in statement and (
                    "public_id" in statement or "identity_key" in statement
                ):
                    continue
                conn.execute(statement)
            self._initialize_or_validate_state(conn, legacy=bool(existing_tables))
            self._backfill_public_identities(conn)
            for statement in CKM_DDL_STATEMENTS:
                if "CREATE UNIQUE INDEX" in statement and (
                    "public_id" in statement or "identity_key" in statement
                ):
                    conn.execute(statement)
            self._preflight_schema(conn)
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
    def _add_public_identity_columns(conn: sqlite3.Connection) -> None:
        additions = {
            "ckm_capability": (("public_id", "TEXT NOT NULL DEFAULT ''"), ("identity_key", "TEXT NOT NULL DEFAULT ''")),
            "ckm_artifact": (("public_id", "TEXT NOT NULL DEFAULT ''"),),
            "ckm_evidence_edge": (("public_id", "TEXT NOT NULL DEFAULT ''"),),
            "ckm_evidence_edge_history": (("public_id", "TEXT NOT NULL DEFAULT ''"),),
            "ckm_assessment": (("public_id", "TEXT NOT NULL DEFAULT ''"),),
            "ckm_finding": (("public_id", "TEXT NOT NULL DEFAULT ''"),),
        }
        for table, columns_to_add in additions.items():
            columns = {
                row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
            }
            if not columns:
                continue
            for name, declaration in columns_to_add:
                if name not in columns:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")

    @staticmethod
    def _initialize_or_validate_state(conn: sqlite3.Connection, *, legacy: bool) -> None:
        rows = conn.execute("SELECT * FROM ckm_state").fetchall()
        if len(rows) > 1:
            raise CkmValidationError("CKM state preflight failed: expected exactly one state row")
        if rows:
            version = int(rows[0]["schema_version"])
            if version != CKM_SCHEMA_VERSION:
                raise CkmValidationError(
                    f"unsupported CKM state schema version {version}; expected {CKM_SCHEMA_VERSION}"
                )
            return
        now = utc_now()
        conn.execute(
            """
            INSERT INTO ckm_state
                (singleton, epoch, state_revision, schema_version, created_at, updated_at)
            VALUES (1, ?, ?, ?, ?, ?)
            """,
            (f"epoch_{uuid4().hex}", 1 if legacy else 0, CKM_SCHEMA_VERSION, now, now),
        )

    @staticmethod
    def _backfill_public_identities(conn: sqlite3.Connection) -> None:
        seed_identity_by_name: dict[str, str] = {}
        try:
            from app.builderops.ckm.seed import load_manifest

            seed_identity_by_name = {
                entry.name: f"seed:{entry.stable_key}" for entry in load_manifest()
            }
        except (OSError, ValueError):
            # A custom/partial deployment may not carry the repository manifest.
            # Existing rows still receive deterministic legacy identities below.
            seed_identity_by_name = {}

        for row in conn.execute("SELECT * FROM ckm_capability ORDER BY id").fetchall():
            identity_key = str(row["identity_key"] or "")
            if not identity_key:
                identity_key = seed_identity_by_name.get(str(row["name"])) or (
                    f"legacy:{row['existence_provenance']}:{row['id']}"
                )
            public_id = str(row["public_id"] or "") or stable_public_id(
                "capability", identity_key
            )
            conn.execute(
                "UPDATE ckm_capability SET identity_key = ?, public_id = ? WHERE id = ?",
                (identity_key, public_id, row["id"]),
            )

        for row in conn.execute("SELECT * FROM ckm_artifact ORDER BY id").fetchall():
            public_id = str(row["public_id"] or "") or stable_public_id(
                "artifact", str(row["source_ref"])
            )
            conn.execute("UPDATE ckm_artifact SET public_id = ? WHERE id = ?", (public_id, row["id"]))

        for row in conn.execute("SELECT * FROM ckm_evidence_edge ORDER BY id").fetchall():
            public_id = str(row["public_id"] or "") or CkmStore._edge_public_id(
                conn, row["artifact_id"], row["capability_id"], row["basis"]
            )
            conn.execute(
                "UPDATE ckm_evidence_edge SET public_id = ? WHERE id = ?", (public_id, row["id"])
            )
        for row in conn.execute("SELECT * FROM ckm_evidence_edge_history ORDER BY history_id").fetchall():
            public_id = str(row["public_id"] or "")
            if not public_id:
                active = conn.execute(
                    "SELECT public_id FROM ckm_evidence_edge WHERE id = ?", (row["edge_id"],)
                ).fetchone()
                public_id = str(active["public_id"]) if active else CkmStore._edge_public_id(
                    conn, row["artifact_id"], row["capability_id"], row["basis"]
                )
            conn.execute(
                "UPDATE ckm_evidence_edge_history SET public_id = ? WHERE history_id = ?",
                (public_id, row["history_id"]),
            )
        for row in conn.execute("SELECT * FROM ckm_assessment ORDER BY id").fetchall():
            public_id = str(row["public_id"] or "") or CkmStore._assessment_public_id(conn, row)
            conn.execute(
                "UPDATE ckm_assessment SET public_id = ? WHERE id = ?", (public_id, row["id"])
            )
        for row in conn.execute("SELECT * FROM ckm_finding ORDER BY id").fetchall():
            public_id = str(row["public_id"] or "") or CkmStore._finding_public_id(
                conn, row["kind"], row["capability_id"], row["dimension"]
            )
            conn.execute("UPDATE ckm_finding SET public_id = ? WHERE id = ?", (public_id, row["id"]))

    @staticmethod
    def _preflight_schema(conn: sqlite3.Connection) -> None:
        state_rows = conn.execute("SELECT * FROM ckm_state").fetchall()
        if len(state_rows) != 1 or int(state_rows[0]["schema_version"]) != CKM_SCHEMA_VERSION:
            raise CkmValidationError("CKM state preflight failed: missing or unsupported state row")
        checks = {
            "ckm_capability": ("public_id", "identity_key"),
            "ckm_artifact": ("public_id",),
            "ckm_evidence_edge": ("public_id",),
            "ckm_evidence_edge_history": ("public_id",),
            "ckm_assessment": ("public_id",),
            "ckm_finding": ("public_id",),
        }
        for table, columns in checks.items():
            for column in columns:
                blank = conn.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE {column} = '' OR {column} IS NULL"
                ).fetchone()["count"]
                if blank:
                    raise CkmValidationError(
                        f"CKM identity preflight failed: {table}.{column} has {blank} blank row(s)"
                    )
                duplicate = conn.execute(
                    f"SELECT {column} FROM {table} GROUP BY {column} HAVING COUNT(*) > 1 LIMIT 1"
                ).fetchone()
                if duplicate and table != "ckm_evidence_edge_history":
                    raise CkmValidationError(
                        f"CKM identity preflight failed: duplicate {table}.{column}"
                    )

    @staticmethod
    def _advance_state_revision(conn: sqlite3.Connection) -> None:
        updated = conn.execute(
            """
            UPDATE ckm_state
            SET state_revision = state_revision + 1, updated_at = ?
            WHERE singleton = 1 AND schema_version = ?
            """,
            (utc_now(), CKM_SCHEMA_VERSION),
        )
        if updated.rowcount != 1:
            raise CkmValidationError("CKM mutation refused: state metadata is missing or unsupported")

    def state_identity(self) -> CkmStateIdentity:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM ckm_state").fetchall()
        if len(rows) != 1:
            raise CkmValidationError("CKM state preflight failed: expected exactly one state row")
        row = rows[0]
        if int(row["schema_version"]) != CKM_SCHEMA_VERSION:
            raise CkmValidationError("CKM state preflight failed: unsupported schema version")
        return CkmStateIdentity(
            epoch=str(row["epoch"]),
            state_revision=int(row["state_revision"]),
            schema_version=int(row["schema_version"]),
        )

    @staticmethod
    def _referenced_public_id(
        conn: sqlite3.Connection, table: str, internal_id: str
    ) -> str:
        row = conn.execute(
            f"SELECT public_id FROM {table} WHERE id = ?", (internal_id,)
        ).fetchone()
        if row is None or not row["public_id"]:
            raise CkmValidationError(
                f"CKM identity preflight failed: {table} row {internal_id!r} has no public identity"
            )
        return str(row["public_id"])

    @staticmethod
    def _edge_public_id(
        conn: sqlite3.Connection, artifact_id: str, capability_id: str, basis: str
    ) -> str:
        identity = canonical_digest(
            {
                "artifact": CkmStore._referenced_public_id(conn, "ckm_artifact", artifact_id),
                "capability": CkmStore._referenced_public_id(
                    conn, "ckm_capability", capability_id
                ),
                "basis": basis,
            }
        )
        return stable_public_id("evidence_edge", identity)

    @staticmethod
    def _assessment_public_id(conn: sqlite3.Connection, row: Mapping[str, Any]) -> str:
        identity = {
            "capability": CkmStore._referenced_public_id(
                conn, "ckm_capability", str(row["capability_id"])
            ),
            "scores": {dimension: row[dimension] for dimension in MATURITY_DIMENSIONS},
            "candidate_shares": row["candidate_shares"],
            "formula_ids": row["formula_ids"],
            "aggregate": row["aggregate"],
            "aggregate_formula_id": row["aggregate_formula_id"],
            "low_confidence": row["low_confidence"],
            "edge_fingerprint": row["edge_fingerprint"],
            "watermark_set": row["watermark_set"],
            "valid_from": row["valid_from"],
            "asserted_at": row["asserted_at"],
        }
        return stable_public_id("assessment", canonical_digest(identity))

    @staticmethod
    def _finding_public_id(
        conn: sqlite3.Connection, kind: str, capability_id: str, dimension: str
    ) -> str:
        identity = canonical_digest(
            {
                "kind": kind,
                "capability": CkmStore._referenced_public_id(
                    conn, "ckm_capability", capability_id
                ),
                "dimension": dimension,
            }
        )
        return stable_public_id("finding", identity)

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
                id, public_id, artifact_id, capability_id, evidence_kind, polarity,
                maturity_dimension, confidence, extraction_method, model,
                provider, lifecycle, source_ref, basis, created_at, updated_at
            )
            SELECT id, public_id, artifact_id, capability_id, evidence_kind, polarity,
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

    @staticmethod
    def _migrate_assessment_explainability(conn: sqlite3.Connection) -> None:
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(ckm_assessment)").fetchall()
        }
        if not columns:
            return
        additions = (
            ("candidate_shares", "TEXT NOT NULL DEFAULT '{}'"),
            ("formula_ids", "TEXT NOT NULL DEFAULT '{}'"),
            (
                "aggregate_formula_id",
                "TEXT NOT NULL DEFAULT 'legacy-pre-ckm07'",
            ),
            ("low_confidence", "INTEGER NOT NULL DEFAULT 0 CHECK (low_confidence IN (0, 1))"),
            ("edge_fingerprint", "TEXT NOT NULL DEFAULT 'legacy'"),
        )
        for name, declaration in additions:
            if name not in columns:
                conn.execute(f"ALTER TABLE ckm_assessment ADD COLUMN {name} {declaration}")
        zero_shares = _dumps({dimension: 0.0 for dimension in MATURITY_DIMENSIONS})
        legacy_formulas = _dumps({dimension: "legacy-pre-ckm07" for dimension in MATURITY_DIMENSIONS})
        conn.execute(
            """
            UPDATE ckm_assessment
            SET candidate_shares = CASE WHEN candidate_shares = '{}' THEN ? ELSE candidate_shares END,
                formula_ids = CASE WHEN formula_ids = '{}' THEN ? ELSE formula_ids END
            """,
            (zero_shares, legacy_formulas),
        )

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
            now = utc_now()
            conn.execute(
                """
                INSERT INTO ckm_state
                    (singleton, epoch, state_revision, schema_version, created_at, updated_at)
                VALUES (1, ?, 1, ?, ?, ?)
                """,
                (f"epoch_{uuid4().hex}", CKM_SCHEMA_VERSION, now, now),
            )
            self._preflight_schema(conn)
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
        identity_key: str | None = None,
    ) -> CkmCapability:
        now = utc_now()
        candidate_id = new_id("cap")
        resolved_identity_key = identity_key or (
            f"inferred:{existence_provenance}:{boundary_ref or name}"
        )
        public_id = stable_public_id("capability", resolved_identity_key)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM ckm_capability WHERE identity_key = ?",
                (resolved_identity_key,),
            ).fetchone()
            desired = (name, definition, parent_id, lifecycle, existence_provenance, boundary_ref)
            if existing is not None:
                actual = tuple(
                    existing[field]
                    for field in (
                        "name",
                        "definition",
                        "parent_id",
                        "lifecycle",
                        "existence_provenance",
                        "boundary_ref",
                    )
                )
                if actual == desired:
                    conn.commit()
                    return CkmCapability.from_row(existing)
                conn.execute(
                    """
                    UPDATE ckm_capability
                    SET name = ?, definition = ?, parent_id = ?, lifecycle = ?,
                        existence_provenance = ?, boundary_ref = ?, updated_at = ?
                    WHERE identity_key = ?
                    """,
                    (*desired, now, resolved_identity_key),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO ckm_capability (
                        id, public_id, identity_key, name, definition, parent_id, lifecycle,
                        existence_provenance, boundary_ref, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        candidate_id,
                        public_id,
                        resolved_identity_key,
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
            self._advance_state_revision(conn)
            conn.commit()
        capability = self.get_capability_by_identity_key(resolved_identity_key)
        if capability is None:  # pragma: no cover - defensive, upsert always leaves a row
            raise CkmValidationError(f"capability upsert did not persist: {name}")
        return capability

    def get_capability_by_identity_key(self, identity_key: str) -> CkmCapability | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ckm_capability WHERE identity_key = ?", (identity_key,)
            ).fetchone()
        return CkmCapability.from_row(row) if row is not None else None

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
        public_id = stable_public_id("artifact", source_ref)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT * FROM ckm_artifact WHERE source_ref = ?", (source_ref,)
            ).fetchone()
            desired = (artifact_kind, source, watermark, provenance)
            if existing is not None:
                actual = tuple(
                    existing[field]
                    for field in ("artifact_kind", "source", "watermark", "provenance")
                )
                if actual == desired:
                    conn.commit()
                    return CkmArtifact.from_row(existing)
                conn.execute(
                    """
                    UPDATE ckm_artifact
                    SET artifact_kind = ?, source = ?, watermark = ?, provenance = ?, updated_at = ?
                    WHERE source_ref = ?
                    """,
                    (*desired, now, source_ref),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO ckm_artifact (
                        id, public_id, source_ref, artifact_kind, source, watermark, provenance,
                        created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        candidate_id,
                        public_id,
                        source_ref,
                        artifact_kind,
                        source,
                        watermark,
                        provenance,
                        now,
                        now,
                    ),
                )
            self._advance_state_revision(conn)
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
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT id, source_ref FROM ckm_artifact WHERE source = ?", (source,)
            ).fetchall()
            stale = [row for row in rows if row["source_ref"] not in source_refs]
            for row in stale:
                edge_rows = conn.execute(
                    "SELECT * FROM ckm_evidence_edge WHERE artifact_id = ?", (row["id"],)
                ).fetchall()
                self._archive_evidence_edges(conn, edge_rows)
                conn.execute("DELETE FROM ckm_evidence_edge WHERE artifact_id = ?", (row["id"],))
                conn.execute("DELETE FROM ckm_artifact WHERE id = ?", (row["id"],))
            if stale:
                self._advance_state_revision(conn)
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
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT value FROM ckm_watermark WHERE source = ?", (source,)
            ).fetchone()
            if existing is not None and existing["value"] == value:
                conn.commit()
                return
            conn.execute(
                """
                INSERT INTO ckm_watermark (source, value, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (source, value, utc_now()),
            )
            self._advance_state_revision(conn)
            conn.commit()

    def current_watermark_set(self) -> dict[str, str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT source, value FROM ckm_watermark ORDER BY source").fetchall()
        return {str(row["source"]): str(row["value"]) for row in rows}

    # --- Evidence edge ---------------------------------------------------------

    @staticmethod
    def _archive_evidence_edges(
        conn: sqlite3.Connection, rows: list[sqlite3.Row]
    ) -> None:
        """Preserve superseded edge versions outside the active CEG projection."""

        retired_at = utc_now()
        for row in rows:
            conn.execute(
                """
                INSERT INTO ckm_evidence_edge_history (
                    history_id, edge_id, public_id, artifact_id, capability_id,
                    evidence_kind, polarity, maturity_dimension, confidence,
                    extraction_method, model, provider, lifecycle, source_ref,
                    basis, created_at, updated_at, retired_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    new_id("edge_history"),
                    row["id"],
                    row["public_id"],
                    row["artifact_id"],
                    row["capability_id"],
                    row["evidence_kind"],
                    row["polarity"],
                    row["maturity_dimension"],
                    row["confidence"],
                    row["extraction_method"],
                    row["model"],
                    row["provider"],
                    row["lifecycle"],
                    row["source_ref"],
                    row["basis"],
                    row["created_at"],
                    row["updated_at"],
                    retired_at,
                ),
            )

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
        if extraction_method == "inferred" and (
            basis is None or not isinstance(basis, str) or not basis.strip()
        ):
            raise CkmValidationError(
                "inferred evidence edges require an explicit non-empty rationale as basis"
            )
        resolved_basis = basis or source_ref
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            public_id = self._edge_public_id(conn, artifact_id, capability_id, resolved_basis)
            candidate = CkmEvidenceEdge(
                id=candidate_id,
                public_id=public_id,
                artifact_id=artifact_id,
                capability_id=capability_id,
                evidence_kind=evidence_kind,
                polarity=polarity,
                maturity_dimension=maturity_dimension,
                confidence=confidence,
                extraction_method=extraction_method,
                model=model,
                provider=provider,
                lifecycle=lifecycle,
                source_ref=source_ref,
                basis=resolved_basis,
                created_at=now,
                updated_at=now,
            ).validate()
            if candidate.extraction_method == "inferred" and candidate.lifecycle != "candidate":
                raise CkmValidationError(
                    "inferred evidence edges must enter as candidate; use a confirmation receipt"
                )
            existing_row = conn.execute(
                """
                SELECT * FROM ckm_evidence_edge
                WHERE artifact_id = ? AND capability_id = ? AND basis = ?
                """,
                (artifact_id, capability_id, resolved_basis),
            ).fetchone()
            if existing_row is not None:
                material_fields = (
                    "artifact_id",
                    "capability_id",
                    "evidence_kind",
                    "polarity",
                    "maturity_dimension",
                    "confidence",
                    "extraction_method",
                    "model",
                    "provider",
                    "source_ref",
                    "basis",
                )
                desired = {
                    "artifact_id": artifact_id,
                    "capability_id": capability_id,
                    "evidence_kind": evidence_kind,
                    "polarity": polarity,
                    "maturity_dimension": maturity_dimension,
                    "confidence": confidence,
                    "extraction_method": extraction_method,
                    "model": model,
                    "provider": provider,
                    "source_ref": source_ref,
                    "basis": resolved_basis,
                }
                material_unchanged = all(
                    existing_row[field] == desired[field] for field in material_fields
                )
                confirmation_preserved = (
                    material_unchanged
                    and existing_row["extraction_method"] == "inferred"
                    and existing_row["lifecycle"] == "confirmed"
                    and extraction_method == "inferred"
                    and lifecycle == "candidate"
                )
                unchanged = material_unchanged and (
                    existing_row["lifecycle"] == lifecycle or confirmation_preserved
                )
                if unchanged:
                    conn.commit()
                    return CkmEvidenceEdge.from_row(existing_row)
                self._archive_evidence_edges(conn, [existing_row])
            conn.execute(
                """
                INSERT INTO ckm_evidence_edge (
                    id, public_id, artifact_id, capability_id, evidence_kind, polarity,
                    maturity_dimension, confidence, extraction_method, model,
                    provider, lifecycle, source_ref, basis, created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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
                    public_id,
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
            self._advance_state_revision(conn)
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

    def get_active_evidence_edge_by_id(self, edge_id: str) -> CkmEvidenceEdge | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM ckm_evidence_edge WHERE id = ?", (edge_id,)
            ).fetchone()
        return CkmEvidenceEdge.from_row(row) if row is not None else None

    def get_evidence_edge_by_id(self, edge_id: str) -> CkmEvidenceEdge | None:
        """Resolve an edge citation from the active graph or retired history."""

        active = self.get_active_evidence_edge_by_id(edge_id)
        if active is not None:
            return active
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT edge_id AS id, public_id, artifact_id, capability_id,
                       evidence_kind, polarity, maturity_dimension,
                       confidence, extraction_method, model, provider,
                       lifecycle, source_ref, basis, created_at, updated_at
                FROM ckm_evidence_edge_history
                WHERE edge_id = ?
                ORDER BY retired_at DESC LIMIT 1
                """,
                (edge_id,),
            ).fetchone()
        return CkmEvidenceEdge.from_row(row) if row is not None else None

    def has_retired_evidence_edge(self, edge_id: str) -> bool:
        """Return whether the current graph explicitly retired this edge id."""

        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM ckm_evidence_edge_history WHERE edge_id = ? LIMIT 1",
                (edge_id,),
            ).fetchone()
        return row is not None

    def _set_inferred_edge_confirmed(self, edge_id: str) -> CkmEvidenceEdge:
        """Apply a confirmation already authorized by semantic receipt validation.

        This is intentionally private: callers must use the receipt-producing and
        receipt-validating confirmation boundary in ``semantic.py``.
        """

        edge = self.get_active_evidence_edge_by_id(edge_id)
        if edge is None:
            raise CkmValidationError(f"evidence edge not found: {edge_id}")
        if edge.extraction_method != "inferred":
            raise CkmValidationError("only inferred evidence edges require confirmation")
        if edge.lifecycle == "confirmed":
            return edge
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ckm_evidence_edge WHERE id = ?", (edge_id,)
            ).fetchone()
            if row is not None:
                self._archive_evidence_edges(conn, [row])
            conn.execute(
                "UPDATE ckm_evidence_edge SET lifecycle = 'confirmed', updated_at = ? WHERE id = ?",
                (utc_now(), edge_id),
            )
            self._advance_state_revision(conn)
            conn.commit()
        confirmed = self.get_active_evidence_edge_by_id(edge_id)
        if confirmed is None:  # pragma: no cover - defensive
            raise CkmValidationError(f"confirmed edge disappeared: {edge_id}")
        return confirmed

    def list_builderops_receipts(self, event_type: str | None = None) -> list[JsonDict]:
        receipts = self._receipt_store.list_records("BuilderOpsReceipt")
        if event_type is None:
            return receipts
        return [receipt for receipt in receipts if receipt.get("event_type") == event_type]

    def append_builderops_receipt(self, **fields: Any) -> JsonDict:
        return self._receipt_store.append_receipt(**fields)

    def _confirmation_signing_key(self, *, create: bool = False) -> bytes | None:
        """Return the local CKM confirmation key, creating it only at the CLI boundary.

        The key lives in BuilderOps metadata, outside the rebuildable ``ckm_*``
        projection.  Receipt replay may read it but never creates it: an
        unsigned, self-asserted receipt therefore cannot bootstrap its own
        authority after a rebuild.
        """

        key_name = "ckm_confirmation_signing_key_v1"
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT value FROM builderops_meta WHERE key = ?", (key_name,)
            ).fetchone()
            if row is None and create:
                value = secrets.token_hex(32)
                conn.execute(
                    "INSERT INTO builderops_meta (key, value) VALUES (?, ?)",
                    (key_name, value),
                )
                conn.commit()
                return bytes.fromhex(value)
            conn.commit()
        if row is None:
            return None
        try:
            return bytes.fromhex(str(row["value"]))
        except ValueError as exc:  # fail closed on damaged trusted metadata
            raise CkmValidationError("CKM confirmation signing key is invalid") from exc

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
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT id, artifact_id, capability_id, basis
                FROM ckm_evidence_edge
                WHERE extraction_method = 'deterministic'
                """
            ).fetchall()
            stale = [
                row
                for row in rows
                if str(row["basis"]).startswith(owned_basis_prefixes)
                if (row["artifact_id"], row["capability_id"], row["basis"])
                not in edge_keys
            ]
            archived = []
            for row in stale:
                archived.append(
                    conn.execute(
                        "SELECT * FROM ckm_evidence_edge WHERE id = ?", (row["id"],)
                    ).fetchone()
                )
            self._archive_evidence_edges(conn, [row for row in archived if row is not None])
            for row in stale:
                conn.execute("DELETE FROM ckm_evidence_edge WHERE id = ?", (row["id"],))
            if stale:
                self._advance_state_revision(conn)
            conn.commit()
        return len(stale)

    def delete_evidence_edge(self, edge_id: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM ckm_evidence_edge WHERE id = ?", (edge_id,)
            ).fetchone()
            if row is not None:
                self._archive_evidence_edges(conn, [row])
            conn.execute("DELETE FROM ckm_evidence_edge WHERE id = ?", (edge_id,))
            if row is not None:
                self._advance_state_revision(conn)
            conn.commit()

    # --- Assessment (append-only, bitemporal) -----------------------------------

    def append_assessment(
        self,
        *,
        capability_id: str,
        scores: Mapping[str, float],
        citations: Mapping[str, list[JsonDict]],
        candidate_shares: Mapping[str, float] | None = None,
        formula_ids: Mapping[str, str] | None = None,
        aggregate: float,
        aggregate_formula_id: str = "legacy-pre-ckm07",
        low_confidence: bool = False,
        edge_fingerprint: str = "legacy",
        watermark_set: Mapping[str, str],
        valid_from: str | None = None,
        asserted_at: str | None = None,
    ) -> CkmAssessment:
        missing = set(MATURITY_DIMENSIONS) - set(scores)
        if missing:
            raise CkmValidationError(f"assessment missing dimension score(s): {sorted(missing)}")
        missing_citations = [d for d in MATURITY_DIMENSIONS if d not in citations]
        if missing_citations:
            raise CkmValidationError(
                f"assessment dimension(s) missing citations list: {sorted(missing_citations)}"
            )
        resolved_candidate_shares = candidate_shares or {
            dimension: 0.0 for dimension in MATURITY_DIMENSIONS
        }
        resolved_formula_ids = formula_ids or {
            dimension: "legacy-pre-ckm07" for dimension in MATURITY_DIMENSIONS
        }
        if not watermark_set:
            raise CkmValidationError("watermark_set must not be empty")

        now = utc_now()
        resolved_valid_from = valid_from or now
        resolved_asserted_at = asserted_at or now
        assessment_id = new_id("assess")

        columns = ["id", "public_id", "capability_id"]
        values: list[Any] = [assessment_id, "", capability_id]
        for dimension in MATURITY_DIMENSIONS:
            columns.append(dimension)
            values.append(scores[dimension])
            columns.append(f"{dimension}_citations")
            values.append(_dumps(citations[dimension]))
        columns += [
            "candidate_shares",
            "formula_ids",
            "aggregate",
            "aggregate_formula_id",
            "low_confidence",
            "edge_fingerprint",
            "watermark_set",
            "valid_from",
            "asserted_at",
        ]
        values += [
            _dumps(resolved_candidate_shares),
            _dumps(resolved_formula_ids),
            aggregate,
            aggregate_formula_id,
            int(low_confidence),
            edge_fingerprint,
            _dumps(watermark_set),
            resolved_valid_from,
            resolved_asserted_at,
        ]

        placeholders = ",".join("?" for _ in values)
        column_list = ",".join(columns)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            identity_row: JsonDict = {
                "capability_id": capability_id,
                **{dimension: scores[dimension] for dimension in MATURITY_DIMENSIONS},
                "candidate_shares": _dumps(resolved_candidate_shares),
                "formula_ids": _dumps(resolved_formula_ids),
                "aggregate": aggregate,
                "aggregate_formula_id": aggregate_formula_id,
                "low_confidence": int(low_confidence),
                "edge_fingerprint": edge_fingerprint,
                "watermark_set": _dumps(watermark_set),
                "valid_from": resolved_valid_from,
                "asserted_at": resolved_asserted_at,
            }
            values[1] = self._assessment_public_id(conn, identity_row)
            conn.execute(
                f"INSERT INTO ckm_assessment ({column_list}) VALUES ({placeholders})",
                values,
            )
            self._advance_state_revision(conn)
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

    def assessment_for_projection(self, capability_id: str) -> CkmAssessmentProjection:
        """Return the newest assessment plus store-derived freshness (INV-CKM-5)."""

        assessment = self.latest_assessment_for_capability(capability_id)
        if assessment is None:
            raise CkmValidationError(f"capability has no assessment: {capability_id}")
        current = self.current_watermark_set()
        return CkmAssessmentProjection(
            assessment=assessment,
            current_watermark_set=current,
            stale_relative_to_evidence=dict(assessment.watermark_set) != current,
        )

    @staticmethod
    def _assessment_from_row(row: sqlite3.Row) -> CkmAssessment:
        scores = {dimension: row[dimension] for dimension in MATURITY_DIMENSIONS}
        citations = {
            dimension: _loads(row[f"{dimension}_citations"]) for dimension in MATURITY_DIMENSIONS
        }
        candidate_shares = _loads(row["candidate_shares"])
        formula_ids = _loads(row["formula_ids"])
        watermark_set = _loads(row["watermark_set"])
        return CkmAssessment.from_row(
            dict(row),
            scores=scores,
            citations=citations,
            candidate_shares=candidate_shares,
            formula_ids=formula_ids,
            watermark_set=watermark_set,
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
        now = utc_now()
        candidate = CkmFinding(
            id=new_id("find"),
            public_id="pending",
            kind=kind,
            capability_id=capability_id,
            dimension=dimension,
            statement=statement,
            citations=citations,
            created_at=now,
            updated_at=now,
        ).validate()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                """
                SELECT * FROM ckm_finding
                WHERE kind = ? AND capability_id = ? AND dimension = ?
                """,
                (kind, capability_id, dimension),
            ).fetchone()
            citations_json = _dumps(candidate.citations)
            if (
                existing is not None
                and existing["statement"] == statement
                and existing["citations"] == citations_json
            ):
                conn.commit()
                return CkmFinding.from_row(existing, citations=candidate.citations)
            public_id = self._finding_public_id(conn, kind, capability_id, dimension)
            conn.execute(
                """
                INSERT INTO ckm_finding (
                    id, public_id, kind, capability_id, dimension, statement, citations,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(kind, capability_id, dimension) DO UPDATE SET
                    statement = excluded.statement,
                    citations = excluded.citations,
                    updated_at = excluded.updated_at
                """,
                (
                    candidate.id,
                    public_id,
                    candidate.kind,
                    candidate.capability_id,
                    candidate.dimension,
                    candidate.statement,
                    citations_json,
                    candidate.created_at,
                    candidate.updated_at,
                ),
            )
            self._advance_state_revision(conn)
            conn.commit()
        finding = self.get_finding(kind=kind, capability_id=capability_id, dimension=dimension)
        if finding is None:  # pragma: no cover - defensive
            raise CkmValidationError("finding upsert did not persist")
        return finding

    def replace_findings(self, findings: Sequence[Mapping[str, Any]]) -> list[CkmFinding]:
        """Atomically reconcile the disposable current finding projection."""

        now = utc_now()
        candidates: dict[tuple[str, str, str], CkmFinding] = {}
        for raw in findings:
            raw_citations = raw.get("citations", [])
            if not isinstance(raw_citations, list):
                raise CkmValidationError("finding citations must be a list")
            candidate = CkmFinding(
                id=new_id("find"),
                public_id="pending",
                kind=str(raw.get("kind", "")),
                capability_id=str(raw.get("capability_id", "")),
                dimension=str(raw.get("dimension", "")),
                statement=str(raw.get("statement", "")),
                citations=list(raw_citations),
                created_at=now,
                updated_at=now,
            ).validate()
            key = (candidate.kind, candidate.capability_id, candidate.dimension)
            if key in candidates:
                raise CkmValidationError(f"duplicate finding natural key: {key}")
            candidates[key] = candidate

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing_rows = conn.execute("SELECT * FROM ckm_finding").fetchall()
            existing = {
                (row["kind"], row["capability_id"], row["dimension"]): row
                for row in existing_rows
            }
            changed = bool(set(existing) ^ set(candidates))
            for kind, capability_id, dimension in set(existing) - set(candidates):
                conn.execute(
                    """
                    DELETE FROM ckm_finding
                    WHERE kind = ? AND capability_id = ? AND dimension = ?
                    """,
                    (kind, capability_id, dimension),
                )
            for key, candidate in sorted(candidates.items()):
                row = existing.get(key)
                citations_json = _dumps(candidate.citations)
                if row is None:
                    public_id = self._finding_public_id(
                        conn, candidate.kind, candidate.capability_id, candidate.dimension
                    )
                    conn.execute(
                        """
                        INSERT INTO ckm_finding (
                            id, public_id, kind, capability_id, dimension, statement,
                            citations, created_at, updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            candidate.id,
                            public_id,
                            candidate.kind,
                            candidate.capability_id,
                            candidate.dimension,
                            candidate.statement,
                            citations_json,
                            candidate.created_at,
                            candidate.updated_at,
                        ),
                    )
                elif row["statement"] != candidate.statement or row["citations"] != citations_json:
                    changed = True
                    conn.execute(
                        """
                        UPDATE ckm_finding
                        SET statement = ?, citations = ?, updated_at = ?
                        WHERE kind = ? AND capability_id = ? AND dimension = ?
                        """,
                        (
                            candidate.statement,
                            citations_json,
                            now,
                            candidate.kind,
                            candidate.capability_id,
                            candidate.dimension,
                        ),
                    )
            if changed:
                self._advance_state_revision(conn)
            conn.commit()
        return self.list_findings()

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

    def list_findings(self) -> list[CkmFinding]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ckm_finding
                ORDER BY kind, capability_id, dimension
                """
            ).fetchall()
        return [CkmFinding.from_row(row, citations=_loads(row["citations"])) for row in rows]
