State: Shared skill contract. Canonical lifecycle truth matrix for Issues and PRs.

# Lifecycle Truth Matrix

Single source for the optional legacy Project projection of Issue and PR content state. Project
presence or Status never gates issue readiness, pickup, or claim. Review, merge, closure, and
optional projection-repair behavior remain owned by their downstream skills. Skills reference this
file instead of carrying their own copies; `issue-maintenance-change-control` owns optional
reconciliation.

## Allowed Project statuses

`Backlog`, `Ready`, `In Progress`, `Review`, `Done`

## Matrix

| Content | Content state | Projected Status |
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

- `agent:ready` is the pickup qualifier after strict validation. `Status=Ready` is its preferred
  legacy board projection, not a precondition or collision guard.
- GitHub Issue state, agent labels, linked PR state, and merge/delivery reality outrank Project
  state when they disagree; correct the projection to match the harder truth.
