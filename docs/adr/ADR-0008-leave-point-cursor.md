State: Implemented — runtime behavior shipped in PR #1464 (merge commit 3fe0cc29). Scope-filter hardening applied in PR #1465.

# ADR-0008: Leave-Point Cursor as Bounded Operational Trace

**Date:** 2026-05-31
**Status:** Implemented — shipped in PR #1464 (merge commit `3fe0cc29`)

---

## Context

ADR-0007 splits the Workspace State Contract into an artifact-scoped snapshot and a note-independent Workspace Orientation Snapshot. It also identifies one non-derivable re-entry fact: which artifact the human last focused. Losing that fact after process restart weakens restart continuity, but persisting it carelessly would violate the runtime/durable boundary by creating hidden mutable workspace state.

The boundary-sensitive question is whether a leave-point cursor is admissible at all, and if so where it may live. This ADR decides that question for issue #1454. Runtime implementation remains downstream work in #1455.

## Decision

Accept a leave-point cursor, but only as an append-only operational trace pointer.

The leave-point cursor is admissible only as bounded operational trace. It is not memory. It is not durable workspace state. It is not session truth. It is not a governance receipt. It is not a workflow resume command. It is not UI-owned state. It is not a vault artifact.

`GET /api/companion/orientation` may read and project it, but must remain read-only. Orientation must remain correct without it. Loss, expiry, corruption, cross-scope mismatch, missing artifact, or source degradation must fall back to fresh derived orientation.

### Storage model

- Owner storage class: runtime trace substrate.
- Implementation may use a DB-backed append-only trace table/event projection.
- Do not authorize an authoritative mutable "current cursor" row.
- Do not authorize vault-side storage.
- Expired cursor rows may be pruned as operational trace retention, but pruning must not change durable meaning or correctness.

### Strict allowed fields

Only these fields are allowed:

- `cursor_version`
- `event_type`: `workspace.leave_point.captured.v1`
- `vault_id`
- `channel`
- `artifact_uuid`
- `captured_at`
- `expires_at`
- `last_session_id`
- `trace_id`
- `source_ref.kind`: `artifact_activation | canvas_session | session_end`
- `source_ref.ref_id`
- `content_hash_at_capture`: nullable
- `capture_reason`: `artifact_focus | artifact_interaction | session_end`

### Forbidden fields

The cursor must not contain:

- note body
- excerpts/snippets/headings
- summaries
- diffs
- embeddings
- working-set snapshots
- open tabs
- editor selection
- scroll position
- raw chat history
- agent scratchpads
- memory candidates
- accepted memory content
- governance decisions
- receipts
- WriteGuard outputs
- absolute filesystem paths
- UI layout state
- orientation summaries
- resurfacing candidates

### TTL and retention

- Default TTL: 72 hours.
- Hard maximum TTL: 7 days unless a later ADR changes the retention class.
- An expired cursor is ignored as current evidence and may be pruned.

### Validation and failure semantics

- `vault_id` and `channel` must match the current orientation scope.
- `artifact_uuid` is the primary identity. Paths, titles, hashes, and session IDs must not become primary identity.
- `trace_id` and `source_ref` are required.
- `source_ref.kind` must be one of the allowed runtime capture sources.
- A `content_hash_at_capture` mismatch marks the leave point stale, never current.
- A missing artifact marks the projected leave point `artifact_missing`.
- A corrupt cursor is ignored; the read path may scan for the next admissible event.
- A wrong vault/channel cursor is ignored.

### Orientation projection contract

The Workspace Orientation Snapshot projects a structured `leave_point`:

```json
{
  "status": "absent | present | stale | artifact_missing | degraded",
  "artifact_ref": {
    "artifact_uuid": "string | null",
    "logical_ref": "string | null",
    "title": "string | null"
  },
  "captured_at": "iso8601 | null",
  "last_session_id": "string | null",
  "authority_role": "operational_trace_pointer | derived_runtime_projection",
  "source_ref": {
    "kind": "artifact_activation | canvas_session | session_end | null",
    "trace_id": "string | null"
  }
}
```

The projection is not itself authoritative. `authority_role = "operational_trace_pointer"` means the field came from an admissible trace pointer. `authority_role = "derived_runtime_projection"` means the read path derived a best-effort leave point without relying on a current trace pointer.

## Rejected alternatives

### Option A: No cursor

Safe, because orientation stays entirely derived and discardable. Rejected for Phase 2 because it provides weaker restart continuity: the single non-derivable focus fact is lost on process restart.

### Option C: Mutable DB/runtime current row

Rejected. A mutable "current cursor" row would become hidden mutable workspace state and would invite consumers to treat it as session truth.

### Option D: Vault-side cursor artifact

Rejected. Vault-side storage would leak runtime re-entry state into the durable human surface and create a false durable artifact.

### Option E: Session-log derived primary cursor

Rejected as the primary model because it is incomplete and costly. Session logs may be used only as a possible auxiliary derivation if separately scoped and if the resulting projection still satisfies this ADR.

## Consequences

Positive:

- Restart continuity can improve without changing the runtime/durable boundary.
- The cursor has a strict schema, short retention, scope validation, and discardability semantics.
- Orientation remains read-only and correct without a cursor.

Costs and risks:

- #1455 must implement an append-only trace interpretation rather than a convenient mutable "current" store.
- Consumers must handle `absent`, `stale`, `artifact_missing`, and `degraded` as normal states.
- Future retention expansion requires a later ADR because the cursor is admitted only under bounded trace retention.

## Implementation constraints for #1455

#1455 may implement this ADR, but this ADR does not implement runtime code. This docs-only decision change adds no migration, API code, or runtime tests. Downstream code must preserve the read-only orientation path and must not broaden the field set without another ADR.

## References

- Issue #1454: leave-point cursor storage + admissibility
- Issue #1455: downstream runtime implementation
- `docs/adr/ADR-0007-workspace-state-contract-scope-split.md`
- `docs/research/workspace-state-contract-v61-architecture-memo.md`
- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md`
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`
