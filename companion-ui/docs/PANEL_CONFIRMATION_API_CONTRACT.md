---
name: Panel Confirmation Endpoint API Contract
description: API contract for the runtime-mediated Panel confirmation endpoint — request/response schema, idempotency, blocked/receipt semantics, and boundary rules
doc_role: API contract / spec
authority: Binding contract for any implementation of the Panel confirmation endpoint. Must not be bypassed or extended without a governing issue.
owner: v6.0 architecture / Panel runtime implementation lane
last_reviewed: 2026-05-17
governing_issues: "#1042"
related_issues: "#1039, #1040, #1041, #1043, #1022, #995, #996"
source_contracts:
  - companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md
  - docs/PANEL_AGENT.md
  - docs/INTERACTION_SURFACES_AND_AUTHORITY/STATE_EXECUTION_AUTHORITY_REMAINS_GATED.md
  - docs/INTERACTION_SURFACES_AND_AUTHORITY/HYBRID_CHAT_INTEGRATION_SCHEMA.md
---

# Panel Confirmation Endpoint API Contract

## Purpose

Define the API contract for the runtime-mediated Panel confirmation endpoint.

This document is **spec/contract only**. It does not implement the endpoint,
does not add backend routes, and does not change event schemas. The
implementation belongs to a follow-up issue explicitly scoped to runtime
endpoint implementation.

---

## Background

`companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md :: Part 3` established:

- Direct Companion UI vault write-back is not viable. The UI must not write
  vault files directly.
- The preferred confirmation path is a dedicated runtime confirm endpoint
  (Approach 2 from the contract).
- Any confirmation path must produce a durable vault-visible projection
  identical to the CLI/watcher flow.
- Same-turn execution of newly generated proposals is NOT allowed unless the
  existing governed runtime explicitly supports it.

This document defines the endpoint contract so implementation can begin in a
separate issue.

---

## Endpoint

```
POST /api/panel/confirm
```

This endpoint is called by the Companion UI after the user has explicitly
performed a confirm action on a specific Panel proposal. It initiates governed
execution through the runtime pipeline: policy → WriteGuard → idempotency →
deterministic writer → receipt → event emission.

---

## Request Schema

```json
{
  "proposal_id": "<string — canonical action/intent ID>",
  "artifact_id": "<string — note identity, required>",
  "action":      "<string — 'confirm' | 'reject'>",
  "idempotency_key": "<string — client-generated UUID or equivalent>",
  "correction":  {
    "enabled": false,
    "corrected_action_id": null,
    "corrected_parameters": null
  }
}
```

### Field definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `proposal_id` | string | yes | Canonical proposal/intent ID as returned by the Panel runtime when proposals were staged. Used for runtime correlation. |
| `artifact_id` | string | yes | Note/artifact identity. Confirms that the proposal is artifact-local and disambiguates proposals when multiple notes are active. |
| `action` | enum | yes | `confirm` or `reject`. The user's explicit decision for this proposal. |
| `idempotency_key` | string | yes | Client-generated UUID (v4) or equivalent. The runtime must treat duplicate requests with the same key as idempotent — returning the same response without re-executing. |
| `correction.enabled` | bool | no | `true` if the user has corrected the proposal before confirming. Default: `false`. |
| `correction.corrected_action_id` | string or null | no | Overridden action ID if the user changed the action type. Null if only parameters changed. |
| `correction.corrected_parameters` | object or null | no | Overridden action parameters if the user adjusted them. Null if action ID was sufficient. |

### Constraints

- `proposal_id` and `artifact_id` must both be present and non-empty.
- `action` must be exactly `confirm` or `reject`. No other values are valid.
- `idempotency_key` must be a unique opaque string per confirmation attempt.
  Retry of a failed network request must use the **same** idempotency key.
  A new user-initiated confirm action must use a **new** idempotency key.
- Correction fields are optional. If `correction.enabled` is `true`,
  at least one of `corrected_action_id` or `corrected_parameters` must be
  non-null.
- The Companion UI must not call this endpoint in the same turn that a
  proposal was generated. Same-turn execution of newly generated proposals
  is not allowed.

---

## Response Schema

### Success (HTTP 200)

