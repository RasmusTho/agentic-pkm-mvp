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

- Implements `app/builderops/ckm/semantic.py`: takes the unlinked-artifact backlog from CKM-05,
  batches artifact summaries against the capability registry (names + definitions), and submits a
  provider-free `ModelAccessIntent` through the Builder-owned resolver and neutral
  `ModelTurnAdapter` contract. The request declares `fallback_forbidden`; provider, model, adapter,
  effective identity, and credential identity are resolver outputs rather than caller fields.
- The production path uses only the declared metered credential contract. Under ADR-0064's
  2026-07-30 owner-cost ruling those credentials are intentionally unprovisioned, so the current
  expected outcome is a visible `skipped` result with zero proposals and zero edge writes. Product
  LLM policy, Model Inquiry's sanctioned subscription session, mock/fake/deterministic identities,
  and degraded Builder routes are not fallback paths.
- Every proposed edge is written with `extraction_method=inferred`, lifecycle `candidate` (OD-K5 / INV-CKM-3), model+provider provenance, and the rationale as `basis`.
- Threshold discipline: proposals under a configurable confidence floor (default 0.6) are **discarded, not stored** — a low-confidence guess in the store is noise that projections would have to caveat forever.
- Fail-closed unavailable behavior (NFR-6): when the declared credential or an acceptable Builder
  route is unavailable, the stage names the safe reason, reports `proposals=0`, and exits 0 — the
  pipeline is complete without semantic inference and coverage is simply lower. It never writes
  degraded evidence.
- A validated proposal batch and its semantic watermark commit in one SQLite transaction. An
  interruption rolls back both, and concurrent reruns converge through the existing stable edge
  identity rather than exposing partial evidence under an unchanged watermark. The transaction
  revalidates every artifact and capability field sent to the model; drift produces a visible
  zero-write skip. The watermark binds the canonical input snapshot and accepted material edge
  state, so distinct batches or material output changes cannot retain a stale freshness identity.
  Conflicting proposals for one evidence-edge natural key are rejected before persistence.
- Confirmation path: `python -m app.builderops ckm confirm-edge <edge-id>` flips a candidate edge to `confirmed` and writes a BuilderOps confirmation receipt (re-applied on rebuild per INV-CKM-4).
- CLI: `python -m app.builderops ckm associate [--limit N]`.

## Concretely

```bash
python -m app.builderops ckm associate --limit 200
# → "skipped: declared credential unavailable: openai.api-key; proposals=0"
# Provider-backed proposal output is not claimed while metered credentials remain absent.
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

- `python -m pytest tests/builderops/ckm/test_semantic.py -q` (injected adapter contract; no live
  provider call and no mock provider identity)
- Run the production CLI with intentionally absent metered credentials and verify the visible
  zero-proposal skip. Do not provision or retry provider keys for this check.
- Full `pytest -m "not pg"` before PR.

## Out of Scope

- Capability-existence hypotheses (proposing *new* capabilities) — post-MVP; the registry stays seed-defined in the MVP.
- Summaries (CKM-09 consumes edges; FR-11 summary generation is part of CKM-09's projection work only if cheap, else post-MVP).
- Any auto-confirmation, batch-confirmation UI, or prompt-tuning framework.

## Related Docs

- `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.13`, `docs/LLM_ROUTING.md`, `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Cross-Task Invariants`

## Related GitHub Issues

One issue. Blocked by CKM-05; parallel with CKM-07. TCD hint: Sonnet / high (prompt + fencing design; the guard tests are the hard part).
