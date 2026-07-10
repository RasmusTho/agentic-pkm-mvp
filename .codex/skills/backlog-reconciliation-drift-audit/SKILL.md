---
name: backlog-reconciliation-drift-audit
description: "Periodically reconcile docs, Issues, PRs, Builder Ops Vault tickets, and owner docs so backlog truth stays stable over time."
---

# Backlog Reconciliation Drift Audit

Audit the durable and operational sources of truth: docs, GitHub Issues/PRs, Builder Ops Vault
tickets and claims, and owner docs. GitHub Project v2 is a deprecated optional projection and is
not audited or mutated in the Builder System hot path.

## Audit chain

`Docs <-> Issues <-> Vault tickets/claims <-> PRs <-> Owner Docs`

Look for stale or duplicate Issues, missing source anchors or `Verify:` markers, falsely ready
work, expired or conflicting Vault claims, delivered-but-open Issues, missing owner-doc writeback,
and roadmap text that still calls delivered work pending.

## Rules

- GitHub Issues are the external task contract; Vault is active delivery truth when its ticket
  exists; the repository is code and owner-doc truth.
- Use REST `gh api` for GitHub reads and mutations. Never use GraphQL, `gh project`, or Project-v2
  field mutations for this workflow.
- Validate Vaults with `builderops vault validate` before acting on status or claim drift.
- `agent:ready` requires strict readiness validation and a matching unclaimed `Ready` ticket when
  Vault-backed. Do not use an absent Project card as evidence of drift.
- Close delivered Issues only after a PR/commit and acceptance evidence are repo-verifiable; remove
  all `agent:*` labels on closure.

## Procedure

1. Read owner docs and scoped roadmap/plan sections.
2. List open Issues and relevant PRs through REST; inspect bodies, labels, comments, links, and
   delivery evidence.
3. Validate the Vault and inspect every scoped ticket's folder, YAML status, and claim TTL.
4. Compare all four surfaces and choose one corrective action per drift class.
5. Make only explicit, verified corrections: issue body/labels/comments, Vault operations, owner-doc
   writeback, bounded follow-up issues, or documented escalation.
6. Emit a receipt with before/after counts and every action.

## Output

- Backlog truth summary
- Drift findings by source surface
- Corrective actions and verification evidence
- Remaining bounded work or human decisions
