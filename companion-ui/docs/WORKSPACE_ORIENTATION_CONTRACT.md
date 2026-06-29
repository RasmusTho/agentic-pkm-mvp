---
name: Companion UI Workspace Orientation Contract
description: Runtime note-independent read-side contract for the Companion UI workspace orientation endpoint
doc_role: API contract / spec
authority: Binding read-side contract for `GET /api/companion/orientation` and downstream Companion UI re-entry integration.
owner: Companion UI / product architecture
last_reviewed: 2026-06-02
source_contracts:
  - docs/adr/ADR-0007-workspace-state-contract-scope-split.md
  - companion-ui/docs/WORKSPACE_STATE_CONTRACT.md
  - companion-ui/docs/UI_RUNTIME_BOUNDARIES.md
  - docs/adr/ADR-0008-leave-point-cursor.md
  - docs/adr/ADR-0009-orientation-memory-candidate-intent.md
  - docs/adr/ADR-0011-orientation-push-ambient-resurfacing.md
  - docs/adr/ADR-0012-orientation-multiagent-reads.md
  - docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md
  - docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md
  - docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md
governing_issue: "#1451; #1454; #1455; #1457; #1487; #1459"
implementation_state: implemented_phase_3_memory_intent_seam
---

# Workspace Orientation Contract

## Purpose

Define the note-independent read-side orientation snapshot the Companion
UI can use for cold load and re-entry when no artifact is active.

The existing Workspace State Contract remains artifact-scoped:
`GET /api/companion/workspace?note_path=...` requires `note_path` and answers
"what is the state around this artifact?" This contract defines the separate
Workspace Orientation Snapshot at `GET /api/companion/orientation`, which
answers "where am I in the system, what is open, what changed, and what can I
safely resume?"

This document is the contract for the runtime endpoint and Companion UI
re-entry consumption. Phase 2 implemented ADR-0008's leave-point cursor
projection rules as an append-only operational trace pointer. Phase 3 adds
read-only pending MemoryCandidate awareness plus bounded, trace-backed
`MemoryCandidate` handoff intents under ADR-0009. All shipped surfaces remain
read-only projections.

## Scope

This contract is **workspace-scoped** and note-independent.

- Endpoint: `GET /api/companion/orientation`.
- No `note_path` request parameter is required or owned by this surface.
- The response scope envelope is:

```json
{
  "scope": {
    "kind": "workspace",
    "artifact_ref": null,
    "vault_id": "string",
    "channel": "dev | test | prod | unknown"
  }
}
```

`vault_id` is an opaque runtime label. It must not expose an absolute vault
filesystem path. `artifact_ref` is always `null` for this note-independent
workspace surface; artifact references inside the payload may include
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
- The UI renders server-declared `mutation_intents`; it must not classify
  MemoryCandidate-worthiness locally.
- `mutation_intents` are handoff hints only. They must never execute, persist,
  enqueue, write receipts, call WriteGuard, promote memory, or mutate state
  through this read path.
- The Phase 3 endpoint may return bounded `MemoryCandidate` mutation intents
  only when ADR-0009's source, threshold, and trace requirements are satisfied.
  These intents target the review boundary by reference only and do not create
  candidates.
- Every non-trivial item carries `authority_role` and `source_ref`.
- Snapshot freshness is declared at `meta` level only. Per-item freshness fields
  are intentionally excluded to avoid token amplification.
- The endpoint must not expose raw vault absolute paths, raw note bodies, raw
  chat history, raw embeddings, agent scratchpads, or internal orchestration
  state.
- Runtime health remains owned by `/api/status`. This payload may expose only a
  minimal derived guard/degraded posture needed for orientation rendering.
- A leave-point cursor, when implemented by later runtime work, is admissible
  only as an operational trace pointer. The orientation read path may project
  it but must remain read-only, and orientation must remain correct without it.

## `mutation_intents` Rules

`mutation_intents` are handoff hints only. They do not execute, authorize, or
persist mutations.

MemoryCandidate intents are admissible only under
`docs/adr/ADR-0009-orientation-memory-candidate-intent.md`:

