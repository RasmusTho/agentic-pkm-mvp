---
name: backlog-reconciliation-drift-audit
description: "Audit drift between governing docs, GitHub backlog state, and delivered reality so repo work stays issue-first and source-anchor based."
---

# Backlog Reconciliation Drift Audit

Use this skill when reconciling docs, Issues, PRs, and shipped state in this repository.

## Required posture

- Read `AGENTS.md`, `docs/development/DEV_WORKFLOW.md`, and the relevant owner docs first.
- Treat GitHub Issue plus Project state as the canonical backlog receipt.
- Treat owner docs as the canonical shipped-reality writeback surface.

## Workflow

1. Compare active docs with open Issues and recent PRs.
2. Look for missing source anchors, stale pending wording, scope drift, or delivered work that was not written back to owner docs.
3. Prefer opening or tightening bounded Issues instead of leaving vague backlog notes in docs.
4. When work is already shipped, update owner docs so they describe reality instead of pending intent.
5. Keep any audit output specific enough that a later Issue can be created without rediscovery.

## Guardrails

- Do not treat inline `Tracked by` markers as the primary backlog system.
- Do not create duplicate backlog work when an anchor already has an Issue.
- Do not move runtime/system-agent semantics into builder-agent governance docs.
