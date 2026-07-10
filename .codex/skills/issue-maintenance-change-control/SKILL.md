---
name: issue-maintenance-change-control
description: "Keep GitHub Issues, PRs, labels, and Builder Ops Vault state truthful when backlog state drifts from repo reality, including high-risk change-control moves across Core Runtime <-> Agentic Lab."
---

# Issue Maintenance: Change Control

This is a cold-path maintenance skill for restoring truthful contracts and operational state. The
Builder Ops Vault is the active queue when a matching ticket exists; GitHub Issues and PRs are the
external traceability trail. GitHub Project v2 is a deprecated read-only projection.

All changes must use explicit, verified commands. Use REST `gh api` for GitHub label, issue, PR,
and comment mutations. Do not use `gh api graphql`, `gh project`, or Project-v2 mutations.

## Use this skill when

- an Issue is stale, malformed, duplicated, too large, partially delivered, or falsely ready;
- a Vault ticket, Issue label, linked PR, or merged delivery state disagrees;
- owner-doc writeback or roadmap cleanup is missing after delivery;
- a bounded maintenance audit is required across related items; or
- the work changes the Core Runtime <-> Agentic Lab boundary or operator-facing defaults.

## Authority and invariants

- Read `AGENTS.md`, `docs/DOCS_INDEX.md`, and `.codex/skills/_shared/LIFECYCLE_TRUTH_MATRIX.md`.
- GitHub Issue is the canonical external task contract. Product code and owner docs remain repo
  authority. Vault records never mutate product/runtime truth.
- When a matching Vault ticket exists, validate it before changing queue state:
  `python3 -m app.builderops builderops vault validate "$BUILDEROPS_VAULT_ROOT" --json`.
- For an executable Vault-backed Issue, `Ready` with no active claim plus `agent:ready` is the
  transition-ready state. Claim first, then remove `agent:ready` through REST. If REST fails,
  release the Vault claim.
- Without a ticket, use the dispatcher/GitHub-label fallback in `AGENTS.md`; never acquire a
  dispatcher lease for a Vault-backed ticket.
- Closed Issues must have no `agent:*` labels. Do not treat a Project card, projection, or receipt
  as closure proof.

Before adding or preserving `agent:ready`, validate the exact Issue body:

```bash
python3 scripts/validate_issue_readiness.py --body-file <body-file> --label agent:ready
```

## Change-control checklist

For Core Runtime <-> Agentic Lab moves, require direction, exact paths/modules, default-posture
impact, operator-contract impact, governing source anchors, and a boundary regression test plan.
Classify all work as Product/Runtime, Builder System, or boundary work using
`docs/architecture/SBS_OPERATING_MODEL.md`. Escalate only for a named human decision, missing input,
or authority question.

## Maintenance procedure

1. Read the Issue, linked PRs, recent receipts/comments, source anchors, and relevant owner docs.
2. Validate any matching Vault and inspect its folder/YAML status plus active claim. Identify whether
   the Issue is a parent validation hub or an executable child slice.
3. Correct the Issue contract: preserve Source Anchors; make scope bounded; add resolvable `Verify:`
   targets; split oversized work; close duplicates or delivered work with a receipt comment.
4. Correct labels through REST from delivery truth. Remove `agent:ready` for blocked, active, or
   delivered work. Use `agent:blocked` for dependencies and `agent:needs-human` only for a real
   human authority decision.
5. For Vault-backed work, use `builderops vault move`, `note`, or `release` with the correct active
   owner. `Backlog`, `Ready`, `Blocked`, and `Done` release claims; `Review` is a deliberate handoff.
6. Close an Issue only when merged/repo-verifiable delivery satisfies its contract; then remove all
   `agent:*` labels and record the canonical PR/commit in a comment.
7. Route unresolved operational observations to BuilderOps, a bounded issue with `Verify:` targets,
   or an explicit discard/supersession receipt.

## Fast maintenance audit

List open Issues and linked PRs with REST endpoints. For each, report exactly one result:
`create issue`, `update issue`, `split issue`, `close issue`, `relabel issue`, `update vault ticket`,
`update owner doc`, `rewrite roadmap/plan wording`, `create follow-up issue`, or `escalate human decision`.

Do not scan, add, or mutate GitHub Project v2. It is neither a prerequisite nor evidence that the
queue is healthy.

## Output

1. Summary for the human
2. Issue/PR/Vault truth assessment
3. Executed corrections and REST/Vault receipts
4. Remaining bounded follow-ups or human decisions
