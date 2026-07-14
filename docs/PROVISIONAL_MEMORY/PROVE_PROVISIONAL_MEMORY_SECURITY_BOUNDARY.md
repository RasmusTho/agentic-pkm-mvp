---
name: Prove Provisional Memory Security Boundary
description: Close the capability with deterministic bilingual poisoning and authority-boundary regression gates.
task_id: PROVISIONAL-MEMORY-04
source_anchor: docs/eval.md :: Deterministic retrieval/memory/classification metrics runner
parent_capability: Provisional Memory
prerequisites: [PROVISIONAL-MEMORY-03]
depends_on: [ADMIT_PROVISIONAL_MEMORY_AS_LOW_TRUST_CONTEXT.md]
can_parallelize_with: []
---

# PROVE_PROVISIONAL_MEMORY_SECURITY_BOUNDARY

## Purpose

Turn the composed W7 boundary into a deterministic regression gate before the capability is accepted
or any quality/security claim is made.

## What This Task Does

- Adds bilingual SV/EN cases for direct-write poisoning, prompt injection, false authority claims,
  provenance loss, citation omission, and attempted APPLY escalation.
- Exercises the real API → artifact/receipt → recall/context chain.
- Wires the cases into the deterministic eval/CI path without calling a live LLM.
- Produces the parent-closure verification packet and owner-doc promotion handoff.

## Concretely

The same fixtures always produce the same verdict. Any provisional-memory route into action
authority, uncited proposal influence, missing trust posture, or missing provenance is a blocking
failure, not a threshold-tuned quality metric.

## Why This Matters

Unit tests can prove local helpers while missing a composition bypass. The final gate proves the
authority invariant across production boundaries and both supported languages.

## Acceptance Criteria

- [ ] The bilingual fixture covers benign and adversarial provisional-memory use in SV and EN.
  Verify: `tests/eval/fixtures/provisional_memory_boundary.yaml`
- [ ] The deterministic runner blocks any action-tier, uncited-proposal, provenance-loss, or hidden-
  trust result. Verify: `tests/eval/test_provisional_memory_boundary.py::test_bilingual_provisional_memory_boundary`
- [ ] The end-to-end production chain is exercised from API write through guarded recall/context.
  Verify: `tests/agent_memory/test_provisional_memory_end_to_end.py::test_direct_write_remains_low_trust_through_recall`
- [ ] Existing bilingual retrieval/memory metrics do not regress. Verify: `tests/eval/test_golden_metrics.py::test_golden_eval_pipeline` and `tests/eval/test_golden_metrics.py::test_memory_recall_slice`
- [ ] Parent #2314 receives a closure packet listing all child merges, test/eval evidence, owner-doc
  writeback, and any operator-only residual. Verify: GitHub issue #2314 comment headed `W7 capability validation receipt`

## How to Verify (Pre-Merge)

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q \
  tests/eval/test_provisional_memory_boundary.py \
  tests/agent_memory/test_provisional_memory_end_to_end.py \
  tests/eval/test_golden_metrics.py::test_golden_eval_pipeline \
  tests/eval/test_golden_metrics.py::test_memory_recall_slice
python -m app.eval.run
ruff check app tests
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q -m "not pg"
```

Attach the deterministic scorecard/summary to the PR and parent receipt.

## Out of Scope

- Live-model quality judgments or default flips.
- Production deployment, reindex, or BGE-M3 cutover.
- W8 UI, W9 graph, or W10 agentic retrieval expansion.

## Related Docs

- `docs/eval.md`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/adr/ADR-0025-memory-authority-direct-write-policy.md`
- `docs/PROVISIONAL_MEMORY/README.md`

## Related GitHub Issues

Final implementation Issue under #2314. TCD hint: Sol/high-xhigh because this is the security and
cross-system acceptance gate.