```json
{
  "proposal_id":   "<string>",
  "artifact_id":   "<string>",
  "status":        "<string — see Status Values>",
  "outcome":       "<string — see Outcome Values>",
  "receipt":       {
    "action_taken":  "<string>",
    "outcome":       "<string>",
    "timestamp":     "<ISO 8601>",
    "message":       "<string or null>",
    "inverse_action": "<string or null — identifier for the inverse/undo action>"
  },
  "idempotency_key": "<string — echoed from request>",
  "events_emitted":  ["<string>", ...]
}
```

### Blocked (HTTP 200 with blocked status, or HTTP 422)

```json
{
  "proposal_id": "<string>",
  "artifact_id": "<string>",
  "status":      "blocked",
  "outcome":     "blocked",
  "block_reason": {
    "gate":    "<string — policy | writeguard | allowlist | capability>",
    "message": "<string — human-readable reason>",
    "code":    "<string or null — machine-readable block code>"
  },
  "idempotency_key": "<string>"
}
```

### Error (HTTP 4xx / 5xx)

```json
{
  "error":   "<string — error class>",
  "message": "<string — human-readable error>",
  "proposal_id": "<string or null>",
  "idempotency_key": "<string or null>"
}
```

### Status Values

| Status | Description |
|---|---|
| `confirming` | Runtime received the request and is evaluating policy. |
| `executing` | Policy cleared; governed execution is in progress. |
| `executed` | Execution complete. Receipt is present. |
| `blocked` | Execution was blocked (policy, WriteGuard, allowlist, capability). |
| `rejected` | User action was `reject`; proposal declined with no execution. |
| `logged` | Action was logged for review rather than executed (policy outcome). |

### Outcome Values

| Outcome | Description |
|---|---|
| `success` | Governed execution completed; vault-visible projection written. |
| `blocked` | Execution denied at a policy gate. |
| `logged` | Action logged; deferral projection written. |
| `partial` | Some sub-actions succeeded, others blocked (if applicable). |
| `rejected` | User explicitly rejected the proposal. |

---

## Proposal/Intent ID Correlation

- The `proposal_id` in the confirm request must match the `proposal_id` /
  intent ID that the Panel runtime issued when it staged the proposal.
- The runtime must maintain a correlation table (or equivalent) mapping
  proposal IDs to their staged intent payloads for the duration of the
  proposal's validity window.
- If the `proposal_id` is unknown or expired, the endpoint must return a
  4xx error with an appropriate `error` field (`unknown_proposal` or
  `expired_proposal`).

---

## Idempotency Expectations

- The runtime must use the `idempotency_key` to detect duplicate confirm
  requests and return the original response without re-executing.
- Idempotency window: at minimum for the duration of the execution outcome
  visibility period (until the user navigates away or dismisses the receipt).
- If a confirmed proposal was already executed, a duplicate request with the
  same key must return the original receipt rather than failing or re-executing.
- The idempotency key is client-owned. The runtime must not generate it.

---

## Blocked and Error States

### Policy-blocked

A proposal may be blocked at policy evaluation (before WriteGuard). The
response must identify the gate (`policy`) and provide a human-readable reason.

### WriteGuard-blocked

A proposal may be blocked at the WriteGuard (allowlist violation, file lock,
or governance constraint). The response must identify the gate (`writeguard`).

### Allowlist-blocked

Execution denied because the action type or target is not in the current
capability allowlist. Gate: `allowlist`.

### Capability-blocked

The requested action requires a capability not currently available. Gate:
`capability`.

### Network/Runtime Error

HTTP 5xx errors indicate a runtime failure. The Companion UI must surface these
as transient errors and must not treat them as confirmed or rejected.

---

## Receipt Semantics

A receipt is a durable record of execution outcome. The receipt is:

- Included in the `receipt` field of the HTTP 200 success response.
- Written to the vault AI-status callout by the runtime as a durable
  vault-visible projection (see `PANEL_DURABLE_PROJECTION_MAPPING.md`).
- Not written by Companion UI. The UI renders the receipt from the response;
  the runtime writes the vault-visible version.

Receipt fields:

| Field | Description |
|---|---|
| `action_taken` | The canonical action ID that was executed. |
| `outcome` | `success`, `blocked`, `logged`, `partial`. |
| `timestamp` | ISO 8601 execution timestamp (UTC). |
| `message` | Human-readable outcome description. May be null. |
| `inverse_action` | Identifier for the inverse/undo action, if declared by the runtime. May be null. |

---

## Durable Vault-Visible Projection Requirement

The endpoint implementation must produce a durable vault-visible projection
equivalent to the CLI/watcher flow:

