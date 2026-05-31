---
name: Panel Confirmation / Checkbox Projection API Contract
description: API contract for Panel confirmation transport and the future runtime-mediated checkbox projection endpoint — request/response schema, source freshness, idempotency, blocked/receipt semantics, and boundary rules
doc_role: API contract / spec
authority: Binding contract for any implementation or revision of Panel confirmation transport and read-mode checkbox projection. Must not be bypassed or extended without a governing issue.
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

# Panel Confirmation / Checkbox Projection API Contract

## Purpose

Define the API contract boundary for Panel confirmation transport and the future runtime-mediated read-mode checkbox projection path.

This document is **spec/contract only**. It does not implement the endpoint,
does not add backend routes, and does not change event schemas. The
implementation belongs to a follow-up issue explicitly scoped to runtime
endpoint implementation or endpoint revision.

---

## Background

`companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md :: Part 3` established:

- Direct Companion UI vault write-back is not viable. The UI must not write
  vault files directly.
- The preferred Companion UI read-mode path is runtime-mediated checkbox
  projection, where the runtime validates a UI click and writes/projects the
  canonical checked Markdown checkbox state.
- Any confirmation path must produce a durable vault-visible projection
  identical to the CLI/watcher flow.
- Same-turn execution of newly generated proposals is NOT allowed unless the
  existing governed runtime explicitly supports it.

Current-state correction: the existing `POST /api/panel/confirm` implementation
is a staged proposal confirmation endpoint backed by transient proposal identity.
It does not yet validate current vault Markdown, validate source freshness, and
project `- [x]` inside the Panel block before execution. Therefore it is
insufficient for Companion UI read-mode Markdown checkbox projection until a
future implementation revises it or adds a separate projection endpoint.

This document defines the future projection contract so implementation can be
scoped in a separate issue without claiming the current endpoint already
provides this behavior.

---

## Endpoint

```
POST /api/panel/confirm
```

The current route name may be retained for compatibility, but before it can
serve Companion UI read-mode checkbox clicks it must be revised to behave as a
runtime-mediated checkbox projection endpoint. A separate endpoint may also be
introduced if compatibility requires keeping the staged proposal confirmation
API distinct.

For read-mode checkbox projection, the endpoint request is transport. It is not
the durable approval authority. The durable human-facing confirmation signal is
the checked Markdown checkbox in the valid Panel `AI-åtgärder` section.

The runtime sequence is:

1. Validate the current note/artifact and source freshness.
2. Validate the target Panel and selectable option identity.
3. Enforce WriteGuard and safe/degraded runtime policy.
4. Project the canonical checked checkbox state (`- [x]`) through the governed
   backend write path.
5. Schedule or trigger normal Panel execution so execution observes or is
   triggered from that checked checkbox state.
6. Emit/record status and receipts according to existing Panel event/outbox and
   receipt conventions.

---

## Future Read-Mode Projection Request Schema

```json
{
  "artifact_id": "<string>",
  "note_path": "<string>",
  "panel_id": "<string>",
  "option_id": "<string>",
  "expected_content_hash": "<string>",
  "expected_source_hash": "<string or null>",
  "idempotency_key": "<string>"
}
```

### Field definitions

| Field | Type | Required | Description |
|---|---|---|---|
| `artifact_id` | string | yes | Note/artifact identity for the active artifact. |
| `note_path` | string | yes | Vault-relative or runtime-resolved path for the current note. Must identify the same artifact as `artifact_id` under the active vault binding. |
| `panel_id` | string | yes | Runtime-declared identifier for the Panel block that contains the selectable option. |
| `option_id` | string | yes | Durable identity for the specific selectable Panel option line. Must not be inferred from label text, rendered DOM order, or `ai:proposed`. |
| `expected_content_hash` | string | yes | Hash of the note content snapshot rendered by Companion UI. Used to reject stale projection requests. |
| `expected_source_hash` | string or null | yes | Hash of the source line/range for the option when available. Null is allowed only when the runtime-defined projection contract explicitly permits content-level freshness alone. |
| `idempotency_key` | string | yes | Client-generated UUID (v4) or equivalent. Duplicate requests with the same key must return the same projection/execution status without duplicating writes or execution. |

### Constraints

- `artifact_id`, `note_path`, `panel_id`, `option_id`,
  `expected_content_hash`, and `idempotency_key` must be present and non-empty.
- `idempotency_key` must be a unique opaque string per confirmation attempt.
  Retry of a failed network request must use the **same** idempotency key.
  A new user-initiated projection attempt must use a **new** idempotency key.
- The request targets checkbox projection only. Correction/edit/reject flows
  require separate contract text and must not be smuggled into the first
  read-mode checkbox slice.
- The Companion UI must not call this projection path in the same turn that a
  proposal was generated unless a future governed runtime contract explicitly
  allows that path.

### Validation requirements

The runtime must validate:

- `note_path` / `artifact_id` identify the same current artifact under the active vault binding.
- `panel_id` resolves to a valid Panel block in the current note.
- `option_id` resolves to exactly one pending/selectable option in that Panel.
- The option is inside `AI-åtgärder`.
- The option is not inside a code block.
- The option is not an ordinary Markdown task.
- Current content/source hash matches the UI snapshot or the request fails stale.
- WriteGuard and safe/degraded policy allow projection.
- Duplicate requests with the same idempotency key do not duplicate writes or execution.

---

## Response Schema

### Success (HTTP 200)

