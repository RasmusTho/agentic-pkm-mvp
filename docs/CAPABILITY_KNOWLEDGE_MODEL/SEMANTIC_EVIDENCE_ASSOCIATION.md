---
name: Semantic Evidence Association
description: LLM association of unlinked artifacts to capabilities — candidate-labeled, confidence-scored, skip-on-unavailable
task_id: CKM-06
source_anchor: docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.13 AI Integration
parent_capability: Capability Knowledge Model
prerequisites: [CKM-05]
depends_on: [DETERMINISTIC_EVIDENCE_LINKERS.md]
can_parallelize_with: [Maturity Assessment Engine]
---

# Semantic Evidence Association

## Purpose

Extend evidence coverage to artifacts no mechanical rule can place (a doc that discusses retrieval without being cited by the matrix; a commit whose subject names a capability). This is the CKM's only inference surface in the MVP, and it is deliberately fenced.

## What This Task Does

- Implements `app/builderops/ckm/semantic.py`: takes the unlinked-artifact backlog from CKM-05, batches artifact summaries against the capability registry (names + definitions), and asks the configured LLM (routed via the repo's existing LLM routing, cheap-model tier) to propose `(artifact → capability, evidence_kind, maturity_dimension, confidence, one-line rationale)`.
- Every proposed edge is written with `extraction_method=inferred`, lifecycle `candidate` (OD-K5 / INV-CKM-3), model+provider provenance, and the rationale as `basis`.
- Threshold discipline: proposals under a configurable confidence floor (default 0.6) are **discarded, not stored** — a low-confidence guess in the store is noise that projections would have to caveat forever.
- Deterministic fallback (NFR-6): when no LLM is reachable, the stage reports `skipped (llm unavailable)` and exits 0 — the pipeline is complete without it, coverage is just lower.
- Confirmation path: `python -m app.builderops ckm confirm-edge <edge-id>` flips a candidate edge to `confirmed` and writes a BuilderOps confirmation receipt (re-applied on rebuild per INV-CKM-4).
- CLI: `python -m app.builderops ckm associate [--limit N]`.

## Concretely

```bash
python -m app.builderops ckm associate --limit 200
# → "proposed 74 candidate edges (mean conf 0.78), discarded 41 below floor, 85 no-match; model=<provider:model>"
python -m app.builderops ckm confirm-edge 8123
# → "edge 8123 confirmed; receipt builderops://receipts/<id>"
```

## Why This Matters

This is where the CKM could silently rot (Critical Review §8.2): unlabeled inference would launder guesses into the assessment. The candidate fence + confidence floor + model provenance are what keep maturity numbers auditable.

## Acceptance Criteria

- [ ] Inferred edges always carry `extraction_method=inferred`, lifecycle `candidate`, model/provider provenance, and a rationale; the writer refuses an inferred edge posing as deterministic/confirmed, asserted through the production write path (enforcement AC).
  - Verify: `tests/builderops/ckm/test_semantic.py::test_inferred_edges_fenced_via_store_write_path`
- [ ] Sub-floor proposals are discarded (not stored); the discard count is reported.
  - Verify: `tests/builderops/ckm/test_semantic.py::test_confidence_floor_discards`
- [ ] LLM-unavailable path: stage exits 0 with named skip, zero edges written, watermark untouched.
  - Verify: `tests/builderops/ckm/test_semantic.py::test_llm_unavailable_skips_cleanly`
- [ ] `confirm-edge` flips lifecycle and writes a receipt that `rebuild()` + re-link + re-apply restores (INV-CKM-4 roundtrip).
  - Verify: `tests/builderops/ckm/test_semantic.py::test_confirmation_receipt_survives_rebuild`

## How to Verify (Pre-Merge)

- `python -m pytest tests/builderops/ckm/test_semantic.py -q` (stubbed LLM; no live calls in CI)
- One live bounded run (`--limit 20`) locally; eyeball 5 proposals for sanity.
- Full `pytest -m "not pg"` before PR.

## Out of Scope

- Capability-existence hypotheses (proposing *new* capabilities) — post-MVP; the registry stays seed-defined in the MVP.
- Summaries (CKM-09 consumes edges; FR-11 summary generation is part of CKM-09's projection work only if cheap, else post-MVP).
- Any auto-confirmation, batch-confirmation UI, or prompt-tuning framework.

## Related Docs

- `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.13`, `docs/LLM_ROUTING.md`, `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Cross-Task Invariants`

## Related GitHub Issues

One issue. Blocked by CKM-05; parallel with CKM-07. TCD hint: Sonnet / high (prompt + fencing design; the guard tests are the hard part).
