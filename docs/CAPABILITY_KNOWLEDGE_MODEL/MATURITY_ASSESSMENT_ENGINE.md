---
name: Maturity Assessment Engine
description: Seven-dimension explainable maturity vector per capability with transparent aggregation, full evidence citations, and incremental re-assessment
task_id: CKM-07
source_anchor: docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 6. Information Model (Maturity dimensions)
parent_capability: Capability Knowledge Model
prerequisites: [CKM-05]
depends_on: [DETERMINISTIC_EVIDENCE_LINKERS.md]
can_parallelize_with: [Semantic Evidence Association]
---

# Maturity Assessment Engine

## Purpose

Compute the load-bearing output of the CKM: an explainable maturity assessment per capability. Explainability is the whole design (NFR-1): the vector is the judgment; any scalar is a labeled convenience.

## What This Task Does

- Implements `app/builderops/ckm/assess.py` computing, per capability, seven dimension scores in [0,1] from evidence edges — **pure transparent functions over edge counts/kinds/polarity, no LLM**:
  1. functional completeness (merged PRs + source edges vs. spec/requirement edges; weakened by `weakens` edges)
  2. test completeness (test edges + invariant-registry citations)
  3. documentation quality (doc edges whose artifacts carry a current `State:` header)
  4. integration completeness (evidence spanning ≥2 artifact kinds incl. source + caller/surface docs; built-but-dormant scores low)
  5. operational readiness (ops/runbook/health doc edges)
  6. architectural stability (inverse recent-churn from git edges)
  7. requirement coverage (fraction of requirement/spec edges that also have realizing + verifying edges)
- Each dimension emits `(score, citations[], candidate_share, formula_id)`. Scoring formulas live in one module-level table (`FORMULAS`) so the published function is inspectable and versioned (`formula_id` stored per assessment).
- Aggregate = **weighted-min** family: `aggregate = min(dimensions weighted per FORMULAS)` so one starved dimension cannot hide (SRS §6). Stored alongside the vector, labeled `convenience`.
- Candidate-share honesty (INV-CKM-3): every dimension reports what fraction of its supporting evidence is `candidate`; assessments over majority-candidate evidence are flagged `low-confidence`.
- Bitemporal append (INV-CKM-5): each run writes new assessment rows recording the watermark set read; never updates in place.
- Incremental: re-assesses only capabilities whose edge set changed since their newest assessment.
- CLI: `python -m app.builderops ckm assess`.

## Concretely

```bash
python -m app.builderops ckm assess
# → "assessed 31 capabilities (12 unchanged, skipped); e.g. retrieval: [F .8, T .7, D .9, I .6, O .4, S .8, R .7] agg .4(min:ops) cand 8%"
```

## Why This Matters

Critical Review §8.1: an opaque maturity number that reads as truth is the subsystem's chief failure mode and would make the whole CKM net-harmful. Every property here (citations, formula ids, candidate share, append-only) exists to keep the number auditable.

## Acceptance Criteria

- [ ] Every dimension score of every assessment carries ≥0 citations resolving to real evidence edges, and a `formula_id` present in the published `FORMULAS` table.
  - Verify: `tests/builderops/ckm/test_assessment_engine.py::test_every_dimension_cites_evidence`
- [ ] The aggregate is reproducible from the stored vector by the published function (recompute == stored), and a starved dimension caps it (weighted-min property).
  - Verify: `tests/builderops/ckm/test_assessment_engine.py::test_aggregate_transparent_and_min_capped`
- [ ] Candidate-share is computed per dimension and the low-confidence flag fires when candidate evidence is the majority.
  - Verify: `tests/builderops/ckm/test_assessment_engine.py::test_candidate_share_and_low_confidence_flag`
- [ ] Assessments are append-only with recorded watermark set; a stale assessment (evidence watermark advanced past it) is detectable from store state alone (INV-CKM-5), asserted via the store read path used by projections (enforcement AC).
  - Verify: `tests/builderops/ckm/test_assessment_engine.py::test_staleness_detectable_from_projection_read_path`
- [ ] Incremental: unchanged edge set ⇒ no new assessment row.
  - Verify: `tests/builderops/ckm/test_assessment_engine.py::test_incremental_skip_unchanged`

## How to Verify (Pre-Merge)

- `python -m pytest tests/builderops/ckm/test_assessment_engine.py -q`
- Live run over the seeded+linked repo; sanity-eyeball 3 known capabilities (e.g. Retrieval should out-score Context building on functional completeness, matching their contract-model maturity labels).
- Full `pytest -m "not pg"` before PR.

## Out of Scope

- LLM-anything. Formula *tuning* beyond sane defaults (delivery iterates; `formula_id` versioning is the seam).
- Gap findings (CKM-08), rendering (CKM-09/10), maturity *targets* or thresholds policy.

## Related Docs

- `docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: §6, §8.1`, `docs/COMPONENTS.md :: Maturity taxonomy` (labels to sanity-check against), `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Cross-Task Invariants`

## Related GitHub Issues

One issue. Blocked by CKM-05; parallel with CKM-06. TCD hint: Sonnet / high (formula design + invariants; strong test harness makes verification cheap).
