---
name: docs-to-issue
description: "Convert governing docs into a bounded GitHub Issue contract for this repository without skipping source anchors, constraints, or validation."
---

# Docs To Issue

Use this skill when turning repo docs into a GitHub Issue for implementation work in this repository.

## Required posture

- Read `AGENTS.md` first.
- Identify the owning docs via `docs/DOCS_INDEX.md`.
- Treat GitHub Issues as the canonical implementation contract.
- Do not start non-trivial edits until the Issue exists and is ready.

## Workflow

1. Find the most local governing doc items for the change.
2. Create or tighten a bounded Issue with `Context`, `Scope`, `Source Anchors`, `Constraints`, `Acceptance Criteria`, `Out of Scope`, `Suggested Validation`, and `Source Docs`.
3. Prefer stable anchor IDs when they exist; otherwise use the most local durable section text that the repo validator can resolve.
4. Keep the Issue small enough that one PR can satisfy it without hidden follow-up work.
5. Label and link the work so it can move through the normal `Issue -> PR -> CI` flow.

## Guardrails

- Do not invent backlog work without source anchors.
- Do not widen scope beyond what the owning docs justify.
- Do not treat chat-only instructions as the canonical task contract when an Issue is expected.
