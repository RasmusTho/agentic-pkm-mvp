State: Accepted - docs/governance decision for #1459. No runtime, API, UI, MCP, A2A, orchestration, lease, agent coordination, or multi-agent read behavior is implemented.

# ADR-0012: Orientation Multi-Agent Reads Boundary

**Date:** 2026-06-02
**Status:** Accepted - docs/governance decision for #1459

---

## Context

ADR-0007 introduced `GET /api/companion/orientation` as a note-independent,
read-only Workspace Orientation Snapshot. The surface is a bounded orientation
projection for the human/UI. ADR-0008 admits only a bounded leave-point trace
cursor. ADR-0009 admits only bounded `MemoryCandidate` handoff intents. ADR-0011
keeps push/ambient resurfacing transport out of the current implementation.

Phase 4 also deferred multi-agent reads. The useful future capability is narrow:
agents may need the same orientation snapshot the human sees so they can
understand what is open, stale, degraded, or safe to propose. The dangerous
version is broad: Workspace Orientation becomes an agent coordination authority,
shared mutable workspace object, hidden A2A bus, lease manager, orchestration
dashboard, or memory accumulator.

This ADR decides the boundary before any implementation. It does not implement
multi-agent reads.

## Decision

Agents may consume Workspace Orientation only as the **same read-only projection
exposed to the human/UI**.

The allowed future shape is a bounded read path over `GET /api/companion/orientation`
or an exact compatibility wrapper that preserves the same contract:

- read-only;
- snapshot-shaped;
- bounded by the existing orientation caps;
- provenance-bearing through `authority_role` and `source_ref`;
- degraded honestly through existing freshness/degradation fields;
- no raw note bodies, raw chat history, embeddings, agent scratchpads, or
  orchestration internals;
- no writes, execution, receipts, candidate creation, governance mutation, or
  durable semantic transition from the read itself.

Per-agent identity or scope may be supplied only as bounded read context for
access control, audit, rate limiting, or provenance of the read. It must not
become writable workspace truth, semantic artifact metadata, agent-owned
orientation state, or an authority field inside the projection.

Workspace Orientation remains a read substrate, not a coordination substrate.
It must not carry:

- shared mutable workspace state;
- agent-owned coordination state;
- A2A routing state;
- orchestration runs, checkpoints, leases, or agent messages;
- hidden subscription state;
- a mutable "current workspace" record owned by agents.

Any action suggested from the projection must route through existing governed
write paths. Agents may use the snapshot to decide what to propose, but proposal,
write, trust, review, memory, promotion, lifecycle, or receipt-producing
transitions remain outside orientation.

## Agent Consumer Rules

A future implementation child must preserve these rules:

- Agents request orientation under an explicit consumer identity or scope when
  policy requires it.
- The response payload remains the same orientation projection shape consumed by
  the human/UI unless a later owner decision adds an explicitly compatible
  read-only envelope.
- The envelope may identify the consumer, policy scope, or audit trace, but it
  must not change artifact meaning or create per-agent workspace truth.
- Multiple agents reading the same snapshot do not create coordination state.
- Repeated reads do not accumulate memory, agent scratchpads, or hidden worklogs.
- Read traces, if added, are operational traces only and are not governance
  receipts or durable semantic artifacts.
- Agents must treat `mutation_intents` as handoff hints only. They do not
  execute, authorize, or persist anything through orientation.

## Governance Routing

Orientation may inform an agent proposal, but it does not execute the proposal.

Allowed follow-on routes remain existing governed surfaces, for example:

- Panel/governance proposal for review, trust, lifecycle, or owner-doc action;
- Canvas/body-edit governance for body changes;
- MemoryCandidate review boundary where ADR-0009 or a later memory ADR admits a
  handoff;
- GitHub/BuilderOps workflow where the proposal belongs to builder operations.

The executing path owns WriteGuard, receipts, conflict handling, and human or
policy approval. Orientation does not.

## Forbidden Paths

The multi-agent read path must not:

