State: Research memo (architecture analysis + design proposal for the Workspace State Contract toward v6.1). Not a normative contract. Does not change shipped reality.

# Workspace State Contract — v6.1 Architecture Memo

Doc role: research / architecture analysis
Authority: none (analysis input). Normative ownership stays with `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md` (#1122) and `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md` (#1368).
Last reviewed: 2026-05-31
Anchored against: `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md`, `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md`, `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`, `docs/CONCEPTS/STATE_AXES_CONTRACT.md`, `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`, `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`, `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`, `app/api/routes/companion.py`, `app/orientation/runtime.py`, `app/resurfacing/runtime.py`, `app/observability/status_service.py`.

---

## 1. Executive summary

The repo already has a Workspace State Contract. `companion-ui/docs/WORKSPACE_STATE_CONTRACT.md` (governing #1122) defines `GET /api/companion/workspace?note_path=<path>` as a **read-side, artifact-scoped, query-composed aggregate**: given one note, return its body/identity plus Canvas session posture, Panel posture, suggestion posture, guard status, and read-only `reorient`/`resurface` projections. The shipped runtime backs this with deterministic, query-independent derivers (`build_orientation_frame`, `evaluate_resurfacing_candidates`) that already expose the right safety shape — `read_only = True` and a `mutation_intents: list[str]` channel that proposes but never executes.

The v6.1 research target ("runtime continuity, orientation after long absence, future agent memory") is **not the same object**. It is **workspace-scoped, not note-scoped**, and it must exist *before and between* notes — when nothing is open, the human still needs to know where they were, what is unresolved, and what to resume. The single most important finding in this memo:

> **The current contract conflates two scopes under one endpoint name.** `note_path` is a mandatory parameter, so today there is no "workspace state" when no artifact is loaded. The v6.1 capability the prompt describes lives precisely in that gap.

The recommendation is therefore **not** to build a bigger aggregate. It is to **split the contract along its real authority and lifecycle seams**:

1. Keep the shipped artifact-scoped aggregate (`/companion/workspace?note_path=`) exactly as-is — it is correct for what it does.
2. Add a **note-independent orientation surface** (`/companion/orientation` or `/companion/workspace` with no `note_path`) that is a pure deterministic projection over durable artifacts + operational traces.
3. Elevate the existing `read_only + mutation_intents` pattern to the **core invariant** of the whole contract: workspace state is a *projection that may propose, never a store that mutates*.
4. Keep the contract **stateless and re-derivable by default**, persisting only a tiny bounded set of "leave-point" cursors that genuinely cannot be reconstructed (and classifying those as traces, not durable semantics).

This preserves determinism, local-first operation, the runtime/durable boundary, and human trust, and it gives agent-memory and multi-agent work a safe seam (intents → governance → receipt) without ever letting workspace state become hidden cognition.

---

## 2. Architectural analysis (where we actually are)

### 2.1 The shipped object

`app/api/routes/companion.py` composes the aggregate at request time from independent sources:

- `build_orientation_frame()` / `get_orientation_signals()` — derives a leave-point, open items, and notable changes from `OrientationSignals` (event counts, ingestion timing, worker-queue depth) held in `app/observability/status_service.py`.
- `evaluate_resurfacing_candidates()` — explicitly documented in-code as *"query-independent and read-only"*; produces why-now-bearing candidates from the same signal snapshot.
- `receipts_for_artifacts()` — artifact-scoped accountability records.
- Canvas session registry (in-memory), Panel state, WriteGuard status, artifact identity resolution.

Two of these (orientation, resurfacing) are already **note-independent** — they take a signal snapshot, not a `note_path`. They are being delivered *through* a note-scoped envelope they don't actually need. That is the seam evidence: the v6.1 surface is half-built and trapped inside the wrong scope.

### 2.2 State taxonomy (grounded in the existing boundary contract)

`docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md` already classifies "Workspace state" as *Runtime Projection / UI projection — an aggregate view, a projection, not a durable artifact*. The prompt asks for finer partitions; mapping them onto the existing categories:

| Prompt category | Maps to repo category | Durable? | In the contract? | Authority |
|---|---|---|---|---|
| Durable state | Durable semantic artifact | yes | **referenced, never owned** | authoritative |
| UI projection state | UI state / overlay | no (discardable) | yes (read-only) | none |
| Ephemeral runtime state | Runtime/session/workflow state | no | partly (posture summaries) | none |
| Cognitive state | Activation state + salience overlay | no (re-derivable) | yes (derived only) | none (never a gate) |
| Governance state | Proposal staging + receipts | staging: no / receipts: yes | yes (counts + outcomes) | proposal-bearing / authoritative |
| Orchestration state | AgentState / workflow progress | no | **deliberately excluded in v6.1** | none |

The taxonomy already exists and is sufficient. The contract's job is **projection and partitioning**, not introducing a new state class. Anything the contract would need to *invent and store* is a red flag that durable state is being smuggled into a projection.

### 2.3 Canonical vs derived vs out-of-scope

- **Canonical (referenced, owned elsewhere):** note bodies/identity (`FRONTMATTER.md`), `review_state`/`maturity` axes (`STATE_AXES_CONTRACT.md`), accepted agent memory (`AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`), receipts (`RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`). The contract **links** to these; it must never restate them as fields the UI could mistake for source.
- **Derived (the contract's actual product):** orientation frame, resurfacing candidates, salience/zone overlays, Panel/Canvas posture summaries, guard status, bounded working set. All re-derivable; losing them costs convenience, not meaning.
- **Out of scope entirely:** raw AgentState, raw event log, full retrieval result sets, internal LLM routing/traces, absolute vault filesystem paths, multi-step workflow internals. These belong to observability, the orchestrator, and trace surfaces — not the orientation contract.

---

## 3. Architectural role and style

### 3.1 Role

The contract should be understood as an **orientation substrate**, not a nervous system. "Nervous system" implies a write-bearing coordination bus; that role belongs to events/outbox and governance. The workspace contract is the **read-side projection the human (and, later, agents) consult to answer "where am I, what's open, what changed, what should I resume."** It is a *coordination read*, not a *coordination authority*.

### 3.2 Style comparison

| Style | Determinism | Latency | Replayability | Complexity | Token churn | Fit |
|---|---|---|---|---|---|---|
| **Query-composed runtime view** (current) | High (pure derivation) | Recompute per call | High | Low | Recompute cost per read | **Best default** |
| Centralized aggregation endpoint | Medium | Low after warm | Medium | Medium | Risk of fat payload | Acceptable if bounded |
| Event-derived projection (materialized) | Medium (depends on replay) | Low read | High *iff* deterministic fold | High | Low read churn | Only where re-derivation is too slow |
| Materialized state graph | Low (mutable store drifts) | Low | Low | High | Low | **Reject** — becomes hidden state |
| Hybrid: deterministic recompute + bounded persisted cursors | High | Low–medium | High | Medium | Low | **Recommended target** |

**Recommendation:** stay query-composed/deterministic-recompute as the spine (it is what makes the surface trustworthy and replayable on a local-first single process), and add only a **bounded persisted cursor set** for the irreducible "leave-point" facts (last active artifact, last interaction timestamp, last session id) that cannot be re-derived after a process restart. Classify that cursor set as an **operational trace**, never durable semantics — consistent with the boundary contract's "session logs may be a durable receipt/trace; classify explicitly."

The materialized state graph is the trap: it is the SaaS-dashboard answer, and it directly violates "no hidden mutable cognition state."

---

## 4. Authority and governance boundaries

The governing invariant, promoted from the shipped seam pattern (`read_only=True`, `mutation_intents=[]`):

> **The Workspace State Contract has zero write authority. It may project state and emit `mutation_intents`; it may never apply them, persist semantics, mutate sessions, write receipts, or touch WriteGuard.** Every actionable item carries a Panel/governance *handoff hint*, not an execution.

Concrete boundary rules:

- **May write authoritative state:** nobody, via this contract. Authoritative writes stay in the human surface + governed write path (`write_note_from_absolute` behind `DEFAULT_WRITE_GUARD`, producing a receipt). The path is always `runtime value → proposal → governance → receipt → durable artifact`.
- **May only derive/project:** orientation, resurfacing, salience, posture summaries, working set.
- **Append-only:** receipts and traces, owned by their subsystems; the contract reads counts/outcomes, never appends.
- **Requires receipts:** any transition from a workspace-surfaced intent into a durable change — but that receipt is produced by the executing path (Panel/Canvas), not by the workspace read.
- **Must survive restart:** only durable artifacts + receipts (already durable). The contract itself holds nothing that must survive; the bounded cursor set is best-effort trace, and its loss degrades to "fresh orientation," never to incorrectness.

Subsystem interactions:

- **Governance router (`app/chat/governance_router.py`):** the contract reports staged-proposal counts and latest receipt outcome; it does not classify actions or route them. The existing rule "UI must not infer Panel action classes / governance categories locally" extends unchanged.
- **Receipts vs operational traces:** the contract surfaces *receipts* (human-legible outcomes) as first-class fields, and treats the leave-point cursors as *traces* — never conflating the two, per `RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`.
- **Memory candidates:** the contract may *surface* that candidates exist and *emit* a "consider as memory" intent; it must not create, accept, or store candidates (see §6).
- **Contextualization lifecycle:** activation/working-set is reported as derived attention only; it is recorded for audit in the bundle receipt, never written back onto the source artifacts.

---

## 5. Runtime semantics

### 5.1 Pull, snapshot, deterministic — by default

- **Pull over push:** the human/UI requests orientation when re-entering. Push/streaming is a later optimization for ambient resurfacing, gated behind explicit need; it must not become a notification firehose (`UI_RUNTIME_BOUNDARIES.md`: "no notification-centric interaction").
- **Snapshot over incremental:** each read returns a coherent snapshot with a `trace_id` and `generated_at`. Incremental diffs are an optimization, not the contract.
- **Deterministic recomputation over persisted runtime state:** the same signal snapshot must yield the same projection. This is already true of the shipped derivers and is the property that makes the surface auditable.

### 5.2 The runtime concerns, partitioned

| Concern | Treatment |
|---|---|
| Active note context | Cursor (`active_artifact_ref`) — bounded trace, re-pointable, loss → "no active note" |
| Active sessions | Reported posture from session registry; `session_persistence: in_memory` honestly declared |
| Interrupted workflows | Surfaced as **open loops** (orientation already computes "intents created but not executed"); never auto-resumed |
| Resumable cognition | A re-entry frame: leave-point + open loops + notable changes; deterministic from traces |
| Resurfacing candidates | Derived, why-now-bearing; dismiss/snooze/pin are UI affordances the contract does **not** persist (current contract already says this) |
| Pending governance actions | Counts + latest outcome only; action stays in Panel |
| Orientation hints | Derived; each carries a source link |
| Bounded working set | Explicit cap (see §7 token amplification); the contract enforces bounds, not the UI |
| Stale/expired state | Each derived block carries `generated_at`; staleness is surfaced, never silently trusted (`TEMPORAL_VALIDITY_AND_STALENESS_CONTRACT.md`) |
| Conflict resolution | Read side has no conflicts to resolve; `content_hash` remains the stale-read baseline for the *write* path, unchanged |

### 5.3 Resumability without durable runtime state

The "orientation after long absence" capability is satisfiable almost entirely by **re-derivation over durable + trace sources**: recent receipts, recent vault deltas (mtime/ingestion), open promotion/worker loops. The only genuinely non-derivable fact is *"which artifact the human last had focused"* — hence the single small cursor. This keeps resumability strong while keeping persisted runtime state near zero.

---

## 6. Agent-memory interaction (the highest-risk seam)

Agent-memory candidate/review/promotion/recall slices are shipped (#1079–#1083; companion-aware #1085 pending). The danger the prompt names is real and specific: the workspace surface is the most tempting place to quietly accumulate cognition.

Safe boundary pattern:

- **Workspace state reads memory; it never writes it.** It may surface accepted memory as orientation context and may surface *that candidates are pending review*.
- **The contract emits `MemoryCandidate` intents, it does not create candidates.** A "this seems worth remembering" signal is a `mutation_intent` routed to the candidate review queue (`docs/AGENT_MEMORY/ADD_MEMORY_CANDIDATE_REVIEW_QUEUE.md`), where the existing human/authority gate applies. Acceptance is the durable transition, with a receipt.
- **No implicit accumulation.** The contract must not maintain a growing "session memory" blob. Salience/working-set are re-derived each read and bounded; nothing persists as opaque hidden state.
- **Salience stays an overlay, never a gate** (`SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md`). Resurfacing ranking influences attention only; it cannot upgrade similarity into urgency or change artifact meaning.

The litmus test: *if discarding the entire workspace projection loses any meaning, something durable was misfiled into it.* That test must pass at all times.

---

## 7. Failure and risk analysis

| Failure mode | Mechanism | Mitigation |
|---|---|---|
| **Scope conflation** | One endpoint serves note-scoped and workspace-scoped needs; workspace orientation can't exist with no note open | Split surfaces (§8); make `note_path` optional/separate |
| **Authority leakage** | Contract grows a write/persist path "for convenience" | Hard invariant: `read_only + mutation_intents`; architectural test asserting the route has no write deps |
| **Implicit state mutation** | Dismiss/snooze/pin or working-set quietly persisted | Keep them UI-only (already specified); no persistence in the read path |
| **Semantic drift** | Projection restates `review_state`/`maturity`/identity and drifts from source | Reference-only; never copy durable axes as authoritative fields |
| **Stale projection** | Cached snapshot served as current | `generated_at` + `trace_id` on every block; bounded TTL; `guards.degraded` on partial |
| **Token amplification** | Aggregate balloons (full bodies, full candidate lists, full receipts) and every read floods context | Bound every collection (top-N candidates, summaries not bodies, counts not lists); the contract owns the caps |
| **Over-centralization** | Everything routes through one fat endpoint; it becomes the system's coupling point | Keep sub-sources independent and individually degradable; aggregate is a thin composer |
| **Replay inconsistency** | Persisted runtime state diverges from re-derivation | Default to re-derivation; persist only non-derivable cursors, classified as trace |
| **UI/runtime desync** | UI infers classification/authority locally | Server-declared classification only (already a rule); UI renders, never decides |
| **Runaway agent coordination** | Multiple agents read+act on shared workspace state and amplify | v6.1 keeps multi-agent **out of scope**; when added, agents consume the same read-only projection and must route through governance, never share mutable workspace state |
| **Memory dump** | Workspace becomes opaque accumulating cognition | §6 boundary + discardability litmus test |

---

## 8. Proposed contract shape

Not production code — contract/semantic shape.

### 8.1 Two surfaces, one invariant

**A. Artifact-scoped aggregate (shipped, unchanged):**
`GET /api/companion/workspace?note_path=<path>` → the current payload (artifact / runtime / canvas / panel / suggestions / guards). Keep `#1122` as-is.

**B. Workspace/orientation surface (the v6.1 addition), note-independent:**
`GET /api/companion/orientation` → re-entry projection that exists with no note open:

```jsonc
{
  "generated_at": "iso8601",
  "trace_id": "string",
  "read_only": true,
  "leave_point": {                 // bounded trace, re-pointable
    "active_artifact_ref": "string | null",
    "last_interaction_at": "iso8601 | null",
    "last_session_id": "string | null"
  },
  "open_loops": [                  // derived from traces/receipts/queue
    { "label": "string", "source_link": "string", "panel_handoff_hint": "string | null" }
  ],
  "notable_changes": [             // recent durable deltas since leave-point
    { "label": "string", "source_link": "string", "at": "iso8601" }
  ],
  "resurface": { "candidates": [ /* top-N, why-now-bearing, bounded */ ] },
  "working_set": { "items": [ /* bounded, derived attention only */ ], "cap": 12 },
  "governance": { "pending_proposal_count": 0, "latest_receipt_outcome": "…|null" },
  "memory": { "pending_candidate_count": 0 },   // read-only awareness, never write
  "mutation_intents": [],          // proposals only; execution lives in Panel/governance
  "guards": { "degraded": false, "reasons": [] }
}
```

### 8.2 Partitioning model

Three bands, each with distinct lifecycle and authority:

1. **Referenced durable** (identity, axes, receipts, accepted memory) — links only.
2. **Derived projection** (orientation, resurfacing, salience, working set, posture) — recomputed per read, bounded, stamped.
3. **Bounded trace cursors** (leave-point) — best-effort persisted, discardable, classified as trace.

### 8.3 Lifecycle and update semantics

- Read → recompute bands 2+3; band 1 by reference. Snapshot with `generated_at`/`trace_id`.
- Update is **pull + snapshot** in v6.1. Push/incremental is a deferred, separately-governed delta.
- Degradation is explicit: any unresolved sub-source → `guards.degraded=true` with a reason; never silent UI defaults (existing rule).

### 8.4 Ownership model

- Endpoint composition: Runtime Projection / Companion UI backend.
- Each band's source: its existing owner (orientation runtime, resurfacing runtime, receipts, session registry, governance router). The aggregate **borrows reads, owns nothing**.

### 8.5 Observability

- Every read emits a `trace_id` and which sub-sources resolved vs degraded.
- The leave-point cursor write (the only write anywhere near this surface) is itself a trace row, not a receipt and not a durable artifact.

---

## 9. Recommended phased path

- **Phase 0 — Name the split (docs).** Amend `WORKSPACE_STATE_CONTRACT.md` to state explicitly that it is the *artifact-scoped* aggregate, and that note-independent orientation is a separate surface. Update `RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`'s workspace row to point at both. Docs-authoring lane; no code.
- **Phase 1 — Expose what already exists.** Surface the already-note-independent `build_orientation_frame` / `evaluate_resurfacing_candidates` through a `note_path`-free endpoint. Pure read; deterministic; bounded. This is the MVP (§10).
- **Phase 2 — Leave-point cursor.** Add the single bounded trace cursor (active artifact / last interaction) so "orientation after absence" survives restart. Classified as trace; loss degrades gracefully.
- **Phase 3 — Memory-candidate intent seam.** Wire `mutation_intents` → candidate review queue (read-only awareness of pending candidates; intent emission only). No new write authority.
- **Phase 4 (deferred) — Push/ambient + multi-agent reads.** Only after Phases 1–3 prove the bounded read model; both gated behind explicit ADRs.

---

## 10. Suggested MVP boundary for v6.1

**In:**
- `GET /api/companion/orientation` (note-independent), returning `leave_point` (derived only, no cursor yet), `open_loops`, `notable_changes`, bounded `resurface.candidates`, `governance` counts, `guards`.
- `read_only: true`, empty `mutation_intents`, `generated_at` + `trace_id`, bounded collections.
- Deterministic recomputation from existing `OrientationSignals`; no new persisted state.

**Out (explicitly deferred):**
- Persisted leave-point cursor (Phase 2).
- Memory-candidate intent emission (Phase 3).
- Push/streaming, incremental diffs, multi-agent reads (Phase 4).
- Any write/persist/session-mutation capability (permanent — never in scope for this contract).

This MVP ships the missing v6.1 capability (re-entry orientation with nothing open) while changing zero safety properties: it is a new read over derivers that already exist and already declare themselves read-only.

---

## 11. Open questions requiring ADRs / governance decisions

1. **Endpoint shape:** new path (`/companion/orientation`) vs `note_path`-optional on `/companion/workspace`? (Recommend new path — keeps the shipped #1122 contract's mandatory-`note_path` invariant intact.) → ADR.
2. **Leave-point cursor durability:** trace row in DB vs derived-only? Where does the single non-derivable fact live, and is even that acceptable as persisted runtime state? → boundary-contract decision (#1368/#1369).
3. **Working-set bound:** what N, and is the cap a contract constant or policy-configurable per `NOTE_KIND_POLICIES`-style extension? → governance.
4. **Memory-candidate intent threshold:** what makes the contract emit "consider as memory," and does emission itself need a receipt/trace? → AGENT_MEMORY governance (#1085 adjacency).
5. **Push/ambient resurfacing:** if/when streaming is added, how is the "no notification-centric interaction" constraint enforced at the contract level? → ADR (Phase 4 gate).
6. **Multi-agent reads:** confirm agents consume the identical read-only projection and that shared mutable workspace state is permanently prohibited. → ADR before any multi-agent work.

---

## 12. Critical takeaways (challenging the framing)

- The prompt frames this as *designing* a contract. The honest finding is that one **exists and is correct for its scope**; the real work is **recognizing a scope boundary** and exposing a surface that's already half-implemented but trapped behind a mandatory `note_path`.
- "Runtime nervous system" is the wrong metaphor and would invite the materialized-graph anti-pattern. This is an **orientation read substrate** with **zero write authority**.
- The system's existing seams (`read_only` + `mutation_intents`, query-independent derivers, the runtime/durable boundary, receipt/trace separation, salience-as-overlay) **already encode the safe design**. The risk is not under-specification — it is *erosion*: a convenient persist here, a cached graph there, a quietly-accumulated memory blob. The contract's primary defensive job is to make those erosions architecturally impossible (no write deps, bounded collections, discardability litmus test), not to add capability.
