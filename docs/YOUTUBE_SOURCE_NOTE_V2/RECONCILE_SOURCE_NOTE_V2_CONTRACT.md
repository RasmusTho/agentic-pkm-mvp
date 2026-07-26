---
name: Reconcile YouTube Source Note v2 contract
description: Establish the authoritative v2 contract and decision gates before runtime work.
task_id: YSNV2-01
source_anchor: docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Reconciliation baseline
parent_capability: YouTube Source Note v2
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Reconcile Source Note v2 Contract

## Purpose

Turn the reconciled current-state evidence and target-state intent into an authoritative v2 contract with an explicit output-language rule. This is docs/contract work, not runtime implementation.

## What This Task Does

Records the three confirmed V1 defects, the V1 non-defects, the new partial-success invariant, metadata-bundle conformance rules, and the recorded D1–D6 owner decisions. It establishes exact writeback anchors for later Product/Runtime tasks.

## Concretely

Update the knowledge-acquisition and source-note contract surfaces to state that raw evidence is immutable; a candidate is terminal only after note materialization; optional extractor failure is visible/rerunnable; all D1–D6 owner decisions are preserved; re-extraction produces a versioned proposal companion; and system prose is English unless the source's original language is Swedish.

## Why This Matters

Without this reconciliation, later work could fix the wrong V1 behaviors, emit invalid metadata bundles, or silently change authority and replay semantics.

## Acceptance Criteria

- [ ] The owner-contract writeback distinguishes the three confirmed V1 defects from process-local extraction, fixed rendering, and title-bearing paths as non-defects.
  Verify: doc writeback at `docs/KNOWLEDGE_ACQUISITION/YOUTUBE_SOURCE_SPEC.md :: Writeback`.
- [ ] The pipeline contract defines required-versus-optional extractor materialization semantics and visible rerun behavior.
  Verify: doc writeback at `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Stage execution model`.
- [ ] The metadata rule names top-level bundle fields, object-form `scope_binding`, and required identity/provenance/episode/sensitivity/suppression resolution; it does not copy invalid brief examples.
  Verify: doc writeback at `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Reconciliation baseline`.
- [ ] Recorded D1–D6 decisions are preserved explicitly, including D5 versioned proposal companions and D6 English output except for Swedish-original sources.
  Verify: operator receipt at `docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: Owner decision record`.

## How to Verify (Pre-Merge)

- Review each cited doc anchor against `docs/architecture/metadata-bundle.md` and `schemas/metadata-bundle.schema.json`.
- Run `python3 scripts/docs_guard.py` if the owner-doc writeback changes guarded surfaces.

## Out of Scope

Code, schemas, GitHub issue filing, and changing the recorded D1–D6 decisions.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/README.md`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md`
- `docs/architecture/metadata-bundle.md`

## Related GitHub Issues

Live Issue: [#4108](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4108). This task delivers
contract-only writebacks for later Product/Runtime work and no v2 runtime behavior. Recommended
capability: Terra/high; this is bounded reconciliation with doc-anchor verification.
