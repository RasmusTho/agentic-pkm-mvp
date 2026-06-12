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
| `agent:ready` | bounded, testable, unblocked — safe for agent execution; use only with `Status=Ready` |
| `agent:blocked` | dependency unresolved, including parent validation hubs waiting on child slices |
| `agent:needs-human` | requires a named human decision, tradeoff, missing input, or authority question |

Rules:

- Every new implementation Issue leaves creation with exactly one truthful agent-state label.
- `agent:blocked` and `agent:needs-human` belong on non-active work, normally with
  `Status=Backlog`.
- Closed or delivered Issues must not retain any `agent:*` label.

## Governance-lane exception

`lane:governance` is the one label allowed beyond the delivery-control-plane set: add it (in
addition to the canonical labels) when the item belongs to the governance lane, so the governance
Project filter and the relaxed governance verification routing stay aligned with `AGENTS.md` and
`docs/development/DELIVERY_FEEDBACK_LOOP.md`.

Labels outside this taxonomy (for example `governance`, `ci`, `maintenance`) are non-canonical and
should be normalized away.
