---
name: Companion UI Workspace State Contract
description: Read-side aggregate contract for the Companion UI browser workspace state endpoint
doc_role: API contract / spec
authority: Binding read-side contract for `GET /api/companion/workspace` and downstream Canvas/Panel browser integration.
owner: Companion UI / product architecture
last_reviewed: 2026-05-19
source_contracts:
  - companion-ui/docs/COMPANION_UI_TARGET_ARCHITECTURE.md
  - companion-ui/docs/UI_RUNTIME_BOUNDARIES.md
  - companion-ui/docs/PANEL_COMPANION_UI_CONTRACT.md
  - companion-ui/docs/PANEL_CONFIRMATION_API_CONTRACT.md
  - companion-ui/docs/CANVAS_AGENT_MVP_CONTRACT.md
  - companion-ui/docs/CANVAS_SUGGESTION_FLOW.md
governing_issue: "#1122"
---

# Workspace State Contract

## Purpose

Define the read-side aggregate endpoint the browser workspace uses to load one
coordinated view of the active artifact and its Companion UI runtime state.

This contract exists because `GET /api/artifacts/note` only reads the artifact
body and note metadata. The browser also needs Canvas session posture, Panel
proposal posture, suggestion posture, and guard status before Canvas/Panel
browser integration can proceed.

This document is a contract only. It does not implement the endpoint.

## Scope (artifact-scoped)

This contract is **artifact-scoped**. `note_path` is required; the aggregate
describes the state *around one active note*. It is one of two read-side
Workspace State surfaces:

- **Artifact Workspace Snapshot (this contract):** `GET /api/companion/workspace?note_path=…`
  — answers "what is the state around this artifact?"
- **Workspace Orientation Snapshot (planned, v6.1):** a separate
  note-independent surface (`GET /api/companion/orientation`) that exists when
  no note is open — answers "where am I in the system, what is open, and what
  can I safely resume?" The planned contract is
  `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`.

Re-entry, continuity, resurfacing-when-idle, and orientation-after-absence are
**not** served by widening this aggregate; they belong to the note-independent
surface. The scope split, endpoint shape, and shared invariants
(read-only + `mutation_intents`, bounded collections, snapshot-level freshness,
per-item `authority_role`/`source_ref`, no `orchestration`/`runtime` dashboard
slices) are recorded in
`docs/adr/ADR-0007-workspace-state-contract-scope-split.md` and detailed in
`companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`. The note-independent
surface is shipped as a read-only Phase 1 endpoint; Companion UI consumption is
tracked separately.

## Endpoint

```http
GET /api/companion/workspace?note_path=<relative_path>
```

The endpoint is read-only. It may aggregate runtime state from existing
endpoints or services, but it must not mutate vault files, session state,
Panel state, receipts, or write-guard state.

### Request Parameters

| Field | Required | Description |
|---|---:|---|
| `note_path` | yes | Runtime-relative note path for the artifact to load. Absolute vault filesystem paths are not accepted from browser callers. |

## Authority Rules

- The endpoint is a read-side UI aggregate. It is not a source of semantic,
  governance, or mutation authority.
- The UI must not infer body/governance classification from this payload.
  Classification is server-declared and belongs to the runtime.
- The UI must not infer Panel action classes, capability classes, or governance
  categories locally.
- The payload must not expose raw vault filesystem paths to the browser.
- Runtime environment selection, vault binding, policy, WriteGuard, execution,
  and receipt production remain owned by the backend runtime.
- If an aggregate field is unavailable, the response must surface that as
  `guards.degraded = true` with a reason-bearing blocked/error field rather
  than letting the UI guess.

## Success Payload

```json
{
  "artifact": {
    "artifact_id": "string | null",
    "artifact_kind": "human_note | companion_note",
    "note_path": "string",
    "title": "string",
    "body": "string",
    "content_hash": "string",
    "identity_source": "frontmatter.uuid | frontmatter.id | uuid_healing | companion_path | missing",
    "identity_state": "resolved | legacy_resolved | healed | unresolved_missing_uuid | companion_of_resolved",
    "companion_of": "string | null",
    "owns_identity": true
  },
  "runtime": {
    "environment_label": "dev | test | prod | unknown",
    "api_base_url_label": "string",
    "trace_id": "string",
    "reorient": {
      "facts": [],
      "inferences": [],
      "candidates": [],
      "stale_context": [],
      "recent_deltas": [],
      "open_loops": []
    },
    "resurface": {
      "candidates": []
    }
  },
  "canvas": {
    "session_id": "string | null",
    "session_state": "start | active | paused | interrupted | closed | null",
    "user_present": true,
    "can_edit_body": true,
    "recovery_needed": false,
    "session_log_path": "string | null",
    "session_persistence": "in_memory | durable"
  },
  "panel": {
    "state": "idle | running | proposals-staged | confirming | executing | receipt-displayed | no-match | blocked | clarification-needed | plan-staged | capability-needed | partial-complete",
    "proposal_count": 0,
    "receipt_count": 0,
    "latest_receipt_outcome": "success | blocked | logged | partial | rejected | null",
    "blocked_reason": null,
    "no_match_reason": null
  },
  "suggestions": {
    "current_suggestion_state": null,
    "server_declared_classification": null,
    "pending_receipts": []
  },
  "guards": {
    "canvas_enabled": false,
    "writeguard_status": "ok | blocked | unknown",
    "degraded": false
  }
}
```

