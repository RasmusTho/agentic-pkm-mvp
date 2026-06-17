---
name: Agent Workflow Integration
description: Wire dispatcher claim/heartbeat/complete into issue-to-code skill execution and verify adoption
task_id: DISPATCHER-ADOPTION-04
source_anchor: docs/DISPATCHER_AGENT_ADOPTION/AGENT_WORKFLOW_INTEGRATION.md
parent_capability: Dispatcher Agent Adoption
prerequisites: [DISPATCHER-ADOPTION-01, DISPATCHER-ADOPTION-02, DISPATCHER-ADOPTION-03]
depends_on: [BOOTSTRAP_AND_SYNC_WIRING.md, COMPLETE_COMMAND.md, FALLBACK_POLICY.md]
can_parallelize_with: []
---

# Agent Workflow Integration

## Purpose

After the policy is written (FALLBACK_POLICY task) and the commands exist (BOOTSTRAP_AND_SYNC_WIRING + COMPLETE_COMMAND tasks), this task verifies that agents following `issue-to-code` actually call the dispatcher in practice. It also adds an architecture test that enforces the dispatcher step order so the skill cannot silently drift back to label-only pickup.

This is the final adoption gate. It is explicitly evidence-based: "agents are using the dispatcher" cannot be proven by a unit test, so the acceptance path requires observed delivery receipts.

## What This Task Does

1. Adds `tests/architecture/test_dispatcher_skill_integration.py` — a lightweight static check that `issue-to-code/SKILL.md` references the required dispatcher steps (`dispatcher status`, `dispatcher next`, `dispatcher claim`, `dispatcher heartbeat`, `dispatcher complete`) in the correct order.
2. Adds `tests/dispatcher/test_agent_loop.py` — an integration test that exercises the full agent loop (status check → next → claim → heartbeat → complete) against a temporary in-process dispatcher store, asserting event audit trail is correct.
3. Records adoption evidence: after the first three issue-to-code deliveries post-merge, operator logs a short receipt on the parent feature issue confirming dispatcher was called (or fallback was used and why).

No changes to `AGENTS.md` or `issue-to-code/SKILL.md` beyond what FALLBACK_POLICY already wrote — this task only adds the test layer and adoption evidence.

## Concretely

```sh
# architecture test — verifies skill doc has correct dispatcher steps
pytest tests/architecture/test_dispatcher_skill_integration.py -v
# => test_skill_references_dispatcher_status PASSED
# => test_skill_references_dispatcher_next PASSED
# => test_skill_references_dispatcher_claim PASSED
# => test_skill_references_dispatcher_heartbeat PASSED
# => test_skill_references_dispatcher_complete PASSED
# => test_skill_dispatcher_steps_in_order PASSED

# integration test — full agent loop against temp store
pytest tests/dispatcher/test_agent_loop.py -v
# => test_full_agent_loop_status_next_claim_heartbeat_complete PASSED
# => test_full_agent_loop_fallback_event_trail PASSED
```

Adoption receipt format (posted on parent feature issue after each delivery):

```
Dispatcher adoption receipt — delivery N
- Issue: #<number>
- Agent: <worktree/agent-id>
- Dispatcher used: yes / no (fallback: <reason>)
- Dispatcher events: task.claimed, task.heartbeat (N times), task.completed
- Notes: <any anomaly>
```

## Why This Matters

Without a static architecture test, the skill doc can drift. A developer updating the skill removes the dispatcher subsection and no test catches it. The integration test gives confidence the full loop works end-to-end in isolation. The adoption receipts give confidence agents are actually hitting the dispatcher, not just passing tests.

## Acceptance Criteria

- [ ] `tests/architecture/test_dispatcher_skill_integration.py` exists and asserts all five dispatcher step references present in `issue-to-code/SKILL.md` in correct order.
  Verify: `tests/architecture/test_dispatcher_skill_integration.py::test_skill_dispatcher_steps_in_order`
- [ ] `tests/dispatcher/test_agent_loop.py` exercises the full claim → heartbeat → complete loop against a temp store and asserts the event audit trail contains `task.claimed`, `task.heartbeat`, `task.completed` in order.
  Verify: `tests/dispatcher/test_agent_loop.py::test_full_agent_loop_status_next_claim_heartbeat_complete`
- [ ] All dispatcher tests pass.
  Verify: `pytest -q tests/dispatcher/ tests/architecture/test_dispatcher_skill_integration.py`
- [ ] Three adoption receipts posted on the parent feature issue (operator closes adoption gate).
  Verify: adoption evidence on parent feature issue body or comments

## How to Verify (Pre-Merge)

```sh
pytest -q tests/dispatcher/ tests/architecture/test_dispatcher_skill_integration.py
ruff check tests/dispatcher/test_agent_loop.py tests/architecture/test_dispatcher_skill_integration.py
mypy tests/dispatcher/test_agent_loop.py
```

## Out of Scope

- Changing the pickup policy to dispatcher-only (removing GitHub fallback) — adoption shadow mode is the MVP target.
- Adding dispatcher metrics or dashboards.
- Multi-worktree concurrency testing.

## Related Docs

- `docs/AGENT_ISSUE_DISPATCHER.md :: Agent Interaction Contract` — the loop this task tests
- `.codex/skills/issue-to-code/SKILL.md :: dispatcher-integration` — written by FALLBACK_POLICY task
- `tests/architecture/` — existing architecture-enforcement test directory

## Related GitHub Issues

One issue. Adds two test files. Adoption evidence is recorded by operator post-merge on the parent feature issue, not by the agent in this PR.
