State: Shared skill contract. Canonical label taxonomy for the delivery control plane.

# Label Taxonomy

Single source for the canonical label set. Skills reference this file instead of carrying their
own copies.

## Canonical labels

| Label | When |
|-------|------|
| `type:task` | default for bounded implementation or maintenance work |
| `type:bug` | confirmed defect or regression |
| `type:refactor` | code structure change with no behavior change |
| `prio:high` | blocks other work or has active regression |
| `prio:med` | normal delivery priority |
| `prio:low` | nice-to-have, no urgency |
| `agent:ready` | bounded, testable, unblocked, and strictly validated — safe for agent pickup without requiring Project Status |
| `agent:blocked` | dependency unresolved, including parent validation hubs waiting on child slices |
| `agent:needs-human` | requires a named human decision, tradeoff, missing input, or authority question |
| `state:known-defect` | rolling registry Issue containing confirmed deferred P2 defect entries; never an implementation pickup label |

Rules:

- Every new implementation Issue leaves creation with exactly one truthful agent-state label.
- `agent:blocked` and `agent:needs-human` belong on non-active work. A Project may mirror them as
  `Backlog`, but that projection does not control pickup.
- Closed or delivered Issues must not retain any `agent:*` label.
- `state:known-defect` belongs only on the locked rolling Known Defects registry Issue. That
  container also carries `type:bug`, is not an implementation Issue, carries no `agent:*` label,
  remains in `Backlog` if projected, and must never carry `agent:ready`.
- Registry entries are schema-marked Issue comments, not labels or child Issues. When an entry is
  selected for implementation, create/link a normal bounded `type:bug` Issue with exactly one
  priority, exactly one truthful normal agent state, the canonical contract, ACs, and `Verify:`
  targets. Do not copy `state:known-defect` to the implementation Issue.

## Narrow label exceptions

`lane:governance` is the lane exception: add it (in addition to the canonical delivery labels) when
the item belongs to the governance lane, so the governance Project filter and the relaxed
governance verification routing stay aligned with `AGENTS.md` and
`docs/development/DELIVERY_FEEDBACK_LOOP.md`.

`state:known-defect` is the only non-lane state exception. It identifies the registry container and
is never a substitute for a normal implementation Issue's agent state.

Labels outside this taxonomy and these two exceptions (for example `governance`, `ci`,
`maintenance`) are non-canonical and should be normalized away.