## Field Rules

### `artifact`

`artifact` is the note body and note identity needed to render the active
workspace.

| Field | Rule |
|---|---|
| `artifact_id` | Stable artifact identifier when available. For normal human vault notes this is the frontmatter `uuid` or a UUID written by the approved healing path. `null` means identity is explicitly unresolved. Path strings and content hashes must not be used as fallback artifact IDs. |
| `artifact_kind` | `human_note` for normal vault notes; `companion_note` for system-plane companion continuity artifacts. |
| `note_path` | Browser-safe runtime-relative path or opaque note reference. It must not be an absolute vault path. |
| `title` | Display title extracted or supplied by the runtime. |
| `body` | Current note body at the time of aggregation. |
| `content_hash` | Hash of the body returned in this payload. Browser edit flows must use it as the stale-read baseline before full-body replacement. |
| `identity_source` | Source of the resolved or unresolved identity decision. |
| `identity_state` | Server-declared identity state. Missing UUID notes that cannot be healed must surface an unresolved state rather than a path/hash fallback. |
| `companion_of` | Main note UUID when the loaded artifact is a companion note; otherwise `null`. |
| `owns_identity` | `true` when the loaded artifact owns human-note identity; `false` for companion notes and other system-plane continuity records. |

Canvas-origin governance proposals and Panel proposal lookup must use the same
resolved `artifact_id` as this workspace aggregate for the same human note.
Companion notes may be represented as companion state, but their path or content
hash must not be treated as human-note artifact identity. Attachment manifest
entries remain locators/version markers in this contract, not independent
artifact UUIDs.

### `runtime`

`runtime` gives the browser safe operational labels for the currently attached
runtime.

| Field | Rule |
|---|---|
| `environment_label` | Safe label only. It must not include vault root paths. |
| `api_base_url_label` | Safe display label such as `local-dev`, `local-test`, `local-prod`, or an operator-provided alias. It must not expose filesystem paths or secrets. |
| `trace_id` | Correlation ID for this aggregate read. |
| `reorient` | Read-only Reorient-mode projection derived from the orientation runtime. Items are grouped as facts, inferences, candidates, stale context, recent deltas, and open loops. Each item must carry a source link; actionable items may expose a Panel handoff hint, but the workspace aggregate does not execute or mutate from Reorient mode. |
| `resurface` | Read-only Resurface-mode projection derived from the resurfacing runtime. Candidates carry a grounded why-now explanation, relation to the active artifact, source link, and signal labels. Dismiss, snooze, and pin are UI affordances only in this slice; the aggregate does not persist those decisions or upgrade similarity into urgency. |

### `canvas`

`canvas` describes the active Canvas session posture for the artifact.

| Field | Rule |
|---|---|
| `session_id` | Current session ID if one is open for this artifact, else `null`. |
| `session_state` | Canvas session lifecycle state from the Canvas Core contract, or `null` when no session exists. |
| `user_present` | Whether user-present body co-authoring authority is currently available. |
| `can_edit_body` | True only when Canvas is enabled, a session is active, user presence is established, and the active mutation class is body-only. |
| `recovery_needed` | True for paused/interrupted recoverable sessions. |
| `session_log_path` | Browser-safe vault-relative `.chats/...` provenance path when available. It must not be an absolute vault filesystem path. |
| `session_persistence` | Typed capability field: `in_memory` or `durable`. |

#### Durability Posture

For the current browser dev/server integration slice,
`session_persistence: "in_memory"` is explicitly accepted.

Meaning:

- Canvas sessions survive only for the lifetime of the API process.
- A process restart loses the in-memory session registry.
- The note body remains durable through the normal note write path.
- Session logs that have already been written remain durable provenance, but
  the open session registry itself is not durable.

This is accepted because the current slice is a local dev/staging integration
path and the shipped Canvas API keeps session state in memory. A future durable
session registry is a separate implementation decision and must not be implied
by this contract.

### `panel`

`panel` is the canonical Panel state slice for browser cold load and explicit
refresh.

