---
name: CKM Store and Object Model
description: CEG tables (capability, evidence edge, assessment, finding) in the BuilderOps store, plus the evidence_kind orthogonality fitness check
task_id: CKM-01
source_anchor: docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 6. Information Model
parent_capability: Capability Knowledge Model
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# CKM Store and Object Model

## Purpose

Give the Capability Evidence Graph a durable, rebuildable home inside the existing BuilderOps SQLite substrate (ADR-0057 OD-K4). Everything downstream (seed, ingestion, linking, assessment, projection) writes through this layer.

## What This Task Does

- Creates package `app/builderops/ckm/` with `models.py` (dataclasses) and `schema.py` (DDL), following the existing `app/builderops/models.py` / `schema.py` / `store.py` patterns.
- Adds tables (prefix `ckm_`): `ckm_capability` (id, name, definition, parent_id, lifecycle `candidate|confirmed|deprecated`, existence_provenance, boundary_ref, timestamps), `ckm_artifact` (natural key = source ref, artifact_kind, source, watermark fields, provenance), `ckm_evidence_edge` (artifact_id, capability_id, evidence_kind, polarity `supports|weakens`, maturity_dimension, confidence, extraction_method `deterministic|inferred`, model/provider when inferred, lifecycle per INV-CKM-3), `ckm_assessment` (capability_id, 7 dimension scores + per-dimension citation JSON, aggregate, watermark_set, valid_from/asserted_at — bitemporal, append-only), `ckm_finding` (kind `gap|missing_evidence`, capability_id, dimension, statement, citations).
- Store accessors in `app/builderops/ckm/store.py`: idempotent upserts on natural keys (INV-CKM-7), append-only assessments (INV-CKM-5), and a `rebuild()` that drops + recreates `ckm_*` tables only.
- Writes a BuilderOps receipt for schema creation/rebuild events via the existing receipt mechanism.
- Ships the orthogonality fitness check (INV-CKM-6): a test asserting no module under `app/builderops/ckm/` imports runtime semantic-dimension code or references the runtime `evidence_role` field.

## Concretely

```bash
python -m pytest tests/builderops/ckm/test_store.py -q            # store roundtrip green
python - <<'PY'
from app.builderops.ckm.store import CkmStore
s = CkmStore.open_default(); s.ensure_schema(); print(sorted(s.table_names()))
PY
# ['ckm_artifact', 'ckm_assessment', 'ckm_capability', 'ckm_evidence_edge', 'ckm_finding']
```

## Why This Matters

If the store lacks provenance columns, idempotent keys, or bitemporal assessments, every downstream invariant (INV-CKM-1/4/5/7) becomes unenforceable and would need a schema migration mid-delivery. If `evidence_kind` can reach runtime `evidence_role`, the CKM silently becomes an authority channel — the one failure ADR-0010 forbids.

## Acceptance Criteria

- [ ] `ckm_*` tables create, upsert idempotently (same natural key twice ⇒ one row), and survive a full drop+recreate via `rebuild()`.
  - Verify: `tests/builderops/ckm/test_store.py::test_upsert_idempotent_and_rebuild`
- [ ] Every table enforces provenance-bearing NOT NULL columns (source ref, extraction method where applicable, timestamps) — inserting a provenance-less row fails.
  - Verify: `tests/builderops/ckm/test_store.py::test_provenance_columns_required`
- [ ] Assessments are append-only bitemporal: writing a second assessment for the same capability preserves the first and orders by `asserted_at`.
  - Verify: `tests/builderops/ckm/test_store.py::test_assessment_append_only_bitemporal`
- [ ] Orthogonality enforcement: CKM modules do not import runtime semantic-dimension modules nor reference the runtime `evidence_role` field, asserted against the real package on disk (production call-site level, not a mock).
  - Verify: `tests/builderops/ckm/test_evidence_kind_orthogonality.py::test_ckm_never_touches_runtime_evidence_role`
- [ ] Schema creation/rebuild emits a BuilderOps receipt through the existing receipt path.
  - Verify: `tests/builderops/ckm/test_store.py::test_schema_events_emit_receipt`

## How to Verify (Pre-Merge)

- `python -m pytest tests/builderops/ckm/ -q` (new tests above)
- `python -m pytest tests/builderops/ -q` (no regression in existing store/CLI/projection tests)
- Full `pytest -m "not pg"` per DEV_WORKFLOW before PR.

## Out of Scope

- Seeding capabilities (CKM-02), any ingestion (CKM-03/04), linking (CKM-05/06), scoring (CKM-07), projections (CKM-09).
- Any migration of existing BuilderOps tables; `ckm_*` is additive only.
- Graph databases or new storage dependencies.

## Restart / Durability Posture

The store is a local SQLite file (existing BuilderOps substrate): rows survive process restarts on the machine that wrote them, and the whole CEG is rebuildable from sources (INV-CKM-4), so machine loss costs only re-synthesis time plus unconfirmed local receipts. No user-facing surface ships in this task.

## Related Docs

- `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 6. Information Model`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md` (OD-K3, OD-K4, OD-K5)
- `docs/builderops/BUILDEROPS_VAULT_STORE.md`, `app/builderops/store.py` (patterns to follow)
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Cross-Task Invariants`

## Related GitHub Issues

One issue. Blocks CKM-02/03/04. TCD hint: Sonnet / high (schema design with cross-task consequences; verification is strong once tests exist).
