---
name: Define Zero-Write Finding Adapter
description: Expose the delivered contradiction harness through a supported read-only, scope-safe boundary for the existing note/Panel proposal flow.
task_id: CTB-01
source_anchor: docs/CONTRADICTION_TRIAGE_BENCH/README.md :: First delivery
parent_capability: Contradiction Triage Bench
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Define Zero-Write Finding Adapter

## Purpose

Turn the delivered contradiction harness into a supported read-only seam for the existing note/Panel proposal flow without creating a parallel UI or a second persistence model.

## What This Task Does

Identify the sanctioned invocation and finding/citation interfaces in the current runtime, then expose a typed adapter that returns only findings admissible to the caller's current scope. The adapter must support an explicit `materialize=False` path and make the zero-write guarantee testable from its production call site. It feeds the existing proposal/confirmation model; it does not define a new human-facing review destination.

## Concretely

The adapter returns a stable finding projection containing only the finding identifier, two verbatim claims, citation-resolution handles, uncertainty/exclusion posture, and diagnostic scan outcome. It fails closed when citation resolution or scope admission is incomplete. It does not invent summary, severity, identity, confidence, or persistence fields.

## Why This Matters

The existing note/Panel proposal flow cannot safely consume a new read path if it reaches into curation internals, silently falls back to path-only evidence, or mistakes an incomplete result for no contradiction.

## Acceptance Criteria

- [ ] The supported harness invocation and returned finding/citation fields are named in code and documented as the Bench's read boundary. Verify: doc writeback at `docs/CONTRADICTION_TRIAGE_BENCH/README.md :: Current foundation and boundary`.
- [ ] The production adapter returns only findings whose two citations resolve under the caller's current admission context. Verify: `tests/curation/test_contradiction_triage_adapter.py::test_adapter_requires_two_resolvable_current_scope_citations`.
- [ ] A denied or unavailable citation returns no partial finding and exposes only a non-disclosing diagnostic outcome. Verify: `tests/curation/test_contradiction_triage_adapter.py::test_adapter_fails_closed_without_cross_scope_disclosure`.
- [ ] Invoking the adapter performs no panel materialization, vault write, outbox emission, receipt append, or suppression write. Verify: `tests/curation/test_contradiction_triage_adapter.py::test_adapter_is_zero_write_at_production_call_site`.
- [ ] Scan failure is distinguishable from a successful empty result. Verify: `tests/curation/test_contradiction_triage_adapter.py::test_adapter_distinguishes_failure_from_no_findings`.

## How to Verify (Pre-Merge)

- `pytest -q tests/curation/test_contradiction_triage_adapter.py`
- `pytest -q tests/curation/test_contradiction_citations_resolve.py tests/curation/test_semantic_never_autowrites.py`
- `pytest -q tests/invariants/test_curation_invariants.py -k 'citations_resolve or semantic_curation_never_autowrites'`

## Out of Scope

No new graphical surface, parallel confirmation model, durable dismissal, triage ledger, superseding-artifact writer, truth adjudication, or cross-scope import/cite authority.

## Related Docs

- `docs/MIMER_CAPABILITY_HARDENING/GRADUATED_CURATION.md :: §4, §6 (G2-4)`
- `docs/CONTRADICTION_TRIAGE_BENCH/README.md`

## Related GitHub Issues

Implementation issue: [#3544](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3544). TCD hint: Terra / high reasoning; the slice touches curation, retrieval admission, and a no-write invariant.
