---
name: Companion UI Workspace Orientation Contract
description: Planned note-independent read-side contract for the Companion UI workspace orientation endpoint
doc_role: API contract / spec
authority: Binding planned read-side contract for `GET /api/companion/orientation` and downstream Companion UI re-entry integration.
owner: Companion UI / product architecture
last_reviewed: 2026-05-31
source_contracts:
  - docs/adr/ADR-0007-workspace-state-contract-scope-split.md
  - companion-ui/docs/WORKSPACE_STATE_CONTRACT.md
  - companion-ui/docs/UI_RUNTIME_BOUNDARIES.md
  - docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md
  - docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md
  - docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md
governing_issue: "#1451"
implementation_state: planned
---

# Workspace Orientation Contract

## Purpose

Define the planned note-independent read-side orientation snapshot the Companion
UI can use for cold load and re-entry when no artifact is active.

The existing Workspace State Contract remains artifact-scoped:
`GET /api/companion/workspace?note_path=...` requires `note_path` and answers
"what is the state around this artifact?" This contract defines the separate
Workspace Orientation Snapshot at `GET /api/companion/orientation`, which
answers "where am I in the system, what is open, what changed, and what can I
safely resume?"

This document is a contract only. It does not implement the endpoint. Until the
runtime implementation issue ships, clients must not assume this endpoint is
available.

## Scope

This contract is **workspace-scoped** and note-independent.

- Endpoint: `GET /api/companion/orientation`.
- No `note_path` request parameter is required or owned by this surface.
- The response scope envelope is:

```json
{
  "scope": {
    "kind": "workspace",
    "vault_id": "string",
    "channel": "dev | test | prod | unknown"
  }
}
```

`vault_id` is an opaque runtime label. It must not expose an absolute vault
filesystem path. Artifact references inside the payload may include
browser-safe, runtime-relative `note_path` values for deep links back to the
artifact workspace, but they must not include raw vault absolute paths or raw
note bodies.

This orientation surface is one of the two read-side Workspace State surfaces
defined by ADR-0007:

- **Artifact Workspace Snapshot:** `GET /api/companion/workspace?note_path=...`
  remains governed by `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md`.
- **Workspace Orientation Snapshot:** `GET /api/companion/orientation` is
  governed by this contract.

The orientation surface is a re-entry substrate, not a runtime dashboard, not a
chat surface, and not a durable state store.

## Endpoint

```http
GET /api/companion/orientation
```

The endpoint is read-only. It may compose a snapshot from existing read-only
derivers and runtime status summaries, but it must not mutate vault files,
session state, Panel state, receipts, WriteGuard state, memory state, or any
durable semantic artifact.

### Request Parameters

No request parameter is required. Browser callers must not send `note_path` to
this endpoint; artifact-specific loading belongs to
`GET /api/companion/workspace?note_path=...`.

## Authority Rules

- The endpoint is a read-side UI projection. It is not a source of semantic,
  governance, memory, orchestration, or mutation authority.
- Server-declared classification is authoritative for the UI. The UI renders
  `authority_role`, `source_ref`, governance counts, latest receipt outcome,
  and degraded posture as supplied; it must not infer governance or authority
  locally.
- `mutation_intents` are handoff hints only. They must never execute, persist,
  enqueue, write receipts, call WriteGuard, promote memory, or mutate state
  through this read path.
- Phase 1 returns `mutation_intents: []`. MemoryCandidate intent emission is
  explicitly deferred to a later phase and must not be introduced by this
  contract.
- Every non-trivial item carries `authority_role` and `source_ref`.
- Snapshot freshness is declared at `meta` level only. Per-item freshness fields
  are intentionally excluded to avoid token amplification.
- The endpoint must not expose raw vault absolute paths, raw note bodies, raw
  chat history, raw embeddings, agent scratchpads, or internal orchestration
  state.
- Runtime health remains owned by `/api/status`. This payload may expose only a
  minimal derived guard/degraded posture needed for orientation rendering.

## Success Payload

