---
name: issue-to-code
description: "Implement a bounded GitHub Issue in this repository while staying inside issue scope, owner-doc rules, and PR linkage requirements."
---

# Issue To Code

Use this skill when implementing an existing GitHub Issue in this repository.

## Required posture

- Read `AGENTS.md` first.
- Read the full governing Issue before editing.
- Treat `Context`, `Scope`, `Source Anchors`, `Constraints`, `Acceptance Criteria`, `Out of Scope`, `Suggested Validation`, and `Source Docs` as binding.

## Workflow

1. Confirm the Issue is the active task contract and is labeled `agent:ready` when that rule applies.
2. Read the owner docs named by the Issue before changing code or nearby docs.
3. Implement the smallest change that satisfies the Issue.
4. Update owner docs in the same change when shipped behavior or workflow guidance changes.
5. Open a PR that links the Issue with `Fixes #<id>`, `Closes #<id>`, or `Resolves #<id>`.

## Guardrails

- Do not expand scope silently.
- Do not add files outside the Issue contract.
- Do not turn repo-local skills into canonical policy surfaces.
- Keep the change minimal and reversible where possible.
