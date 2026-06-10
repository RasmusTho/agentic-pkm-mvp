State: Shared skill contract. Canonical lifecycle truth matrix for Issues and PRs.

# Lifecycle Truth Matrix

Single source for the required Project Status of every Issue and PR content state. Every other
cell is drift and must be corrected. Skills reference this file instead of carrying their own
copies; `issue-maintenance-change-control` owns the reconciliation procedure that applies it.

## Allowed Project statuses

`Backlog`, `Ready`, `In Progress`, `Review`, `Done`

## Matrix

| Content | Content state | Required Project Status |
|---------|---------------|-------------------------|
| Issue | CLOSED | `Done` |
| Issue | OPEN + `agent:ready` | `Ready` |
| Issue | OPEN + `agent:blocked` | `Backlog` |
| Issue | OPEN + `agent:needs-human` | `Backlog` |
| PR | MERGED | `Done` |
| PR | CLOSED (unmerged) | `Done` |
| PR | OPEN + Draft | `In Progress` |
| PR | OPEN + non-draft + review requested | `Review` |
| PR | OPEN + non-draft, no review requested | `In Progress` |
| Any | Present but no Project entry | Add to Project, apply row above |

## Review semantics

`Review` is the explicit review-handoff state, not a synonym for "a non-draft PR exists". Since
`publish-pr` defaults to opening non-draft PRs, an open non-draft PR without a requested review is
still active implementation and belongs in `In Progress`. (Settled by #1806 — review-requested
semantics; do not reintroduce the non-draft-defaults-to-Review variant.)

## Binding rules

- `agent:ready ↔ Status=Ready` is a post-condition, not just a declarative rule: an open
  `agent:ready` Issue in any other status means the queue is lying about what is pickable.
- GitHub Issue state, agent labels, linked PR state, and merge/delivery reality outrank Project
  state when they disagree; correct the projection to match the harder truth.