```json
{
  "scope": {
    "kind": "workspace",
    "vault_id": "default",
    "channel": "dev"
  },
  "meta": {
    "contract_version": "workspace_orientation.v1",
    "as_of": "2026-05-31T12:00:00Z",
    "trace_id": "trace-id",
    "freshness": "fresh | stale | partial | unknown",
    "stale_after": "2026-05-31T12:05:00Z",
    "degraded_reasons": [],
    "caps": {
      "open_loops": 8,
      "notable_changes": 8,
      "resurface_candidates": 5,
      "mutation_intents": 0,
      "source_refs_per_item": 3
    }
  },
  "leave_point": {
    "kind": "derived_only",
    "artifact_ref": {
      "artifact_id": "string | null",
      "note_path": "relative/path.md",
      "title": "string"
    },
    "label": "string | null",
    "last_interaction_at": "2026-05-31T11:45:00Z",
    "last_session_id": "string | null",
    "authority_role": "derived",
    "source_ref": {
      "kind": "runtime_signal",
      "ref": "opaque-source-ref",
      "label": "orientation signals"
    }
  },
  "open_loops": [
    {
      "id": "opaque-open-loop-id",
      "label": "string",
      "status": "open | blocked | waiting | unknown",
      "handoff_hint": "panel | canvas | none",
      "artifact_ref": {
        "artifact_id": "string | null",
        "note_path": "relative/path.md",
        "title": "string"
      },
      "authority_role": "derived",
      "source_ref": {
        "kind": "trace | receipt | runtime_signal",
        "ref": "opaque-source-ref",
        "label": "string"
      }
    }
  ],
  "notable_changes": [
    {
      "id": "opaque-change-id",
      "label": "string",
      "summary": "bounded summary, not a raw note body",
      "changed_at": "2026-05-31T10:00:00Z",
      "artifact_ref": {
        "artifact_id": "string | null",
        "note_path": "relative/path.md",
        "title": "string"
      },
      "authority_role": "derived",
      "source_ref": {
        "kind": "artifact | trace | runtime_signal",
        "ref": "opaque-source-ref",
        "label": "string"
      }
    }
  ],
  "resurface": {
    "candidates": [
      {
        "id": "opaque-candidate-id",
        "label": "string",
        "why_now": "bounded why-now explanation",
        "signal_labels": ["recent_change", "open_loop"],
        "artifact_ref": {
          "artifact_id": "string | null",
          "note_path": "relative/path.md",
          "title": "string"
        },
        "authority_role": "derived",
        "source_ref": {
          "kind": "runtime_signal | artifact | receipt",
          "ref": "opaque-source-ref",
          "label": "string"
        }
      }
    ]
  },
  "governance": {
    "pending_proposal_count": 0,
    "pending_receipt_count": 0,
    "latest_receipt_outcome": "success | blocked | logged | partial | rejected | null",
    "authority_role": "derived",
    "source_ref": {
      "kind": "receipt | trace | runtime_signal",
      "ref": "opaque-source-ref",
      "label": "governance summary"
    }
  },
  "guards": {
    "read_only": true,
    "runtime_posture": "healthy | degraded | unavailable | unknown",
    "degraded": false,
    "reasons": [],
    "authority_role": "derived",
    "source_ref": {
      "kind": "status",
      "ref": "api-status-derived",
      "label": "minimal status posture"
    }
  },
  "mutation_intents": []
}
```

## Field Rules

### `scope`

`scope.kind` is always `workspace`. This contract does not describe an active
artifact aggregate and must not be retrofitted onto the existing artifact
workspace response as a compatibility requirement.

`scope.vault_id` and `scope.channel` are safe runtime labels. They must not
include vault roots, DSNs, secrets, or host-local absolute paths.

### `meta`

`meta` describes the whole snapshot.

| Field | Rule |
|---|---|
| `contract_version` | Version label for this payload shape. Initial planned value: `workspace_orientation.v1`. |
| `as_of` | ISO-8601 timestamp for snapshot generation. |
| `trace_id` | Correlation ID for this aggregate read. |
| `freshness` | Snapshot-level freshness only: `fresh`, `stale`, `partial`, or `unknown`. |
| `stale_after` | ISO-8601 timestamp after which the snapshot should be treated as stale by clients. |
| `degraded_reasons` | Snapshot-level list of reason codes when any source resolution is partial or unavailable. |
| `caps` | Server-declared caps. Clients may render caps but must not enforce larger local caps. |

