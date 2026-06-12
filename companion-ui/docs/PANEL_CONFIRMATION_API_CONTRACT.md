---
name: Panel Confirmation / Checkbox Projection API Contract
description: API contract for Panel confirmation transport and the runtime-mediated checkbox projection endpoint — request/response schema, source freshness, idempotency, blocked/receipt semantics, and boundary rules
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

Define the API contract boundary for Panel confirmation transport and the runtime-mediated read-mode checkbox projection path.

Current implementation status: `POST /api/panel/checkbox-projection` is the source-backed read-mode projection endpoint. `POST /api/panel/confirm` remains the staged/transient proposal confirmation endpoint and is not the Markdown checkbox projection path.

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

Current-state correction: the existing `POST /api/panel/confirm` implementation is a staged proposal confirmation endpoint backed by transient proposal identity. It does not validate current vault Markdown, validate source freshness, and project `- [x]` inside the Panel block before execution. It remains insufficient for Companion UI read-mode Markdown checkbox projection.

---

## Endpoint

```
POST /api/panel/checkbox-projection
```

This endpoint is distinct from `POST /api/panel/confirm` so the staged proposal confirmation API can remain compatibility-stable.

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

## Read-Mode Projection Request Schema

```json
{
  "artifact_id": "<string>",
  "note_path": "<string>",
  "panel_id": "<string>",
  "option_id": "<string>",
  "expected_content_hash": "<string>",
  "expected_source_hash": "<string>",
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
| `expected_source_hash` | string | yes | SHA-256 hash of the current source line for the option in the UI snapshot. |
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
- The request targets only projection of an unchecked pending/selectable option to checked state. It does not implement batch confirmation, uncheck, reject, correction, or multi-select grace semantics.

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
  "status": "projected|already_projected|queued|executed|blocked|stale|not_found|not_selectable|failed",
  "artifact_id": "<string>",
  "note_path": "<string>",
  "panel_id": "<string>",
  "option_id": "<string>",
  "content_hash_before": "<string>",
  "content_hash_after": "<string>",
  "receipt": null,
  "block_reason": "<string or null>",
  "idempotency_key": "<string>"
}
```

### Blocked (HTTP 200)

```json
{
  "status": "blocked",
  "artifact_id": "<string>",
  "note_path": "<string>",
  "panel_id": "<string>",
  "option_id": "<string>",
  "content_hash_before": "<string>",
  "content_hash_after": "<string>",
  "receipt": null,
  "block_reason": "<human-readable reason>",
  "idempotency_key": "<string>"
}
```

### Error (HTTP 4xx / 5xx)

```json
{
  "detail": {
    "status": "stale|not_found|not_selectable|failed",
    "artifact_id": "<string>",
    "note_path": "<string>",
    "panel_id": "<string>",
    "option_id": "<string>",
    "content_hash_before": "<string>",
    "content_hash_after": "<string>",
    "receipt": null,
    "block_reason": "<string or null>",
    "idempotency_key": "<string>"
  }
}
```

### Status Values

| Status | Description |
|---|---|
| `projected` | The checked checkbox projection was written; execution is pending or has been scheduled. |
| `already_projected` | The targeted option is already checked in current Markdown. |
| `queued` | Projection succeeded and normal Panel execution is deferred to watcher/runtime convergence. |
| `executed` | Normal Panel execution ran after projection. |
| `blocked` | Projection was blocked by WriteGuard or runtime safety policy before the checkbox was changed. |
| `stale` | The current note content/source no longer matches the UI snapshot. |
| `not_found` | The target Panel or option no longer exists or no longer resolves uniquely. |
| `not_selectable` | The target exists but is not an unchecked pending/selectable option. |
| `failed` | Projection succeeded but immediate runtime execution failed; the vault-visible checked checkbox remains the convergence signal. |

### HTTP Mapping

| HTTP status | Projection status |
|---|---|
| `200` | `projected`, `already_projected`, `queued`, `executed`, `blocked`, or `failed` after a successful projection with runtime execution failure |
| `404` | `not_found` |
| `409` | `stale` content/source mismatch |
| `422` | invalid request or `not_selectable` |
| `500` | unexpected backend failure before a typed projection response can be produced |

---

