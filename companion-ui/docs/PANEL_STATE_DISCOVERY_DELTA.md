---
name: Panel State Discovery Delta
description: Gap analysis for Panel browser state discovery against the workspace aggregate contract
doc_role: Gap analysis / implementation gate
authority: Binding delta for whether Panel browser integration needs a separate discovery contract.
owner: Companion UI / Panel integration
last_reviewed: 2026-05-19
source_contracts:
  - companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md
  - companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md
  - companion-ui/docs/PANEL_DURABLE_PROJECTION_MAPPING.md
  - companion-ui/docs/WORKSPACE_STATE_CONTRACT.md
governing_issue: "#1127"
---

# Panel State Discovery Delta

## Sufficiency Statement

The workspace aggregate is sufficient for the current Panel browser discovery
slice. No separate Panel state discovery endpoint is needed.

`GET /api/companion/workspace` is the read-side browser discovery mechanism for
artifact-local Panel state. `POST /api/panel/confirm` remains the write-side
confirmation path.

## Existing Contract Coverage

| Question | Answer |
|---|---|
| How does the browser discover staged proposals on cold load? | It reads `panel.state` and `panel.proposal_count` from `GET /api/companion/workspace?note_path=...`. If `panel.state = "proposals-staged"` and `proposal_count > 0`, the browser renders the Panel proposal affordance for that artifact. |
| How does the browser discover receipts for a given note? | It reads `panel.receipt_count` and `panel.latest_receipt_outcome`. `panel.state` tells the browser whether a receipt should be displayed; `latest_receipt_outcome` distinguishes success, blocked, logged/deferred, partial, and rejected outcomes. The durable vault-visible receipt mapping remains governed by `PANEL_DURABLE_PROJECTION_MAPPING.md`. |
| Is polling, SSE, or explicit refresh the right model? | Explicit refresh and load-time aggregation are sufficient for the current slice. Polling or SSE is not required until there is a concrete live-update UX issue. |
| What does blocked/no-match state look like? | `panel.state = "blocked"` carries `blocked_reason`; `panel.state = "no-match"` carries `no_match_reason`. Both are defined by `WORKSPACE_STATE_CONTRACT.md` and rendered as visible Panel states, not silent failures. |

## Cold Load Discovery

When a note is opened, the browser calls:

```http
GET /api/companion/workspace?note_path=<relative_path>
```

The browser uses only the `panel` slice for Panel discovery:

```json
{
  "panel": {
    "state": "proposals-staged",
    "proposal_count": 2,
    "receipt_count": 0,
    "latest_receipt_outcome": null,
    "blocked_reason": null,
    "no_match_reason": null
  }
}
```

Rules:

- The browser does not scan vault text for Panel checkboxes.
- The browser does not re-run Panel cognition on cold load.
- The browser does not infer proposal classes locally.
- The browser renders server-declared Panel state for the active artifact only.

## Receipt Discovery

Receipt discovery is aggregate-level for this slice:

- `receipt_count` tells the browser whether there are current receipt/outcome
  items relevant to the active artifact.
- `panel.state = "receipt-displayed"` tells the browser the primary render
  state.
- `latest_receipt_outcome` tells the browser what happened: `success`,
  `blocked`, `logged`, `partial`, or `rejected`.
- Blocked/logged/partial outcomes remain governed by
  `PANEL_CONFIRMATION_API_CONTRACT.md` and
  `PANEL_DURABLE_PROJECTION_MAPPING.md`.

This delta does not introduce a new receipt list schema. If the browser later
needs full receipt rows on cold load, that is an additive extension to
`WORKSPACE_STATE_CONTRACT.md`, not a separate discovery endpoint. Until then,
`latest_receipt_outcome` is the required field that prevents the browser from
misrepresenting a logged/deferred or blocked receipt as a successful execution.

## Update Model

The current update model is explicit refresh:

- Initial note open calls the workspace aggregate.
- After `POST /api/panel/confirm`, the browser refreshes workspace state.
- Manual refresh or note navigation refreshes workspace state.

Polling and SSE are out of scope for this delta. They can be introduced later
only if the product requires live Panel updates while the user remains on the
same note.

## Additive Gaps

No additive fields are required for the current Panel browser integration
slice.

Future additive fields may be justified if implementation needs:

- full proposal row summaries on cold load,
- full receipt row summaries on cold load,
- proposal validity/expiry windows,
- live update cursors,
- or per-proposal blocked reasons.

Those additions should extend the `panel` slice in
`WORKSPACE_STATE_CONTRACT.md` rather than creating a second Panel discovery
contract.