- Executed checkboxes removed from the panel working set.
- AI status callout (`> [!info]- AI status`) updated with the execution receipt.
- Event stream emissions as appropriate.
- Vault state remains readable/actionable in Obsidian without Companion UI
  being present.

See `companion-ui/docs/PANEL_DURABLE_PROJECTION_MAPPING.md` for the full
projection mapping.

---

## Same-Turn Execution Prohibition

The endpoint must not accept a confirm request for a proposal that was
generated in the same Companion UI interaction turn. Same-turn execution of
newly generated proposals is not allowed by this contract.

Enforcement mechanism (implementation recommendation):
- Include a `proposed_at` timestamp in the staged proposal payload.
- Reject requests where `proposed_at` is within the current interaction window.
- Alternatively, track a `generation_turn_id` and refuse confirms within the
  same turn ID.

---

## Direct Companion UI Vault Write-Back: Explicitly Rejected

The Companion UI must not write vault files directly. All vault mutations
(checkbox state, AI status callout, receipts) are written by the runtime
through the governed execution path.

The confirm endpoint is the signal — not the execution authority. Execution
authority remains with the runtime.

---

## Relation to Existing Panel Runtime Events/Receipts

The confirm endpoint must emit the following events on execution (names from
`docs/PANEL_AGENT.md` event inventory):

| Event | When |
|---|---|
| `panel.intent.executed` | Execution succeeded. |
| `panel.action.triggered` | Governed action was triggered. |
| `panel.action.logged` | Action was logged rather than executed. |
| `panel.action.blocked` | Execution was blocked at a gate. |

The response's `events_emitted` field must list the event names emitted for
this confirmation, so the Companion UI can correlate status.

---

## Policy, WriteGuard, Idempotency, and Receipts: Ownership Statement

The runtime owns:

- Policy evaluation.
- WriteGuard.
- Idempotency.
- Execution of the governed action.
- Receipts and inverse-action declaration.
- Durable vault-visible projection.
- Event emission.

The Companion UI owns:

- Displaying richer confirmation affordances.
- Submitting the named confirmation signal (the endpoint call).
- Rendering the `confirming → executing → receipt` state progression.
- Displaying the receipt after execution.

---

## Required Tests Before Implementation

The following tests must exist before or alongside endpoint implementation:

1. `test_panel_confirm_endpoint_returns_receipt_on_success` — confirm returns
   a valid receipt on successful execution.
2. `test_panel_confirm_endpoint_blocked_on_writeguard` — confirm returns a
   blocked response when WriteGuard denies the action.
3. `test_panel_confirm_endpoint_idempotent` — duplicate requests with the same
   `idempotency_key` return the same response without re-executing.
4. `test_panel_confirm_endpoint_rejects_unknown_proposal_id` — unknown
   `proposal_id` returns a 4xx error.
5. `test_panel_confirm_endpoint_reject_action_no_execution` — `action: reject`
   returns a rejected status with no vault mutation.
6. `test_panel_confirm_endpoint_produces_vault_projection` — execution writes
   the expected vault-visible receipt (integration test with vault stub or
   test vault).
7. `test_panel_confirm_endpoint_does_not_allow_same_turn_execution` — requests
   for same-turn proposals are rejected.

---

## Open Questions (Deferred to Implementation)

1. **Status feedback mechanism.** Is confirmation status delivered synchronously
   (single response) or asynchronously (polling endpoint or SSE stream)?
   Recommendation: synchronous for MVP; SSE for production richness.
2. **Cancellation.** How does the Companion UI cancel a `confirming` or
   `executing` proposal? Is there a `DELETE /api/panel/confirm/{idempotency_key}`
   or equivalent?
3. **Partial-complete handling.** If a proposal decomposes into sub-actions and
   some are blocked, how does the response model `partial` outcomes?
4. **Proposal validity window.** How long is a staged proposal valid before its
   `proposal_id` expires? What does the Companion UI show when a proposal has
   expired?
5. **Authentication.** What auth context does the endpoint require? Is it
   session-scoped to the Companion UI session?

---

## Governing Boundary Statement

- This document is contract/spec only.
- The endpoint is not implemented here.
- No backend routes are added by this document.
- No event schemas are changed by this document.
- The Companion UI must not write vault files directly under any circumstance.
- The runtime is the sole writer of vault-visible state.
- All execution must flow through policy → WriteGuard → idempotency →
  deterministic writer → receipt.