```json
{
  "option_id":     "<string>",
  "panel_id":      "<string>",
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
  "option_id": "<string>",
  "panel_id": "<string>",
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
  "option_id": "<string or null>",
  "idempotency_key": "<string or null>"
}
```

### Status Values

| Status | Description |
|---|---|
| `projecting` | Runtime received the request and is validating/projecting the checked checkbox. |
| `projected` | The checked checkbox projection was written; execution is pending or has been scheduled. |
| `executing` | Normal Panel execution is in progress after projection. |
| `executed` | Execution complete. Receipt is present. |
| `blocked` | Execution was blocked (policy, WriteGuard, allowlist, capability). |
| `logged` | Action was logged for review rather than executed (policy outcome). |
| `stale` | The current note content/source no longer matches the UI snapshot. |
| `not_found` | The target Panel or option no longer exists or no longer resolves uniquely. |

### Outcome Values

| Outcome | Description |
|---|---|
| `projected` | Checked checkbox state was projected; execution has not completed yet. |
| `success` | Governed execution completed; vault-visible projection written. |
| `blocked` | Execution denied at a policy gate. |
| `logged` | Action logged; deferral projection written. |
| `partial` | Some sub-actions succeeded, others blocked (if applicable). |
| `stale` | Projection rejected because the source content changed. |
| `not_found` | Projection rejected because the Panel option is missing or ambiguous. |

---

## Option Identity Correlation

- The `option_id` in the projection request must match a durable option
  identity declared by the runtime for one selectable Panel checkbox line.
- The runtime must resolve `option_id` against the current Markdown source,
  scoped by `artifact_id`, `note_path`, and `panel_id`.
- `ai:proposed` is only a pending marker and is not an option identity.
- Existing `ai:id` must not be treated as durable `option_id` until
  `docs/PANEL_AGENT.md` explicitly promotes it and defines collision,
  duplicate-label, and migration semantics.
- If the `option_id` is unknown, expired, missing, moved without a validating
  source hash, or ambiguous, the endpoint must return a 4xx or typed response
  with `status: "not_found"` or `status: "stale"` as appropriate.

---

## Idempotency Expectations

- The runtime must use the `idempotency_key` to detect duplicate projection
  requests and return the original response without duplicating projection or
  execution.
- Idempotency window: at minimum for the duration of the execution outcome
  visibility period (until the user navigates away or dismisses the receipt).
- If the checkbox was already projected or the action already executed for the
  same option and source generation, a duplicate request with the same key must
  return the original status/receipt rather than failing or re-executing.
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

The future projection implementation must produce a durable vault-visible
projection equivalent to the CLI/watcher flow:

- The target checkbox is projected as checked (`- [x]`) inside the valid Panel
  `AI-åtgärder` section.
- Executed checkboxes removed from the panel working set.
- AI status callout (`> [!info]- AI status`) updated with the execution receipt.
- Event stream emissions as appropriate.
- Vault state remains readable/actionable in Obsidian without Companion UI
  being present.

See `companion-ui/docs/PANEL_DURABLE_PROJECTION_MAPPING.md` for the full
projection mapping.

---

## Same-Turn Execution Prohibition

The projection path must not accept a request for an option that was generated
in the same Companion UI interaction turn. Same-turn execution of newly
generated proposals is not allowed by this contract.

Enforcement mechanism (implementation recommendation):
- Include a `proposed_at` timestamp or source-generation marker in the option
  payload exposed to Companion UI.
- Reject requests where the option was generated within the current interaction window.
- Alternatively, track a `generation_turn_id` and refuse confirms within the
  same turn ID.

---

## Direct Companion UI Vault Write-Back: Explicitly Rejected

The Companion UI must not write vault files directly. All vault mutations
(checkbox state, AI status callout, receipts) are written by the runtime
through the governed execution path.

The endpoint request is transport — not durable approval authority and not
execution authority. The durable human-facing confirmation signal is the
checked Panel checkbox in vault Markdown. Execution authority remains with the
runtime after normal Panel validation.

---

## Relation to Existing Panel Runtime Events/Receipts

After projection, normal Panel execution must emit events according to
`docs/PANEL_AGENT.md` event inventory. The projection endpoint may return the
event names it directly emitted or scheduled, but it must not invent a second
proposal/execution model.

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
- Submitting the projection request for a runtime-declared eligible Panel option.
- Rendering the `confirming → executing → receipt` state progression.
- Displaying the receipt after execution.

---

## Required Tests Before Implementation

The following tests must exist before or alongside endpoint implementation:

1. Parser/mapping tests prove only valid Panel `AI-åtgärder` checkboxes are eligible.
2. Projection endpoint validation tests cover `artifact_id`, `note_path`, `panel_id`, `option_id`, content/source hashes, and pending/selectable status.
3. Stale source tests reject changed content and moved/missing options.
4. WriteGuard and safe/degraded-mode tests prove projection does not bypass governed write policy.
5. Idempotency/retry tests cover duplicate browser clicks, retries, already-checked options, and watcher overlap.
6. Watcher/runtime convergence tests prove Obsidian/plain-text checked checkboxes and Companion UI projection produce the same semantics and receipts.
7. Companion UI read-mode browser tests prove ordinary task checkboxes stay non-agent controls and only runtime-declared Panel options call the projection endpoint.

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
4. **Option identity decision.** Does the runtime promote `ai:id` into durable
   `option_id` with stronger generation rules, or introduce a new explicit
   marker such as `<!--ai:option_id=...-->`?
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
