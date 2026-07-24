"""SQLite DDL for the Capability Evidence Graph (CEG) tables.

Additive to the existing BuilderOps SQLite substrate (``app/builderops/schema.py``):
these ``ckm_*`` tables live in the same database file but are never touched by
the base BuilderOps DDL, and no existing BuilderOps table is modified here
(constraint: CKM-01 is additive-only).

Every table below carries provenance-bearing NOT NULL columns (a source ref
or provenance column, an extraction-method column where applicable, and
created/updated or valid/asserted timestamps) so INV-CKM-1 is enforced at the
schema level, not only in application code.
"""

from __future__ import annotations

CKM_SCHEMA_VERSION = 5

CKM_TABLE_NAMES = (
    "ckm_state",
    "ckm_public_identity",
    "ckm_identity_successor",
    "ckm_capability",
    "ckm_artifact",
    "ckm_evidence_edge",
    "ckm_evidence_edge_history",
    "ckm_assessment",
    "ckm_finding",
    "ckm_watermark",
)

CKM_REQUIRED_QUERY_INDEXES = frozenset(
    {
        "idx_ckm_capability_parent_public",
        "idx_ckm_evidence_edge_capability_public",
        "idx_ckm_evidence_edge_artifact_public",
        "idx_ckm_assessment_capability_asserted_public",
        "idx_ckm_finding_capability_public",
    }
)

CKM_REQUIRED_COLUMNS = {
    "ckm_state": frozenset(
        {"singleton", "epoch", "state_revision", "schema_version", "created_at", "updated_at"}
    ),
    "ckm_public_identity": frozenset(
        {"public_id", "resource_type", "status", "created_at", "tombstoned_at"}
    ),
    "ckm_identity_successor": frozenset(
        {"source_public_id", "successor_public_id", "relation", "created_at"}
    ),
    "ckm_capability": frozenset(
        {
            "id", "public_id", "identity_key", "name", "definition", "parent_id",
            "lifecycle", "existence_provenance", "boundary_ref", "created_at", "updated_at",
        }
    ),
    "ckm_artifact": frozenset(
        {
            "id", "public_id", "source_ref", "artifact_kind", "source", "watermark",
            "provenance", "created_at", "updated_at",
        }
    ),
    "ckm_evidence_edge": frozenset(
        {
            "id", "public_id", "artifact_id", "capability_id", "evidence_kind", "polarity",
            "maturity_dimension", "confidence", "extraction_method", "model", "provider",
            "lifecycle", "source_ref", "basis", "created_at", "updated_at",
        }
    ),
    "ckm_evidence_edge_history": frozenset(
        {
            "history_id", "edge_id", "public_id", "artifact_id", "capability_id",
            "evidence_kind", "polarity", "maturity_dimension", "confidence",
            "extraction_method", "model", "provider", "lifecycle", "source_ref", "basis",
            "created_at", "updated_at", "retired_at",
        }
    ),
    "ckm_assessment": frozenset(
        {
            "id", "public_id", "capability_id",
            "functional_completeness", "functional_completeness_citations",
            "test_completeness", "test_completeness_citations",
            "documentation_quality", "documentation_quality_citations",
            "integration_completeness", "integration_completeness_citations",
            "operational_readiness", "operational_readiness_citations",
            "architectural_stability", "architectural_stability_citations",
            "requirement_coverage", "requirement_coverage_citations", "candidate_shares",
            "dimension_status", "formula_ids", "aggregate", "aggregate_formula_id", "low_confidence",
            "edge_fingerprint", "watermark_set", "valid_from", "asserted_at",
        }
    ),
    "ckm_finding": frozenset(
        {
            "id", "public_id", "kind", "capability_id", "dimension", "statement",
            "citations", "created_at", "updated_at",
        }
    ),
    "ckm_watermark": frozenset({"source", "value", "updated_at"}),
}

CKM_LEGACY_ADDED_COLUMNS = {
    "ckm_public_identity": frozenset(
        {"public_id", "resource_type", "status", "created_at", "tombstoned_at"}
    ),
    "ckm_identity_successor": frozenset(
        {"source_public_id", "successor_public_id", "relation", "created_at"}
    ),
    "ckm_capability": frozenset({"public_id", "identity_key"}),
    "ckm_artifact": frozenset({"public_id"}),
    "ckm_evidence_edge": frozenset({"public_id", "basis"}),
    "ckm_evidence_edge_history": frozenset({"public_id"}),
    "ckm_assessment": frozenset(
        {
            "public_id", "candidate_shares", "formula_ids", "aggregate_formula_id",
            "dimension_status", "low_confidence", "edge_fingerprint",
        }
    ),
    "ckm_finding": frozenset({"public_id"}),
    "ckm_watermark": frozenset(),
}

