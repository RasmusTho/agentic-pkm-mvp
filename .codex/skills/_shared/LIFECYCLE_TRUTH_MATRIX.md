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
| PR | OPEN + non-draft, no review requested | `Review` |
| Any | Present but no Project entry | Add to Project, apply row above |

## Review semantics

`Review` is the Project handoff state for open non-draft PRs. The shipped Project automation maps
`opened`, `reopened`, and `ready_for_review` non-draft PR events to `Review`; draft PRs remain
`In Progress` until they are marked ready. Maintenance runs must not treat a normal open non-draft
PR card in `Review` as drift.

## Binding rules

- `agent:ready ↔ Status=Ready` is a post-condition, not just a declarative rule: an open
  `agent:ready` Issue in any other status means the queue is lying about what is pickable.
- GitHub Issue state, agent labels, linked PR state, and merge/delivery reality outrank Project
  state when they disagree; correct the projection to match the harder truth.
