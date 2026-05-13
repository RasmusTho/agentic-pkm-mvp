---
name: Prevent Unreviewed Memory Authority
description: Specify the guard that stops unreviewed memory from authorizing writeback or overriding human truth.
task_id: AGENT-MEMORY-05
source_anchor: docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Authority rules
parent_capability: Agent Memory
prerequisites: [AGENT-MEMORY-01, AGENT-MEMORY-02, AGENT-MEMORY-03, AGENT-MEMORY-04]
depends_on: [DEFINE_MEMORY_CANDIDATE_MODEL.md, ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md, PROMOTE_REJECT_AND_REVISE_MEMORY.md, EXPLAIN_MEMORY_RECALL.md]
can_parallelize_with: []
---

# PREVENT_UNREVIEWED_MEMORY_AUTHORITY

## Purpose

Specify the authority guard that prevents unreviewed, inferred, or contradicted memory from
authorizing writeback or overriding human-authored knowledge.

## What This Task Does

This task defines the implementation contract for memory authority boundaries. It specifies:

- which memory states may support suggestion only,
- which reviewed states may support stronger recall,
- and which states remain forbidden from write-authority escalation.

## Concretely

A later implementation should be able to enforce rules such as:

- unreviewed or inferred memory may be shown with labels but cannot authorize apply,
- promoted memory still cannot override human-authored artifacts or contracts,
- contradicted or stale memory must surface its posture before reuse,
- and writeback flows must treat memory as supporting input rather than authority source.

## Why This Matters

The concept contract is explicit that agent memory must not become a hidden source of truth. This
task is the implementation guardrail for that rule. Without it, memory recall can become an
unreviewed shortcut around provenance, contracts, and human authority.

## Acceptance Criteria

- [ ] The implementation spec forbids unreviewed memory from authorizing writeback or governed
  apply flows. Verify: `tests/agent_memory/test_memory_authority_guard.py::test_unreviewed_memory_cannot_authorize_writeback`
- [ ] The implementation spec preserves human-authored artifacts and explicit contracts as stronger
  authority than recalled memory. Verify: `tests/agent_memory/test_memory_authority_guard.py::test_memory_cannot_override_human_authored_truth`
- [ ] The implementation spec requires stale, contradicted, or inferred memory to surface its
  posture before reuse. Verify: `tests/agent_memory/test_memory_authority_guard.py::test_memory_authority_guard_requires_posture_visibility`
- [ ] The implementation spec distinguishes memory-supported suggestion from memory-authorized
  mutation. Verify: `tests/agent_memory/test_memory_authority_guard.py::test_memory_supports_suggestion_without_escalating_to_mutation_authority`

## How to Verify (Pre-Merge)

- Add or update the authority-guard tests named in the acceptance criteria.
- Confirm the guard applies even when recalled memory is convenient or repeated often.
- Confirm the implementation path still points back to provenance and review state before any
  stronger action is allowed.

## Out of Scope

- Candidate-memory modeling.
- Review queue interaction details.
- Memory promotion mechanics.
- UI design for memory review or recall.

## Related Docs

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md`
- `docs/AGENT_MEMORY/EXPLAIN_MEMORY_RECALL.md`

## Related GitHub Issues

Not created in this PR. When filed later, use this task spec as the child implementation issue
contract for memory authority guards.
