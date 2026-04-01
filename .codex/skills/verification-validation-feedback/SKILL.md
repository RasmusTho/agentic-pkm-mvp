---
name: verification-validation-feedback
description: "Run issue-appropriate validation, compare it to repo CI expectations, and report residual risk or gaps without overstating confidence."
---

# Verification Validation Feedback

Use this skill after implementing a bounded change in this repository.

## Required posture

- Read `AGENTS.md` and `docs/development/DEV_WORKFLOW.md` first.
- Match validation breadth to the touched area.
- Treat CI expectations as the compatibility baseline, not as optional suggestions.

## Workflow

1. Start with the Issue's `Suggested Validation`.
2. Add any repo baseline checks required by `docs/development/DEV_WORKFLOW.md` when the change type warrants them.
3. Prefer lightweight checks for docs-only work and broader suites for code or runtime contract changes.
4. Record what was run, what passed, what failed, and what was intentionally not run.
5. Call out residual risk plainly when validation is narrower than full CI.

## Guardrails

- Do not claim CI compatibility without running relevant local checks or explicitly stating the gap.
- Do not omit failures or blockers.
- Do not widen the task by fixing unrelated validation noise unless the Issue contract is updated first.
