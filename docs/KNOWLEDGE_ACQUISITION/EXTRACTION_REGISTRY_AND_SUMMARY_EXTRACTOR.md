---
name: Extraction Registry and Summary Extractor
description: The open extractor registry plus one worked-example extractor (summary) with schema-validated, fail-loud output
task_id: KA-04
source_anchor: "docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md :: Extraction registry"
parent_capability: Knowledge Acquisition Phase 2 vertical slice
prerequisites: [KA-03]
depends_on: [NORMALIZE_TRANSCRIPT.md]
can_parallelize_with: []
---

# Extraction Registry and Summary Extractor

## Purpose

Implement the extraction registry contract and prove it with exactly one extractor (`summary`).
The registry's openness — adding an extractor touches nothing else — is the platform's main
extension axis, so this task's real deliverable is the registration mechanism, not the summary.

## What This Task Does

- Registry: register `(extractor_id, version, input content type, output schema, model identity)`;
  extractors depend only on the normalized artifact and are mutually independent.
- `summary` extractor: LLM call routed per `docs/LLM_ROUTING.md`, output schema-validated at the
  boundary; schema mismatch is an explicit item-scoped failure, never a silent default (the
  correctness kernel's typed-LLM-boundary posture; STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN in
  spirit).
- Extraction lineage: extractor id + version + model identity stamped per
  `REFINEMENT_PIPELINE_CONTRACT.md` §Lineage.
- Re-running an extractor at the same version over unchanged input is an idempotent no-op;
  a bumped version replaces the prior extraction.

## Concretely

```
normalized (208 segments) → registry.run("summary@2") → {"summary": "...", "confidence": 0.8}
registry.run("summary@2") again → no-op (unchanged input, unchanged version)
```

## Why This Matters

If adding extractor #2 requires touching the pipeline, the platform premise fails. If extractor
output isn't schema-gated, a malformed LLM response flows into candidates as fact.

## Acceptance Criteria

- [ ] An extractor can be registered and run against a normalized fixture without modifying any
      pipeline or plugin code (enforced at the production call site: the pipeline resolves
      extractors only through the registry).
      Verify: `tests/knowledge_acquisition/test_extraction_registry.py::test_register_and_run_via_pipeline_callsite`
- [ ] `summary` output validates against its schema; a malformed LLM response (fixture) fails
      loudly and item-scoped, producing no extraction artifact.
      Verify: `tests/knowledge_acquisition/test_summary_extractor.py::test_schema_mismatch_fails_loud_no_artifact`
- [ ] Extraction lineage carries extractor id, version, and model identity.
      Verify: `tests/knowledge_acquisition/test_extraction_registry.py::test_lineage_stamped`
- [ ] Same input + same extractor version → idempotent no-op; bumped version → replacement.
      Verify: `tests/knowledge_acquisition/test_extraction_registry.py::test_version_replacement_semantics`

## How to Verify (Pre-Merge)

- `pytest tests/knowledge_acquisition/test_extraction_registry.py tests/knowledge_acquisition/test_summary_extractor.py -q` (LLM stubbed/mock provider)
- `ruff check app tests`

## Out of Scope

The other example extractors (claims, entities, action_items — follow-on issues after slice
acceptance); prompt quality tuning; chunking; embeddings.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md` §Extraction registry
- `docs/LLM_ROUTING.md`, `docs/CAPABILITY_CONTRACT_MODEL.md` (proposal-class declaration)

## Related GitHub Issues

One issue. TCD hint: Sonnet / high (registry design + typed LLM boundary).