- make Workspace Orientation an agent coordination authority;
- create shared mutable workspace state;
- create an A2A bus, orchestration bus, lease table, queue, or checkpoint store;
- expose raw note bodies, raw chat, embeddings, or agent scratchpads;
- create, accept, promote, reject, or store memory;
- create or apply governance actions;
- write receipts from the read itself;
- mutate vault files, frontmatter, ObjectStore state, Panel state, Canvas state,
  WriteGuard state, or runtime authority surfaces;
- treat per-agent identity as durable artifact truth;
- let one agent's read change what another agent sees except through separately
  governed source changes.

## Consequences

Positive:

- Agents can later gain orientation context without a separate privileged
  projection.
- The human/UI projection remains the contract anchor.
- The runtime boundary remains discardable and read-only.
- Follow-on actions stay behind existing governance/write paths.
- #1459 has a bounded implementation shape instead of an open-ended Phase 4
  coordination request.

Costs and constraints:

- Agent consumers cannot ask Orientation to store coordination state.
- Agent-specific filtering must be handled as access policy or read envelope,
  not as a new source of workspace truth.
- Any need for active runs, leases, checkpoints, agent messages, task routing,
  or coordination belongs to a separate orchestration/A2A design, not this
  orientation surface.

## Rejected Alternatives

### 1. No agent reads of orientation

Rejected. A read-only agent consumer can be useful without weakening the
orientation contract, as long as the agent consumes the same bounded projection
and any action routes through governance.

### 2. Agent-specific orientation projection

Rejected for the first implementation shape. A separate agent projection would
invite drift between what the human sees and what agents treat as context. If a
future owner decision adds an agent envelope, it must remain compatible with the
same underlying orientation projection.

### 3. Shared mutable workspace state

Rejected. This is the failure mode ADR-0007 explicitly warned about. A shared
mutable workspace object would turn read orientation into runtime truth and
coordination authority.

### 4. Orientation as A2A or orchestration bus

Rejected. Agent routing, runs, leases, checkpoints, and messages belong to a
separate orchestration/A2A boundary if needed. They are not orientation.

### 5. Automatic action execution from orientation

Rejected. Orientation can inform proposals. Execution belongs to governed paths
with the required policy, WriteGuard, conflict, and receipt semantics.

## Contract Impact

`companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md` must continue to state
that the shipped orientation endpoint has no multi-agent semantics. It should
point to this ADR as the future boundary for any multi-agent read child issue.

`docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md` should make clear that
Workspace Orientation is not shared mutable workspace truth and not an agent
coordination substrate.

`docs/adr/ADR-0007-workspace-state-contract-scope-split.md` remains correct:
Phase 4 multi-agent reads were deferred to a later ADR. This ADR resolves that
open question by allowing only a later bounded read-only child over the same
orientation projection.

## Verification Requirements

- ADR is present at `docs/adr/ADR-0012-orientation-multiagent-reads.md`.
- ADR is indexed in `docs/adr/INDEX.md`.
- Workspace Orientation Contract points to ADR-0012 while preserving the current
  no-multi-agent-semantics implementation claim.
- Runtime/durable boundary docs preserve the no-shared-mutable-workspace-state
  rule.
- `python3 scripts/docs_guard.py` passes.
- `git diff --check` passes.

## Follow-up Issue Impact

Implementation remains deferred until a bounded child issue is opened.

That child must specify:

- exact read endpoint or compatibility wrapper;
- consumer identity/scope rules;
- access-control and rate-limit posture, if any;
- whether read traces are emitted, and if so their operational trace shape;
- payload compatibility with the human/UI projection;
- no shared mutable workspace state;
- no orchestration/A2A/lease/checkpoint/message state;
- no write, receipt, memory, Panel, Canvas, WriteGuard, or durable semantic
  mutation from the read;
- tests proving read-only behavior, bounded output, same-projection semantics,
  and governance routing for any follow-on action.

## References

- Issue #1459: ADR boundary decision
- Issue #1450: Workspace Orientation epic Phase 4
- `docs/adr/ADR-0007-workspace-state-contract-scope-split.md`
- `docs/research/workspace-state-contract-v61-architecture-memo.md`
- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`
- `companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
