---
name: bug-to-issue
description: "Create a GitHub Issue whenever a bug is discovered during analysis, testing, review, or runtime observation. Use when Codex identifies a defect, regression, crash, or contract mismatch and needs to open a compliant issue in the target repo with correct labels, body sections, and ready/needs-human status."
---

# Bug To Issue

## Overview

Turn any discovered bug into a compliant GitHub Issue that matches the repo's contract shape and labels. Default to creating issues in the current repo unless the user specifies a different one.
This is the hot-path defect intake lane, not the cold-path maintenance lane.

## Workflow

1. Resolve repo:
   - If repo specified, use it.
   - If not, infer from current git remote; if still unknown, ask for `owner/repo`.
2. Check for existing issue:
   - Search open issues for the same symptom/title. If a matching issue exists, comment with new evidence instead of creating a duplicate.
3. Create or update Issue body:
   - Always use the required contract sections:
     - `## Context`
     - `## Scope`
     - `## Source Anchors`
     - `## Constraints`
     - `## Acceptance Criteria`
     - `## Out of Scope`
     - `## Suggested Validation`
     - `## Source Docs`
   - Include exact repro steps and observed/expected results when available.
   - Do not create a micro-issue for routine repair, reconciliation, or bookkeeping churn; route those signals to the maintenance skills instead.
   - Acceptance Criteria must carry `Verify:` markers:
     - The primary behavioral AC ("bug no longer reproduces") points to a regression test the fix will add: `Verify: \`tests/<path>::test_<bug_name>\`` — the test should fail against current code and go green after the fix.
     - Any non-behavioral AC (doc clarifications, roadmap/status wording) points to its observable target.
     - If the bug cannot yet be expressed as a failing test (e.g., the repro is environment-dependent or requires instrumentation that does not exist), mark `agent:needs-human` rather than `agent:ready`.
4. Labels:
   - Always add `type:bug`.
   - Add one priority: `prio:high`, `prio:med`, or `prio:low` based on impact.
   - Add `agent:ready` only if the scope is bounded, testable, and unblocked.
   - Otherwise add `agent:needs-human` or `agent:blocked`.
5. Project:
   - Add the new Issue to Project `Agent Delivery Control Plane`.
   - Set Status to match the agent-state label: `agent:ready` → `Ready`; otherwise (`agent:blocked`, `agent:needs-human`) → `Backlog`.
6. Output receipt: issue number, labels set, Project Status set, and whether it was created or updated.

## Heuristics for `agent:ready`

Set `agent:ready` when all are true:
- Concrete scope and acceptance criteria are present.
- Every AC carries a resolvable `Verify:` target; the repro is expressible as a named failing test.
- Source anchors point to specific files or docs.
- No unresolved decisions or missing contract inputs.
- The bug is a real defect, not a low-signal maintenance correction that should be batched into audit or retrospective work.

Force `agent:needs-human` when:
- a named human decision, tradeoff, missing input, or authority question is required before work can proceed
- It is a Core Runtime ↔ Agentic Lab boundary move without explicit direction and module paths.
- The change would alter operator-facing defaults without explicit posture and validation plan.

## Capturing learning

**Capturing learning:** if during this work you notice a divergence from plan — you did something you did not expect to do, or discovered an earlier artifact was wrong — route it through `capture-learning`, which owns the invocation timing: invoke immediately only when the divergence needs upstream repair now; otherwise note the signal for `learning-retrospective`. Only log if you can name an upstream artifact that could absorb the fix.