### Bounded Collections

The server owns all collection caps. Phase 1 caps are:

| Collection | Cap | Rule |
|---|---:|---|
| `leave_point` | 1 | One derived-only leave point. No persistence in MVP. |
| `open_loops` | 8 | Summaries only; no raw note body or raw chat history. |
| `notable_changes` | 8 | Bounded summaries of recent deltas; no raw note body. |
| `resurface.candidates` | 5 | Why-now-bearing candidates only. No full retrieval result set. |
| `mutation_intents` | 0 | Phase 1 default is always an empty list. |
| `source_refs_per_item` | 3 | Keep provenance inspectable without expanding into raw logs. |

Implementations may return fewer items. Increasing a cap is a contract change.
The UI must not widen these collections by issuing its own broader read through
this surface.

### `leave_point`

`leave_point` is derived-only in Phase 1. It may point at the last known
artifact or session posture when existing sources can derive one, but it must
not persist a leave-point cursor or create restart-surviving continuity state.

`leave_point.kind` is `derived_only` in Phase 1. Persisted leave-point cursor
storage belongs to later leave-point ADR/implementation work.

### `open_loops`

`open_loops` lists bounded unresolved or interrupted items useful for re-entry.
Items are derived from existing runtime signals, traces, receipts, or durable
artifact metadata. They are not commitments by themselves and must not be
treated as governance authority.

### `notable_changes`

`notable_changes` lists bounded recent changes that may matter for orientation.
Summaries must be short and source-linked. The payload must not include raw note
bodies, raw diffs, raw event logs, or raw embeddings.

### `resurface.candidates`

`resurface.candidates` contains bounded why-now-bearing candidates. Each
candidate explains the server-derived reason it surfaced in `why_now` and
carries provenance through `source_ref`. Resurfacing is an attentional
projection only. It cannot upgrade similarity into urgency, change artifact
meaning, or create durable memory.

Dismiss, snooze, and pin, if the UI offers them later, are UI-local affordances
only in this Phase 1 surface and must not persist through this read path.

### `governance`

`governance` is a small read-side summary: pending counts plus the latest
receipt outcome when existing seams can provide it. It is not a governance
router and not a decision surface.

The UI must render `pending_proposal_count`, `pending_receipt_count`, and
`latest_receipt_outcome` as supplied. It must not classify proposed actions,
derive authority, or infer receipt outcomes locally.

### `guards`

`guards` lets the UI render degraded/partial orientation states without
inventing local policy. It is deliberately minimal.

`runtime_posture` is a derived coarse posture for this snapshot only. Detailed
runtime health, queues, watchers, worker status, and index posture remain owned
by `/api/status` and must not be copied into this payload as dashboard slices.

### `authority_role`

`authority_role` declares the role of an item in the orientation snapshot.
Allowed Phase 1 values:

| Value | Meaning |
|---|---|
| `derived` | Re-derived projection with no authority of its own. Default for orientation items. |
| `supporting` | Source-linked supporting evidence, such as a receipt outcome summary. |
| `reference` | Opaque reference to an artifact, trace, status source, or receipt source. |

The orientation endpoint must not declare itself or its items `authoritative`
for durable semantics, governance, memory, or orchestration.

### `source_ref`

`source_ref` is an opaque, browser-safe provenance pointer. It must be sufficient
for the runtime to explain where an item came from without exposing unsafe raw
material to the browser.

Allowed Phase 1 `source_ref.kind` values:

- `artifact`
- `receipt`
- `trace`
- `runtime_signal`
- `status`
- `derived`

`source_ref.ref` must be an opaque ID or browser-safe reference. It must not be
an absolute vault path, raw event payload, raw chat transcript, raw embedding,
or agent scratchpad.

### `artifact_ref`

When an item refers to an artifact, it uses `artifact_ref`.

| Field | Rule |
|---|---|
| `artifact_id` | Stable artifact identifier when available; `null` when unresolved. |
| `note_path` | Browser-safe runtime-relative note path for deep linking to `/workspace?note_path=...`; never an absolute vault path. |
| `title` | Display title supplied by the runtime; not raw body content. |

