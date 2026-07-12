---
name: Capability Registry Seed
description: Checked-in capability seed manifest derived from SBS + Capability Contract Model, plus an idempotent loader
task_id: CKM-02
source_anchor: docs/research/DEVELOPMENT_KNOWLEDGE_MODEL.md :: 5.11 Capability Model
parent_capability: Capability Knowledge Model
prerequisites: [CKM-01]
depends_on: [CKM_STORE_AND_OBJECT_MODEL.md]
can_parallelize_with: [Repo Artifact Ingestion, GitHub Artifact Ingestion]
---

# Capability Registry Seed

## Purpose

Populate the capability forest from the taxonomy the repo already owns — the SBS macro-domains/control boundaries and the Capability Contract Model's canonical capabilities — so the CKM assesses the *agreed* decomposition instead of inventing one (ADR-0057 §Constraints).

## What This Task Does

- Authors `app/builderops/ckm/seed/capabilities.yaml`: a human-reviewable manifest with one entry per capability — `id` (stable slug), `name`, `definition` (1–2 sentences), `parent` (slug or null), `boundary_ref` (SBS Level-2 code like `RCA`, `HKA`, or null), `seed_source` (doc path :: anchor).
- Seed content: roots = the eight SBS macro-domains; second level = the fourteen Level-2 control boundaries mapped under their domains; leaves = the canonical capabilities from `docs/CAPABILITY_CONTRACT_MODEL.md :: Examples` (Retrieval, Orientation, Resurfacing, Context building, Citation checking, Memory candidate extraction, Note patch proposal, Archive exposure, Commitment surfacing) plus the per-capability spec directories named there, each placed under its owning boundary.
- Implements `app/builderops/ckm/seed.py` loader: validates the manifest (unique slugs, acyclic parents, resolvable `seed_source` paths), upserts into `ckm_capability` with lifecycle `confirmed` (human-authored manifest = confirmed by construction) and `existence_provenance = seeded:<seed_source>`.
- CLI: `python -m app.builderops ckm seed` (extends the existing BuilderOps CLI pattern).

## Concretely

```bash
python -m app.builderops ckm seed
# → "seeded 31 capabilities, 31 changed" (8 domains + 14 boundaries + 9 leaf capabilities)
python -m app.builderops ckm seed
# → "seeded 31 capabilities, 0 changed" (second run: idempotent, 0 changes)
```

## Why This Matters

Seed grain is the anti-drift anchor (Critical Review §8.3): if the CKM invents its own taxonomy, it forks the SBS and every maturity number becomes incomparable with the architecture docs. Idempotency (INV-CKM-7) makes re-seeding after manifest edits safe.

## Acceptance Criteria

- [ ] The manifest covers all 8 SBS macro-domains and all 14 Level-2 boundaries with correct parentage, and every entry's `seed_source` resolves to an existing repo path.
  - Verify: `tests/builderops/ckm/test_seed.py::test_manifest_covers_sbs_and_sources_resolve`
- [ ] Loader validation rejects duplicate slugs and parent cycles with a named error.
  - Verify: `tests/builderops/ckm/test_seed.py::test_loader_rejects_duplicates_and_cycles`
- [ ] Seeding is idempotent: two consecutive runs leave identical table contents; editing one manifest entry updates exactly that row.
  - Verify: `tests/builderops/ckm/test_seed.py::test_seed_idempotent_and_incremental`
- [ ] Seeded rows carry `existence_provenance` pointing at their `seed_source` (INV-CKM-1).
  - Verify: `tests/builderops/ckm/test_seed.py::test_seeded_rows_carry_provenance`

## How to Verify (Pre-Merge)

- `python -m pytest tests/builderops/ckm/test_seed.py -q`
- Run the CLI twice against a temp store and diff row counts (idempotency smoke).
- Full `pytest -m "not pg"` before PR.

## Out of Scope

- Inferred/candidate capabilities (CKM-06 proposes; OD-K5 governs promotion).
- Evidence of any kind (CKM-03..06); maturity (CKM-07).
- Editing SBS or the Capability Contract Model — the manifest cites them, never restates their semantics.

## Related Docs

- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` (domains + boundaries), `docs/CAPABILITY_CONTRACT_MODEL.md :: Examples`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md` §Constraints
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md :: Cross-Task Invariants`

## Related GitHub Issues

One issue. Blocked by CKM-01; parallel with CKM-03/CKM-04. TCD hint: Sonnet / medium (manifest authoring is careful reading; loader is mechanical, well-tested).
