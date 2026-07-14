---
name: Admit Provisional Memory As Low-Trust Context
description: Admit valid provisional memory only to read and explicitly cited proposal contexts, never action authority.
task_id: PROVISIONAL-MEMORY-03
source_anchor: docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Authority rules
parent_capability: Provisional Memory
prerequisites: [PROVISIONAL-MEMORY-02]
depends_on: [WRITE_PROVISIONAL_MEMORY_THROUGH_GOVERNED_API.md]
can_parallelize_with: []
---

# ADMIT_PROVISIONAL_MEMORY_AS_LOW_TRUST_CONTEXT

## Purpose

Make provisional memory useful for recall without allowing it to become hidden evidence or an
action-authorizing input.

## What This Task Does

- Extends the shipped guarded-recall/context path to load only complete, provenance-bearing
  provisional records.
- Applies the context-admissibility predicate and clamps influence to read or explicitly cited
  proposal support.
- Preserves visible trust, review, provenance, and `may_write=false` posture in the resulting
  ContextBundle/ContextEnvelope.
- Emits recall receipts without persisting activation state as authority.

## Concretely

An answer may display or use provisional memory with its low-trust label. A proposal may cite it
explicitly. Missing provenance, incomplete lifecycle pairs, or any action-tier request are excluded
fail-closed and diagnosed without leaking content.

## Why This Matters

The guard must execute where memory enters real context. Testing only the policy helper would not
prevent a new recall caller from bypassing the ceiling.

## Acceptance Criteria

- [ ] The production recall path invokes admissibility and authority guards for provisional memory.
  Verify: `tests/agent_memory/test_provisional_memory_call_sites.py::test_recall_path_invokes_low_trust_guards`
- [ ] Read use preserves visible provenance/review posture and `may_write=false`.
  Verify: `tests/agent_memory/test_provisional_memory_recall.py::test_read_context_preserves_low_trust_posture`
- [ ] Proposal influence requires an explicit citation; uncited background influence is excluded.
  Verify: `tests/agent_memory/test_provisional_memory_recall.py::test_proposal_use_requires_explicit_citation`
- [ ] Provisional memory cannot reach APPLY/tool-use or an action-authorizing context even when
  repeated or highly ranked. Verify: `tests/agent_memory/test_provisional_memory_call_sites.py::test_provisional_memory_cannot_reach_action_authority`
- [ ] Activation produces a recall receipt and does not mutate the artifact or lifecycle authority.
  Verify: `tests/agent_memory/test_provisional_memory_recall.py::test_recall_receipt_does_not_persist_activation_authority`

## How to Verify (Pre-Merge)

Run the named recall/call-site tests plus context-admissibility, context-bundle, guarded-recall, and
retrieval-scope suites. The action-tier assertion must exercise the real consumer entry point.

## Out of Scope

- Promotion, canonicalization, or write proposal application.
- Retrieval ranking/default changes.
- Memory review UI changes.

## Related Docs

- `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/architecture/context-envelope.md`
- `docs/DURABLE_MEMORY_AND_RECALL/ACTIVATE_GUARDED_RECALL.md`

## Related GitHub Issues

Create after PROVISIONAL-MEMORY-02 merges. TCD hint: Sol/high due to retrieval/context authority and
production consumer enforcement.