## Mutation Intents

`mutation_intents` is present so the payload shape can carry handoff hints
without gaining write authority. In Phase 1 it is always an empty list.

Future non-empty intents, if accepted by later contract work, must follow these
rules:

- The intent is a handoff hint only.
- The target execution surface is explicit, such as Panel/governance.
- The intent carries `authority_role` and `source_ref`.
- The orientation endpoint does not enqueue, execute, persist, or receipt the
  intent.
- MemoryCandidate intents are not part of Phase 1.

## Degraded and Error Payloads

### Partial Source Resolution

Partial source resolution returns HTTP 200 with a degraded snapshot, not a local
UI default. The response must preserve the same payload shape where possible
and include snapshot-level reason codes.

```json
{
  "scope": {
    "kind": "workspace",
    "vault_id": "default",
    "channel": "dev"
  },
  "meta": {
    "contract_version": "workspace_orientation.v1",
    "as_of": "2026-05-31T12:00:00Z",
    "trace_id": "trace-id",
    "freshness": "partial",
    "stale_after": "2026-05-31T12:05:00Z",
    "degraded_reasons": ["resurfacing_source_unavailable"],
    "caps": {
      "open_loops": 8,
      "notable_changes": 8,
      "resurface_candidates": 5,
      "mutation_intents": 0,
      "source_refs_per_item": 3
    }
  },
  "leave_point": null,
  "open_loops": [],
  "notable_changes": [],
  "resurface": {
    "candidates": []
  },
  "governance": {
    "pending_proposal_count": 0,
    "pending_receipt_count": 0,
    "latest_receipt_outcome": null,
    "authority_role": "derived",
    "source_ref": {
      "kind": "derived",
      "ref": "unavailable",
      "label": "source unavailable"
    }
  },
  "guards": {
    "read_only": true,
    "runtime_posture": "degraded",
    "degraded": true,
    "reasons": ["resurfacing_source_unavailable"],
    "authority_role": "derived",
    "source_ref": {
      "kind": "status",
      "ref": "partial",
      "label": "partial source resolution"
    }
  },
  "mutation_intents": []
}
```

Allowed degraded reason codes include:

- `orientation_source_unavailable`
- `resurfacing_source_unavailable`
- `governance_source_unavailable`
- `status_source_unavailable`
- `partial_source_resolution`

### Runtime Unavailable

If the runtime aggregate source cannot be reached at request level, return HTTP
503 with a typed error payload.

```json
{
  "error": "runtime_unavailable",
  "message": "The workspace orientation source could not be reached",
  "trace_id": "trace-id",
  "contract_version": "workspace_orientation.v1"
}
```

Request-level runtime unavailability must not be represented as a successful
fresh snapshot.

## Existing Endpoint Relationship

| Existing endpoint | Relationship |
|---|---|
| `GET /api/companion/workspace?note_path=...` | Artifact-scoped aggregate. Use this after selecting or deep-linking to a note. |
| `GET /api/status` | Runtime health surface. Orientation may use a derived coarse posture only; detailed health stays here. |
| Panel / Canvas write endpoints | Execution surfaces. Orientation may point toward them through future handoff hints but never calls them. |

## Non-goals

- Not durable state.
- Not agent memory.
- Not governance authority.
- Not a source of durable semantic truth.
- Not an orchestration dashboard.
- Not a runtime health dashboard.
- No `orchestration` slice.
- No detailed `runtime` slice for queues, watchers, workers, leases,
  checkpoints, agent messages, or index internals.
- No leave-point persistence in MVP.
- No MemoryCandidate intents in Phase 1.
- No push, streaming, SSE, WebSocket, notification, or ambient resurfacing
  transport.
- No multi-agent semantics.
- No raw vault absolute paths.
- No raw note bodies.
- No raw chat history.
- No raw embeddings.
- No agent scratchpads.
- No memory promotion.
- No WriteGuard mutation.
- No receipt writes.

## Implementation Gate

Implementing `GET /api/companion/orientation` must follow this contract and must
not imply changes to the artifact-scoped workspace endpoint. Runtime
implementation belongs to the follow-on implementation issue for this contract.
