---
name: CKM Projections and Query
description: BuilderOps Markdown projections (capability map, maturity, gaps, generated traceability matrix) plus a CLI query surface — watermarked, self-identifying
task_id: CKM-09
source_anchor: docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.15 Interfaces
parent_capability: Capability Knowledge Model
prerequisites: [CKM-07, CKM-08]
depends_on: [MATURITY_ASSESSMENT_ENGINE.md, GAP_AND_MISSING_EVIDENCE_DETECTION.md]
can_parallelize_with: []
---

# CKM Projections and Query

## Purpose

Make the model consumable — for the owner, for builder agents, and for reports — through the existing BuilderOps projection discipline: generated Markdown views that identify themselves as projections and never masquerade as truth.

## What This Task Does

- Extends `app/builderops/ckm/projections.py` with four projection types, following the `app/builderops/projections.py` metadata contract (every output opens with the generated-projection header):
  - `ckm-capability-map` — the capability forest with lifecycle, boundary refs, evidence counts (confirmed vs candidate), unlinked-artifact count.
  - `ckm-maturity` — per capability: the seven-dimension vector with per-dimension citations count, candidate share, low-confidence and **staleness** flags (INV-CKM-5: assessment older than evidence watermark ⇒ `STALE` marker). The stored aggregate remains a compatibility field but is not rendered in Markdown projections.
  - `ckm-gaps` — current findings grouped by kind, each with its statement + citations.
  - `ckm-traceability-matrix` — a generated matrix in the same column shape as `docs/architecture/traceability-matrix.md`, emitted for **side-by-side comparison** with the hand-authored one; divergence is a signal, never an auto-edit (ADR-0057 §Consequences).
- CLI query surface: `python -m app.builderops ckm show <capability-slug>` (assessment + evidence listing with basis strings) and `python -m app.builderops ckm project --type <type> --out <dir>`.
- Every egress line of every surface carries: projection self-identification, generation timestamp, watermark set, and the candidate/confirmed distinction (INV-CKM-2/3).

## Concretely

```bash
python -m app.builderops ckm project --type ckm-maturity --out /tmp/ckm/
head -3 /tmp/ckm/ckm-maturity.md
# > Generated projection (BuilderOps CKM). Not source of truth. Watermarks: repo=<sha> github=<ts>. Generated: <ts>.
python -m app.builderops ckm show retrieval
# → vector + citations + 41 evidence edges (38 confirmed / 3 candidate) + staleness: current
```

## Why This Matters

INV-CKM-2 lives or dies here: this is the layer humans and agents actually read. A projection missing its watermark or candidate labeling converts every upstream honesty guarantee into silent false confidence.

## Acceptance Criteria

- [ ] All four projection types render over a populated fixture store and open with the generated-projection metadata header including watermark set.
  - Verify: `tests/builderops/ckm/test_projections.py::test_all_egress_self_identifies_with_watermark`
- [ ] The staleness flag renders when evidence watermark > assessment watermark, asserted through the real projection render path (enforcement AC for INV-CKM-5).
  - Verify: `tests/builderops/ckm/test_projections.py::test_stale_assessment_flagged_in_render`
- [ ] Candidate vs confirmed evidence is visibly distinguished in map, maturity, and `show` output.
  - Verify: `tests/builderops/ckm/test_projections.py::test_candidate_confirmed_distinction_rendered`
- [ ] The generated traceability matrix matches the hand-authored matrix's column shape and is written only under the projection output dir — never over `docs/architecture/traceability-matrix.md`.
  - Verify: `tests/builderops/ckm/test_projections.py::test_generated_matrix_shape_and_never_overwrites_canonical`

## How to Verify (Pre-Merge)

- `python -m pytest tests/builderops/ckm/test_projections.py -q`
- Live end-to-end: seed→ingest→link→assess→gaps→project; read all four outputs for sanity.
- Full `pytest -m "not pg"` before PR.

## Out of Scope

- HTML rendering (CKM-10). HTTP API (post-MVP; CLI + files are the MVP interface). Conversational/NL query (post-MVP).
- Publishing projections into `docs/generated/` via CI (operator decision later; MVP writes to a chosen output dir).

## Related Docs

- `docs/builderops/BUILDEROPS_VAULT_PROJECTIONS.md` (metadata contract), `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Cross-Task Invariants`

## Related GitHub Issues

One issue. Blocked by CKM-07 + CKM-08. TCD hint: Sonnet / medium (rendering over a tested substrate; header/flag discipline is checklist-like).
