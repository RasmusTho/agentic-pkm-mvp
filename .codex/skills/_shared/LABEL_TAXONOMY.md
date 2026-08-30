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
| `type:epic` | parent delivery or validation hub |
| `type:feature` | parent feature or validation hub |
| `prio:high` | blocks other work or has active regression |
| `prio:med` | normal delivery priority |
| `prio:low` | nice-to-have, no urgency |
| `agent:ready` | bounded, testable, unblocked, and strictly validated — safe for agent pickup without requiring Project Status |
| `agent:blocked` | dependency unresolved, including parent validation hubs waiting on child slices |
| `agent:needs-human` | requires a named human decision, tradeoff, missing input, or authority question |
| `action:repair-contract` | blocked: next action is truthful contract/maintenance repair, not an inferred cause |
| `action:wait-dependency` | blocked: wait for named dependency evidence |
| `action:restore-environment` | blocked: restore a named local/host/service environment |
| `action:wait-external` | blocked: wait for a named external system or party |
| `action:review-at` | blocked: re-evaluate at a named review trigger |
| `action:human-decision` | needs human: owner decision required |
| `action:human-authorization` | needs human: authorization required |
| `action:human-access` | needs human: access grant or credential action required |
| `action:human-operation` | needs human: operator action required |
| `action:human-acceptance` | needs human: acceptance observation required |
| `agent:in-progress` | active implementation work under a current claim or delivery handoff |
| `state:known-defect` | rolling registry Issue containing confirmed deferred P2 defect entries; never an implementation pickup label |

Rules:

- Every new implementation Issue leaves creation with exactly one truthful agent-state label.
- A successful pickup atomically normalizes `agent:*` labels to exactly `agent:in-progress`, preserving
  every non-agent label; this is the authoritative active-claim transition.
- `agent:blocked` and `agent:needs-human` belong on non-active work. When Project repair is in
  scope, non-parent `agent:blocked` projects to `Blocked` and non-parent `agent:needs-human`
  projects to `Needs Human`; durable epic/parent evidence projects to `Epic / Parent` first.
  An existing explicit open-Issue `Review` projection is retained. None of these projections
  controls pickup.
- Closed or delivered Issues must not retain any `agent:*` label.
- An open `agent:blocked` Issue carries exactly one `action:repair-contract`,
  `action:wait-dependency`, `action:restore-environment`, `action:wait-external`, or
  `action:review-at` label. An open `agent:needs-human` Issue carries exactly one
  `action:human-*` label. Other and terminal states carry no `action:*` label.
- The durable comment receipt is `blocker_action.v1` with `action`, `owner`,
  `next_action`, `unblocks_when`, `dependency_refs`, optional `review_at`, and
  `last_verified_at`. Labels route; the receipt names the evidence and never grants a claim.
- `state:known-defect` belongs only on the locked rolling Known Defects registry Issue. That
  container also carries `type:bug`, is not an implementation Issue, carries no `agent:*` label,
  remains in `Backlog` if projected, and must never carry `agent:ready`. During explicit Project
  reconciliation, the open registry derives `Backlog` before the generic unmapped-issue fallthrough.
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