- The intent is bounded and reference-only.
- The intent targets the existing MemoryCandidate review queue or its
  implementation successor.
- The intent must include a human-legible reason and source reference, but no
  raw candidate content.
- Intent emission does not create a `MemoryCandidate`.
- Intent emission does not accept, promote, revise, reject, or store memory.
- Intent emission does not write candidate content or semantic workspace state.
- The orientation payload must not include raw candidate content, note bodies,
  chat transcripts, agent scratchpads, embeddings, or accepted memory content.
- The UI may render the server-declared intent and may route explicit user
  action to a later governed path, but it must not classify locally or create
  candidates from the orientation payload.

When orientation emits a MemoryCandidate intent, the backend must record an
operational trace for the emitted intent. That trace records intent emission
only; it is not a governance receipt and must not carry raw candidate content.

## Success Payload

```json
{
  "scope": {
    "kind": "workspace",
    "artifact_ref": null,
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
      "mutation_intents": 3,
      "source_refs_per_item": 3
    }
  },
  "leave_point": {
    "status": "absent | present | stale | artifact_missing | degraded",
    "artifact_ref": {
      "artifact_uuid": "string | null",
      "logical_ref": "relative/path.md | null",
      "title": "string | null"
    },
    "captured_at": "2026-05-31T11:45:00Z | null",
    "last_session_id": "string | null",
    "authority_role": "operational_trace_pointer | derived_runtime_projection",
    "source_ref": {
      "kind": "artifact_activation | canvas_session | session_end | null",
      "trace_id": "trace-id | null"
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
  "memory": {
    "pending_candidate_count": 0,
    "authority_role": "derived",
    "source_ref": {
      "kind": "agent_memory.review_queue",
      "ref": "agent_memory.review_queue",
      "label": "memory candidate review queue"
    }
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
  "mutation_intents": [
    {
      "intent_id": "memory-candidate-intent-resurface-pending-promotions",
      "kind": "MemoryCandidate",
      "target_queue": "agent_memory.review_queue",
      "handoff_hint": "panel_governance_review",
      "reason": "Review queue handoff suggested by multiple independent runtime signals; orientation carries references only and creates no candidate.",
      "authority_role": "reference",
      "source_ref": {
        "kind": "runtime_signal",
        "ref": "status.events",
        "label": "resurfacing signal"
      },
      "threshold_signals": ["pending_promotions=2", "promote_created_total=3"],
      "trace_id": "trace-id"
    }
  ]
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
| `contract_version` | Version label for this payload shape. Current value: `workspace_orientation.v1`. |
| `as_of` | ISO-8601 timestamp for snapshot generation. |
| `trace_id` | Correlation ID for this aggregate read. |
| `freshness` | Snapshot-level freshness only: `fresh`, `stale`, `partial`, or `unknown`. |
| `stale_after` | ISO-8601 timestamp after which the snapshot should be treated as stale by clients. |
| `degraded_reasons` | Snapshot-level list of reason codes when any source resolution is partial or unavailable. |
| `caps` | Server-declared caps. Clients may render caps but must not enforce larger local caps. |

### Bounded Collections

The server owns all collection caps. Current caps are:

| Collection | Cap | Rule |
|---|---:|---|
| `leave_point` | 1 | One leave point. Phase 2 may project an admissible operational trace cursor per ADR-0008. |
| `open_loops` | 8 | Summaries only; no raw note body or raw chat history. |
| `notable_changes` | 8 | Bounded summaries of recent deltas; no raw note body. |
| `resurface.candidates` | 5 | Why-now-bearing candidates only. No full retrieval result set. |
| `mutation_intents` | 3 | Bounded handoff hints only. MemoryCandidate intents require ADR-0009 threshold and trace semantics. |
| `source_refs_per_item` | 3 | Keep provenance inspectable without expanding into raw logs. |

Implementations may return fewer items. Increasing a cap is a contract change.
The UI must not widen these collections by issuing its own broader read through
this surface.

### Cognitive-Load Display Budget

The server-declared caps above are transport ceilings, not a requirement to show
every returned item at once. The Companion UI may render a scarcer displayed
subset to protect the orientation moment from becoming a new working-memory
burden.

Current FA-5 budget posture:

| Budget field | Status | Rule |
|---|---|---|
| `items_per_orientation_moment` | Parametric | Display a scarce subset across `open_loops`, `notable_changes`, and `resurface.candidates`; settings may tune the exact count later, but visible cards must fit the human-first working-memory and screen-space budget before deliberate expansion. |
| `foreground_refresh_frequency` | Parametric | Default to manual pull. If ADR-0011 ambient refresh is enabled, refresh only while the surface is visible/foregrounded and only after server-declared staleness or a later settings-controlled interval that does not create notification pressure. |
| `resurface_salience_threshold` | Parametric | Below threshold, return no candidate or mark the resurfacing slice degraded. Do not show weak material with a confident why-now. |

The UI may offer deliberate expansion or drill-in controls, but it must not turn
overflow into a notification inbox, badge, urgency feed, or queue the human is
expected to process. Display scarcity must not silently reorder canonical user
artifacts or imply priority, urgency, approval, memory promotion, or action
authorization.

Parametric settings must not override footprint constraints. When card footprint,
available screen space, or reading/working-memory load would make the orientation
moment heavy, the implementation should choose the smaller displayed subset and
leave additional items behind a deliberate expansion affordance.

### `leave_point`

`leave_point` may point at the last known artifact or session posture when
existing sources can derive one. ADR-0008 admits a leave-point cursor only as
bounded operational trace; it is not restart-surviving semantic continuity
state.

The orientation endpoint may read and project that cursor, but the read path
must not write it. Orientation must remain correct without the cursor.

The structured `leave_point` shape is:

| Field | Rule |
|---|---|
| `status` | One of `absent`, `present`, `stale`, `artifact_missing`, or `degraded`. `present` requires either a valid derived projection or an admissible current operational trace pointer. |
| `artifact_ref.artifact_uuid` | Primary artifact identity when known. Paths, titles, hashes, and session IDs must not become primary identity. |
| `artifact_ref.logical_ref` | Optional browser-safe logical reference such as a runtime-relative note path. It must not be an absolute filesystem path. |
| `artifact_ref.title` | Optional display title derived from the current artifact source. It is projection data, not identity. |
| `captured_at` | Capture time from the admissible cursor, or derived interaction time when no cursor is used. `null` when absent or degraded. |
| `last_session_id` | Optional runtime session correlation. It is not session truth and must not authorize workflow resume. |
| `authority_role` | `operational_trace_pointer` when projected from an admissible cursor; `derived_runtime_projection` when derived without a current cursor. |
| `source_ref.kind` | One of `artifact_activation`, `canvas_session`, `session_end`, or `null` for cursor projection. |
| `source_ref.trace_id` | Trace correlation for the source event when available. |

Cursor projection rules:

- `vault_id` and `channel` must match the current orientation scope.
- `artifact_uuid` must be present and treated as primary identity.
- `trace_id` and `source_ref` are required on the underlying cursor.
- The source must be an allowed runtime capture source.
- Expired, corrupt, or wrong vault/channel cursors are ignored.
- A content-hash mismatch marks `leave_point.status = "stale"`, never current.
- A missing artifact marks `leave_point.status = "artifact_missing"`.
- Source degradation marks `leave_point.status = "degraded"` or falls back to fresh derived orientation.

The cursor is not memory, durable workspace state, session truth, a governance
receipt, a workflow resume command, UI-owned state, or a vault artifact. It must
not carry body content, excerpts/snippets/headings, summaries, diffs,
embeddings, working-set snapshots, open tabs, editor selection, scroll
position, raw chat history, agent scratchpads, memory candidates, accepted
memory content, governance decisions, receipts, WriteGuard outputs, absolute
filesystem paths, UI layout state, orientation summaries, or resurfacing
candidates.

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

`why_now` must be pointer/provenance-first and bounded. The minimal shape is:

- trigger: the server-declared signal that caused the item to surface, such as a
  leave-point return, related current artifact, new activity, or unresolved open
  loop;
- source: `source_ref` pointing to the artifact, trace, receipt, or runtime
  signal backing the resurfacing decision;
- relevance basis: a short human-checkable relation, not a persuasive generated
  rationale;
- confidence/degradation: either an honest signal label/confidence posture or a
  degraded/omitted candidate when the signal is weak.

Cards must be short, self-contained, pointer-first, source-linked, and
TTS-ready. They should help the human decide whether to inspect the source; they
must not embed raw note bodies, raw diffs, raw event logs, raw embeddings, or
long generated explanations. A resurfaced item is not priority, urgency,
approval, memory promotion, or write authority.

Dismiss, snooze, and pin, if the UI offers them later, are UI-local affordances
only and must not persist through this read path.

### `memory`

`memory` exposes read-only awareness of the existing MemoryCandidate review
boundary. The current shipped field is `pending_candidate_count` only. It is a
count/surface-awareness field, not candidate content, memory recall, memory
authority, or a durable state transition.

The orientation endpoint must not expose MemoryCandidate titles, content,
source refs from queued candidates, accepted memory content, or review decisions
through this field. It must not create, enqueue, accept, promote, reject, revise,
or store memory while reading this count.

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
Allowed values:

| Value | Meaning |
|---|---|
| `derived` | Re-derived projection with no authority of its own. Default for orientation items. |
| `derived_runtime_projection` | Leave-point projection derived without a current operational trace cursor. |
| `operational_trace_pointer` | Leave-point projection from an admissible ADR-0008 cursor. This is not durable workspace state or session truth. |
| `supporting` | Source-linked supporting evidence, such as a receipt outcome summary. |
| `reference` | Opaque reference to an artifact, trace, status source, or receipt source. |

The orientation endpoint must not declare itself or its items `authoritative`
for durable semantics, governance, memory, or orchestration.

### `source_ref`

`source_ref` is an opaque, browser-safe provenance pointer. It must be sufficient
for the runtime to explain where an item came from without exposing unsafe raw
material to the browser.

Allowed `source_ref.kind` values:

- `artifact`
- `agent_memory.review_queue`
- `receipt`
- `trace`
- `runtime_signal`
- `status`
- `derived`
- `artifact_activation`
- `canvas_session`
- `session_end`

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

### `recents_anchor`

`recents_anchor` is an optional server-declared **Find/recency projection** — the most recently edited vault note at the time the orientation snapshot was generated.

It is explicitly **NOT** a `leave_point` and carries **NO** continuity semantics. The field is omitted (`null`) when the vault is empty, unreadable, or the runtime chooses not to declare it.

Rules:

- Declared by the runtime only. The UI must not derive this field via a local filesystem `mtime` probe; that would violate the "no direct vault I/O from the UI" invariant and re-open the host-vs-container mount hazard (ADR-0014, #2141).
- The UI renders it as a labeled sub-affordance ("Open your most recent note") on the `cold_start` threshold's Find verb, routing via the existing `/workspace?note_path=…` path.
- The UI must **never** auto-open this path on mount; it is an affordance only.
- The UI must **omit the sub-affordance entirely** when the field is absent.
- Deterministic tiebreak: when multiple notes share the same `mtime`, the lexicographically first path (ascending) wins, ensuring stable server-side resolution.
- **Human notes only.** Machine-config files are excluded from the candidate set: the system directory (`VAULT_SYSTEM_DIR_REL`, companion notes and other machine artefacts) and the committed Design-Handoff `settings/` scaffold (`vault.md`, `local.md`, …). The orientation entry projection only runs for an initialized vault (which always carries that scaffold, #2653), so a settings file must never surface as "your most recent note". Notes whose only available label is a bare UUID stem are likewise skipped to the next valid human note.

Shape:

| Field | Rule |
|---|---|
| `note_path` | Browser-safe runtime-relative note path; never an absolute vault path. Used to form the `/workspace?note_path=…` deep-link. |
| `display_label` | Display label derived from the note's first H1 heading, or its filename stem when no heading is present. Not raw body content. |

Example:

```json
"recents_anchor": {
  "note_path": "Projects/current-work.md",
  "display_label": "Current Work"
}
```

Governing issue: #2176. Operator decision to adopt: Q1 in `companion-ui/design_handoff/2026-06-19-cold-start-threshold/open-questions.md`.

## Mutation Intents

`mutation_intents` is present so the payload shape can carry handoff hints
without gaining write authority. Phase 3 may return structured
`MemoryCandidate` intents under ADR-0009.

Current structured intent fields are:

| Field | Rule |
|---|---|
| `intent_id` | Opaque deterministic ID for the emitted handoff hint. |
| `kind` | Currently `MemoryCandidate`. |
| `target_queue` | Existing review boundary, currently `agent_memory.review_queue`. |
| `handoff_hint` | UI routing hint, currently `panel_governance_review`; not an execution command. |
| `reason` | Human-legible bounded reason grounded in explicit signals; no raw candidate content. |
| `authority_role` | Always `reference`; the intent is not semantic or governance authority. |
| `source_ref` | Browser-safe provenance pointer to the source item that met the threshold. |
| `threshold_signals` | Bounded list of independent signal labels that satisfied ADR-0009. |
| `trace_id` | Correlation ID for the orientation read and emitted trace event. |

Non-empty intents follow these rules:

- The intent is a handoff hint only.
- The target execution surface is explicit, such as Panel/governance.
- The intent carries `authority_role` and `source_ref`.
- The orientation endpoint does not enqueue, execute, persist, or receipt the
  intent.
- MemoryCandidate intents do not create MemoryCandidates; candidate creation,
  review, promotion, rejection, and revision remain governed downstream paths.

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
      "mutation_intents": 3,
      "source_refs_per_item": 3
    }
  },
  "leave_point": null,
  "open_loops": [],
  "notable_changes": [],
  "resurface": {
    "candidates": []
  },
  "memory": {
    "pending_candidate_count": 0,
    "authority_role": "derived",
    "source_ref": {
      "kind": "derived",
      "ref": "unavailable",
      "label": "memory source unavailable"
    }
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
- `memory_source_unavailable`
- `memory_intent_trace_unavailable`
- `governance_source_unavailable`
- `status_source_unavailable`
- `partial_source_resolution`
- `leave_point_stale`
- `leave_point_artifact_missing`
- `leave_point_source_degraded`

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
- No leave-point persistence. Phase 2 reads and projects only the bounded
  operational trace cursor admitted by ADR-0008.
- MemoryCandidate intents are Phase 3 handoff hints only; they do not create,
  enqueue, review, promote, reject, revise, or store memory.
- No push, streaming, SSE, WebSocket, notification, or server-initiated ambient
  resurfacing transport in the current implementation. The Companion UI re-entry
  surface may opt into the ADR-0011 foreground ambient refresh slice with
  `COMPANION_ORIENTATION_AMBIENT_REFRESH=1`; that refresh is client-initiated,
  read-only, default-off, and based only on server-declared `meta.freshness` /
  `meta.stale_after` metadata.
- No multi-agent semantics in the current implementation. Future multi-agent
  read eligibility is governed by ADR-0012 and remains unimplemented.
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
not imply changes to the artifact-scoped workspace endpoint. The current
implementation is limited to the read-only orientation shape in this contract.
Leave-point cursor projection is governed by ADR-0008. MemoryCandidate intent
emission is governed by ADR-0009. Push transport and multi-agent semantics
remain out of scope. ADR-0011 permits only the bounded, default-off,
client-initiated foreground ambient refresh implemented behind
`COMPANION_ORIENTATION_AMBIENT_REFRESH=1`; it does not authorize server push,
SSE, WebSocket, notifications, background wakeups, badges, counters, banners,
or urgency feeds.
ADR-0012 permits only a future bounded same-projection read path for agent
consumers; it does not authorize shared mutable workspace state, A2A routing,
or orchestration semantics.

The Companion UI re-entry surface consumes this endpoint on cold load or
when no artifact is active. It renders only server-declared fields, uses
runtime-relative artifact refs for `/workspace?note_path=...` deep links, and
does not issue mutation calls from the re-entry surface.