| Field | Rule |
|---|---|
| `state` | One of the Panel render states defined in `PANEL_COMPANION_UI_CONTRACT.md`. |
| `proposal_count` | Count of currently staged artifact-local proposals for this note. |
| `receipt_count` | Count of current receipt/outcome items relevant to this note. |
| `latest_receipt_outcome` | Server-declared outcome for the most recent relevant receipt: `success`, `blocked`, `logged`, `partial`, `rejected`, or `null` when no receipt is available. The UI must use this field, not `state`, to distinguish successful execution from logged/deferred or blocked outcomes on cold load. |
| `blocked_reason` | Human-readable reason when `state = "blocked"`, else `null`. |
| `no_match_reason` | Human-readable reason when `state = "no-match"`, else `null`. |

The workspace aggregate is the read-side discovery mechanism for Panel browser
state. A separate Panel discovery endpoint must not be introduced unless this
aggregate proves insufficient in a later accepted delta.

### `suggestions`

`suggestions` describes the Canvas bounded suggestion flow posture when a
suggestion is currently staged or pending.

| Field | Rule |
|---|---|
| `current_suggestion_state` | Canonical state from `CANVAS_SUGGESTION_FLOW.md`, or `null`. |
| `server_declared_classification` | Server-declared classification such as `body` or `governance`, or `null`. The UI must not compute this locally. |
| `pending_receipts` | Pending governance receipt summaries for queued suggestions. Empty when none. |

### `guards`

`guards` lets the browser render safe blocked/degraded states without making
policy decisions itself.

| Field | Rule |
|---|---|
| `canvas_enabled` | Server-side Canvas feature flag value. |
| `writeguard_status` | Runtime-reported guard posture: `ok`, `blocked`, or `unknown`. |
| `degraded` | True when the aggregate is partial or a sub-surface could not be evaluated. |

## error payloads

The endpoint returns typed error payloads for request-level failures.

### Invalid Path

```json
{
  "error": "invalid_note_path",
  "message": "note_path must be a relative runtime note path",
  "trace_id": "string"
}
```

Use HTTP 400 or 422.

### Note Not Found

```json
{
  "error": "note_not_found",
  "message": "No note exists for the requested note_path",
  "note_path": "string",
  "trace_id": "string"
}
```

Use HTTP 404.

### Runtime Unavailable

```json
{
  "error": "runtime_unavailable",
  "message": "The runtime aggregate source could not be reached",
  "trace_id": "string"
}
```

Use HTTP 503.

## Blocked and Degraded Payloads

Surface-level blocks should usually return HTTP 200 with a complete aggregate
and reason-bearing blocked fields. This lets the browser render the note while
showing unavailable actions.

### Canvas Disabled

```json
{
  "canvas": {
    "session_id": null,
    "session_state": null,
    "user_present": false,
    "can_edit_body": false,
    "recovery_needed": false,
    "session_log_path": null,
    "session_persistence": "in_memory"
  },
  "guards": {
    "canvas_enabled": false,
    "writeguard_status": "unknown",
    "degraded": false
  }
}
```

### WriteGuard Blocked

```json
{
  "panel": {
    "state": "blocked",
    "proposal_count": 0,
    "receipt_count": 0,
    "latest_receipt_outcome": "blocked",
    "blocked_reason": "WriteGuard blocked the requested operation",
    "no_match_reason": null
  },
  "guards": {
    "canvas_enabled": true,
    "writeguard_status": "blocked",
    "degraded": false
  }
}
```

### Partial Aggregate

```json
{
  "guards": {
    "canvas_enabled": true,
    "writeguard_status": "unknown",
    "degraded": true
  }
}
```

A partial aggregate must include a specific reason-bearing field in the surface
that failed to resolve. The UI must not silently substitute local defaults.

## existing endpoints

This endpoint complements existing API surfaces. It must not duplicate their
write authority.

| Existing endpoint | Relationship |
|---|---|
| `GET /api/artifacts/note` | Artifact read source. The aggregate may reuse it, but must normalize browser-facing `note_path` so raw vault filesystem paths are not exposed. |
| `POST /api/canvas/sessions` | Existing Canvas session lifecycle write path. The aggregate reports current state; it does not open sessions. |
| `POST /api/canvas/sessions/{id}/edits` | Existing Canvas body edit path. The aggregate provides the body and content hash baseline for browser edit flows; it does not apply edits. |
| `DELETE /api/canvas/sessions/{id}` | Existing Canvas session close path. The aggregate reports state; it does not close sessions. |
| `POST /api/panel/confirm` | Existing Panel confirmation write path. The aggregate reports staged/receipt posture; confirmation remains explicit and runtime-mediated. |

## Implementation Gate

Implementing `GET /api/companion/workspace` must follow this contract before
Canvas browser editing or Panel browser discovery issues proceed.

The Panel slice in this document is the canonical source for Panel browser
state discovery. `PANEL_STATE_DISCOVERY_DELTA.md` may only confirm sufficiency
or define additive gaps.
