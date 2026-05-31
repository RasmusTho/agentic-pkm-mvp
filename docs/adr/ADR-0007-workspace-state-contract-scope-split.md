State: Proposed — decision recorded, pending acceptance. No runtime behavior is claimed; the orientation surface is planned, not shipped.

# ADR-0007: Workspace State Contract — artifact-scoped vs note-independent scope split

**Date:** 2026-05-31
**Status:** Proposed — decision recorded; orientation surface is v6.1 target work, not shipped

---

## Context

The repo already has a Workspace State Contract. `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md` (governing issue #1122) defines `GET /api/companion/workspace?note_path=<path>` as a read-side aggregate: given one note, return its body/identity plus Canvas session posture, Panel posture, suggestion posture, guard status, and read-only `reorient`/`resurface` projections. `note_path` is a **required** parameter. The runtime backing it (`app/api/routes/companion.py`) composes the aggregate at request time from independent sources, two of which — `build_orientation_frame()` (`app/orientation/runtime.py`) and `evaluate_resurfacing_candidates()` (`app/resurfacing/runtime.py`) — are already **note-independent**, deterministic, query-independent, and declare `read_only = True` with a `mutation_intents: list[str]` channel that proposes but never executes.

The v6.1 forward line (`docs/ROADMAP.md`, v6.1+) calls for operational-cognition capabilities: orientation after long absence, re-entry, runtime continuity, resumable cognition, and a safe seam toward agent memory. These needs must work **when no note is open** — the human re-entering the system needs to know where they were, what is unresolved, and what is safe to resume *before* any artifact is loaded.

That capability cannot be served by the current contract, because `note_path` is mandatory. There is therefore a structural gap, and the tempting-but-wrong fix is to widen the artifact aggregate into a single global "workspace" god-object. That path leads to authority leakage, hidden runtime/memory accumulation, dashboard drift, and a cache that drifts from truth — all explicitly prohibited by `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md` (#1368).

This ADR is informed by an architecture memo (`docs/research/workspace-state-contract-v61-architecture-memo.md`) and a cross-model synthesis review.

---

## Decision

The project will **preserve the existing artifact-scoped Companion Workspace Contract and introduce a separate, note-independent Workspace Orientation Contract** for v6.1 re-entry and continuity. The Workspace State Contract is two read-side projections with explicit scope, not one widening aggregate.

1. **Artifact Workspace Snapshot (shipped, unchanged):** `GET /api/companion/workspace?note_path=<path>` remains artifact-scoped. It keeps its mandatory `note_path` and its current payload. #1122 stands.

2. **Workspace Orientation Snapshot (planned, v6.1):** a new note-independent surface at **`GET /api/companion/orientation`**. It exists when no artifact is open and answers: *where am I, what is open, what changed, what can I safely resume?*

   The flat path `/api/companion/orientation` is chosen over `/api/companion/workspace/orientation` deliberately: orientation is **not** a sub-resource of an artifact workspace; it exists precisely when no artifact workspace is active. A hierarchical path would re-encode the scope confusion this ADR removes.

3. **Shared invariants for both surfaces:**
   - Read-only. Both may emit `mutation_intents` (proposals with Panel/governance handoff hints); neither applies them, persists semantics, mutates sessions, writes receipts, or touches WriteGuard.
   - Bounded. Every collection is capped (top-N candidates, summaries not bodies, counts not lists). The contract owns the caps; the UI does not.
   - Provenance-bearing. Every non-trivial item carries `authority_role` and `source_ref`. Freshness/staleness is declared **at snapshot level** (`as_of`, `freshness`, `stale_after`, `source_watermarks`, `degraded_reasons`) — not per item — to avoid token amplification.
   - Server-declared classification only. The UI renders; it never classifies governance/authority locally.
   - Snapshot is the recovery path. State is re-derived per read; nothing the contract holds must survive a restart for correctness.

4. **Scope envelope.** The new Workspace Orientation payload **must** carry an explicit scope envelope:
   ```jsonc
   "scope": { "kind": "artifact | workspace", "artifact_ref": "… | null", "vault_id": "…", "channel": "dev | test | prod" }
   ```
   This is a hard requirement only for the **new** orientation surface. The shipped artifact-scoped payload (`WorkspaceStateResponse` in `app/api/routes/companion.py`) does **not** carry `scope` today and is **not** retroactively made non-compliant by this ADR — its scope is implied by the mandatory `note_path`. Adding the envelope to the artifact payload is an optional **future/compatibility-phase additive** (it would need its own implementation issue), not a Phase 0 obligation.

5. **Leave-point cursor (strict):** the single persisted continuity datum is a **reference only** — `artifact_uuid + captured_at + last_session_id`. It carries no body content, no working-set snapshot, no derived state. It is classified as an **operational trace** (`RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`), never a durable semantic artifact and never durable session state. Its loss degrades to "fresh orientation," never to incorrectness. (Phase 2 — see below.)

6. **Explicitly out of scope for v6.1:** no `orchestration` slice (active runs, leases, checkpoints, agent messages) and no `runtime` health/queues/watchers/index sub-tree in the orientation payload. Multi-agent coordination is Phase 4+ work; runtime health is owned by `/api/status`. The orientation surface may carry at most a single derived `runtime_posture: healthy | degraded` field by reference. This keeps the surface an orientation substrate, not a dashboard or a coordination authority.

---

## Consequences

**Positive**

- Ships the missing v6.1 capability (re-entry with nothing open) by exposing derivers that already exist and already declare themselves read-only — minimal new code, zero safety-property change.
- Keeps the artifact contract (#1122) stable; no breaking change to current Companion UI integration.
- Makes the prohibited failure modes (god-object, hidden state, memory dump, dashboard drift) architecturally hard rather than relying on discipline.

**Negative / costs**

- Two endpoints to document and test instead of one.
- A small persisted trace (leave-point cursor) is introduced in Phase 2; it must be governed strictly as trace to avoid becoming hidden session state.

**Phased path**

- **Phase 0 (this PR):** name the scope split in the owner docs (`WORKSPACE_STATE_CONTRACT.md`, `RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`) and record this ADR. Docs/governance lane; no runtime change.
- **Phase 1:** expose `GET /api/companion/orientation` over the existing note-independent derivers (no persisted state, no leave-point cursor yet). This is the v6.1 MVP.
- **Phase 2:** add the strict leave-point trace cursor for restart-surviving re-entry.
- **Phase 3:** wire `mutation_intents` → MemoryCandidate review queue (read-only awareness + intent emission only; no write authority).
- **Phase 4 (deferred, separate ADRs):** push/ambient resurfacing; multi-agent reads.

---

## Open questions deferred to later ADRs

- Leave-point cursor storage medium (DB trace row vs derived-only) — boundary-contract decision (#1368/#1369).
- Working-set cap value and whether it is a contract constant or policy-configurable.
- MemoryCandidate intent threshold and whether intent emission itself needs a trace/receipt (#1085 adjacency).
- Push/streaming enforcement of the "no notification-centric interaction" constraint (`UI_RUNTIME_BOUNDARIES.md`).

---

## References

- `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md` (#1122)
- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md` (#1368)
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`
- `docs/research/workspace-state-contract-v61-architecture-memo.md`
- `app/orientation/runtime.py`, `app/resurfacing/runtime.py`, `app/api/routes/companion.py`
