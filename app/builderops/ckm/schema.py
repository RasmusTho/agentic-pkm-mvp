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

CKM_SCHEMA_VERSION = 3

CKM_TABLE_NAMES = (
    "ckm_capability",
    "ckm_artifact",
    "ckm_evidence_edge",
    "ckm_assessment",
    "ckm_finding",
    "ckm_watermark",
)

CKM_DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS ckm_capability (
        id TEXT PRIMARY KEY,
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
    CREATE INDEX IF NOT EXISTS idx_ckm_capability_parent
    ON ckm_capability(parent_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_artifact (
        id TEXT PRIMARY KEY,
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
    CREATE INDEX IF NOT EXISTS idx_ckm_artifact_kind
    ON ckm_artifact(artifact_kind)
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_evidence_edge (
        id TEXT PRIMARY KEY,
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
    CREATE INDEX IF NOT EXISTS idx_ckm_evidence_edge_capability
    ON ckm_evidence_edge(capability_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ckm_evidence_edge_artifact
    ON ckm_evidence_edge(artifact_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_assessment (
        id TEXT PRIMARY KEY,
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
    CREATE INDEX IF NOT EXISTS idx_ckm_assessment_capability_asserted
    ON ckm_assessment(capability_id, asserted_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_finding (
        id TEXT PRIMARY KEY,
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
    CREATE INDEX IF NOT EXISTS idx_ckm_finding_capability
    ON ckm_finding(capability_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS ckm_watermark (
        source TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
]