CKM_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS ckm_state (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        epoch TEXT NOT NULL,
        state_revision INTEGER NOT NULL CHECK (state_revision >= 0),
        schema_version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_public_identity (
        public_id TEXT PRIMARY KEY,
        resource_type TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('active', 'tombstone')),
        created_at TEXT NOT NULL,
        tombstoned_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_identity_successor (
        source_public_id TEXT NOT NULL REFERENCES ckm_public_identity(public_id),
        successor_public_id TEXT NOT NULL REFERENCES ckm_public_identity(public_id),
        relation TEXT NOT NULL CHECK (relation IN ('split_successor', 'merge_successor')),
        created_at TEXT NOT NULL,
        PRIMARY KEY (source_public_id, successor_public_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_capability (
        id TEXT PRIMARY KEY,
        public_id TEXT NOT NULL,
        identity_key TEXT NOT NULL,
        name TEXT NOT NULL UNIQUE,
        definition TEXT NOT NULL,
        parent_id TEXT,
        lifecycle TEXT NOT NULL CHECK (lifecycle IN ('candidate', 'confirmed', 'deprecated')),
        existence_provenance TEXT NOT NULL,
        boundary_ref TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_ckm_capability_public_id
    ON ckm_capability(public_id)
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_ckm_capability_identity_key
    ON ckm_capability(identity_key)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ckm_capability_parent
    ON ckm_capability(parent_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ckm_capability_parent_public
    ON ckm_capability(parent_id, public_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_artifact (
        id TEXT PRIMARY KEY,
        public_id TEXT NOT NULL,
        source_ref TEXT NOT NULL UNIQUE,
        artifact_kind TEXT NOT NULL,
        source TEXT NOT NULL,
        watermark TEXT NOT NULL,
        provenance TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_ckm_artifact_public_id
    ON ckm_artifact(public_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ckm_artifact_kind
    ON ckm_artifact(artifact_kind)
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_evidence_edge (
        id TEXT PRIMARY KEY,
        public_id TEXT NOT NULL,
        artifact_id TEXT NOT NULL REFERENCES ckm_artifact(id),
        capability_id TEXT NOT NULL REFERENCES ckm_capability(id),
        evidence_kind TEXT NOT NULL,
        polarity TEXT NOT NULL CHECK (polarity IN ('supports', 'weakens')),
        maturity_dimension TEXT NOT NULL,
        confidence REAL NOT NULL,
        extraction_method TEXT NOT NULL CHECK (extraction_method IN ('deterministic', 'inferred')),
        model TEXT,
        provider TEXT,
        lifecycle TEXT NOT NULL CHECK (lifecycle IN ('candidate', 'confirmed')),
        source_ref TEXT NOT NULL,
        basis TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (artifact_id, capability_id, basis)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_ckm_evidence_edge_public_id
    ON ckm_evidence_edge(public_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ckm_evidence_edge_capability
    ON ckm_evidence_edge(capability_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ckm_evidence_edge_artifact
    ON ckm_evidence_edge(artifact_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ckm_evidence_edge_capability_public
    ON ckm_evidence_edge(capability_id, public_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ckm_evidence_edge_artifact_public
    ON ckm_evidence_edge(artifact_id, public_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_evidence_edge_history (
        history_id TEXT PRIMARY KEY,
        edge_id TEXT NOT NULL,
        public_id TEXT NOT NULL,
        artifact_id TEXT NOT NULL,
        capability_id TEXT NOT NULL,
        evidence_kind TEXT NOT NULL,
        polarity TEXT NOT NULL,
        maturity_dimension TEXT NOT NULL,
        confidence REAL NOT NULL,
        extraction_method TEXT NOT NULL,
        model TEXT,
        provider TEXT,
        lifecycle TEXT NOT NULL,
        source_ref TEXT NOT NULL,
        basis TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        retired_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ckm_evidence_edge_history_edge
    ON ckm_evidence_edge_history(edge_id, retired_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_assessment (
        id TEXT PRIMARY KEY,
        public_id TEXT NOT NULL,
        capability_id TEXT NOT NULL REFERENCES ckm_capability(id),
        functional_completeness REAL NOT NULL,
        functional_completeness_citations TEXT NOT NULL,
        test_completeness REAL NOT NULL,
        test_completeness_citations TEXT NOT NULL,
        documentation_quality REAL NOT NULL,
        documentation_quality_citations TEXT NOT NULL,
        integration_completeness REAL NOT NULL,
        integration_completeness_citations TEXT NOT NULL,
        operational_readiness REAL NOT NULL,
        operational_readiness_citations TEXT NOT NULL,
        architectural_stability REAL NOT NULL,
        architectural_stability_citations TEXT NOT NULL,
        requirement_coverage REAL NOT NULL,
        requirement_coverage_citations TEXT NOT NULL,
        candidate_shares TEXT NOT NULL,
        dimension_status TEXT NOT NULL DEFAULT '{}',
        formula_ids TEXT NOT NULL,
        aggregate REAL NOT NULL,
        aggregate_formula_id TEXT NOT NULL,
        low_confidence INTEGER NOT NULL CHECK (low_confidence IN (0, 1)),
        edge_fingerprint TEXT NOT NULL,
        watermark_set TEXT NOT NULL,
        valid_from TEXT NOT NULL,
        asserted_at TEXT NOT NULL
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_ckm_assessment_public_id
    ON ckm_assessment(public_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ckm_assessment_capability_asserted
    ON ckm_assessment(capability_id, asserted_at)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ckm_assessment_capability_asserted_public
    ON ckm_assessment(capability_id, asserted_at, public_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_finding (
        id TEXT PRIMARY KEY,
        public_id TEXT NOT NULL,
        kind TEXT NOT NULL CHECK (kind IN ('gap', 'missing_evidence')),
        capability_id TEXT NOT NULL REFERENCES ckm_capability(id),
        dimension TEXT NOT NULL,
        statement TEXT NOT NULL,
        citations TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE (kind, capability_id, dimension)
    )
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_ckm_finding_public_id
    ON ckm_finding(public_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ckm_finding_capability
    ON ckm_finding(capability_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ckm_finding_capability_public
    ON ckm_finding(capability_id, public_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_watermark (
        source TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
]