## Option Identity Correlation

- The `option_id` in the projection request must match a durable option
  identity declared by the runtime for one selectable Panel checkbox line.
- The runtime must resolve `option_id` against the current Markdown source,
  scoped by `artifact_id`, `note_path`, and `panel_id`.
- `ai:proposed` is only a pending marker and is not an option identity.
- Existing `ai:id` is not durable `option_id`; it remains legacy/current runtime
  idempotency and removal metadata.
- Runtime-generated proposals use the explicit durable marker
  `<!--ai:option_id=opt_...-->`.
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

A receipt is a durable record of execution outcome. For the first read-mode
checkbox projection slice, the projection response may return `receipt: null`;
the Companion UI refreshes workspace state after projection instead of treating
the transport response as a durable receipt store. Durable receipts are written
to the vault AI-status callout only by normal Panel runtime paths that emit such
receipts (see `PANEL_DURABLE_PROJECTION_MAPPING.md`). Companion UI never writes
receipts directly, and `status=executed` from checkbox projection is not by
itself a universal guarantee that an AI-status callout was appended for every
mapped, logged, or unhandled runtime path.

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

The projection implementation must produce a durable vault-visible projection
equivalent to the CLI/watcher flow:

- The target checkbox is projected as checked (`- [x]`) inside the valid Panel
  `AI-åtgärder` section.
- Executed checkboxes removed from the panel working set.
- AI status callout (`> [!info]- AI status`) updated with the execution receipt
  when the invoked Panel runtime path emits one.
- Event stream emissions as appropriate.
- Vault state remains readable/actionable in Obsidian without Companion UI
  being present.

See `companion-ui/docs/PANEL_DURABLE_PROJECTION_MAPPING.md` for the full
projection mapping.

---

## Same-Turn Execution Boundary

The first implementation slice does not add a Companion-only same-turn approval
model. Source freshness, pending/selectable status, WriteGuard, and normal
Panel runtime gates still apply. If stricter same-turn turn-ID enforcement is
required, it must be added as a separate runtime contract and test slice.

Possible future enforcement mechanism:
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

The current checkbox-projection response does not expose an `events_emitted`
field. Companion UI refreshes workspace state after the projection response;
future richer status APIs may expose event names or receipt details.

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

## Required Coverage

The implementation must carry focused coverage for:

1. Parser/mapping tests prove only valid Panel `AI-åtgärder` checkboxes are eligible.
2. Projection endpoint validation tests cover `artifact_id`, `note_path`, `panel_id`, `option_id`, content/source hashes, and pending/selectable status.
3. Stale source tests reject changed content and moved/missing options.
4. WriteGuard and safe/degraded-mode tests prove projection does not bypass governed write policy.
5. Idempotency/retry tests cover duplicate browser clicks, retries, already-checked options, and watcher overlap.
6. Watcher/runtime convergence tests prove Obsidian/plain-text checked checkboxes and Companion UI projection produce the same semantics and receipts.
7. Companion UI read-mode tests prove ordinary task checkboxes stay non-agent controls and only runtime-declared Panel options call the projection endpoint.

---

## Open Questions (Deferred to Follow-Up)

1. **Status feedback mechanism.** Is confirmation status delivered synchronously
   (single response) or asynchronously (polling endpoint or SSE stream)?
   Recommendation: synchronous for MVP; SSE for production richness.
2. **Cancellation.** How does the Companion UI cancel a `confirming` or
   `executing` proposal? Is there a `DELETE /api/panel/confirm/{idempotency_key}`
   or equivalent?
3. **Partial-complete handling.** If a proposal decomposes into sub-actions and
   some are blocked, how does the response model `partial` outcomes?
4. **Authentication.** What auth context does the endpoint require? Is it
   session-scoped to the Companion UI session?

---

## Governing Boundary Statement

- `POST /api/panel/checkbox-projection` is the read-mode source-backed projection endpoint.
- `POST /api/panel/confirm` remains the staged/transient proposal confirmation endpoint.
- No event schemas are changed by this contract.
- The Companion UI must not write vault files directly under any circumstance.
- The runtime is the sole writer of vault-visible state.
- All execution must flow through policy → WriteGuard → idempotency →
  deterministic writer → receipt.
