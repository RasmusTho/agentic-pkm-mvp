---
name: issue-maintenance-change-control
description: "Maintain issue fidelity during implementation by handling blockers, drift, and scope pressure without bypassing repo governance."
---

# Issue Maintenance Change Control

Use this skill when a governing Issue becomes stale, ambiguous, blocked, or too broad during execution.

## Required posture

- Read `AGENTS.md` first.
- Keep the GitHub Issue as the canonical task contract.
- Prefer contract updates over silent scope changes.

## Workflow

1. Compare the requested work to the active Issue scope and acceptance criteria.
2. If the needed change no longer fits, stop and tighten the contract before continuing.
3. If the work is blocked, capture the blocker in Issue/PR context instead of improvising around governance.
4. Keep follow-up work split into new bounded backlog items when it cannot be completed inside the active Issue.
5. Preserve doc writeback when shipped reality changes.

## Guardrails

- Do not smuggle follow-up work into the active PR.
- Do not treat roadmap intent as permission to skip Issue maintenance.
- Do not rewrite canonical policy in `.codex/` compatibility surfaces.
