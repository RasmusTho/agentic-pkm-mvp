---
name: Specify Archived and Forgotten Memory Lifecycle
description: >
  Bounded specification for agent-memory lifecycle transitions after materialization:
  active → archived/cold-storage → restored, and active/archived → forgotten/tombstoned.
task_id: AGENT-MEMORY-LIFECYCLE-01
source_anchor: docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Decay / archive
parent_capability: Agent Memory
prerequisites:
  - AGENT-MEMORY-01 (MemoryCandidate model)
  - AGENT-MEMORY-03 (Promote/reject/revise flow)
depends_on:
  - docs/AGENT_MEMORY/DEFINE_MEMORY_CANDIDATE_MODEL.md
  - docs/AGENT_MEMORY/PROMOTE_REJECT_AND_REVISE_MEMORY.md
can_parallelize_with: []
---

# DEFINE_MEMORY_LIFECYCLE_ARCHIVE_AND_FORGET

## Purpose

This document specifies the lifecycle states and governed transitions that apply to agent memory
**after** it has been materialized (promoted from candidate to active). It covers:

- `active → archived` (cold-storage; reversible, provenance-preserving)
- `archived → restored` (back to active)
- `active → forgotten` (governed destructive transition; irreversible)
- `archived → forgotten` (governed destructive transition; irreversible)

This is specification work only. Runtime implementation of these flows is out of scope for this
slice and must be created as separate implementation issues.

The semantic source of truth for agent memory is
`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`.
This document is an implementation-readiness breakdown of the lifecycle portion of that contract.

## State Transition Map

```
                   ┌──────────────────────────────────┐
                   │                                  │
  [candidate] ─► [active] ─────────────────────────► [forgotten/tombstoned]
                     │           governed                  (irreversible)
                     │           destructive
                     │
                     ▼
                [archived/cold-storage]
                     │
                     │  restore (governed; reversible)
                     │
                     ▼
                   [active]
                     │
                     │  (may also forget from archived state)
                     ▼
               [forgotten/tombstoned]
                  (irreversible)
```

### Lifecycle States

| State | Meaning | Durable? | Default Recall? | Reversible? |
|---|---|---|---|---|
| `active` | Promoted, in default recall surface | Yes | Yes | Via archive/forget |
| `archived` | Cold-storage; excluded from default recall | Yes | No (policy-admitted only) | Yes — restore |
| `forgotten` | Tombstoned; semantic content removed | Tombstone only | No | No |

These states are **lifecycle state**, not salience scores, zone labels, or retrieval weights. See
[Lifecycle State vs Salience / Zone / Retrieval Weight](#lifecycle-state-vs-salience--zone--retrieval-weight).

## Lifecycle State Definitions

### active

A memory record in `active` state:

- has been promoted through the governed review path (see
  `docs/AGENT_MEMORY/PROMOTE_REJECT_AND_REVISE_MEMORY.md`),
- is included in default recall unless domain, trust, or scope constraints exclude it (see
  `docs/CONCEPTS/LAYERING_MODEL.md :: Domain is the primary boundary`),
- carries its full semantic content, provenance, and review receipts,
- and may transition to `archived` or `forgotten` under the governed rules below.

### archived (cold-storage)

A memory record in `archived` state:

- has been moved out of the default recall surface by a governed archive transition,
- retains its full semantic content and all provenance receipts — archive is not destructive,
- is excluded from default recall unless the caller or policy explicitly opts into archive recall,
- is explicitly retrievable on request or by policy-admitted recall (e.g., a deliberate "search
  archive" intent),
- and may be restored to `active` by a governed restore transition.

Archive posture is a **lifecycle state**, not a salience score or zone label. Refer to
`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Decay / archive`:

> Archive/cold-storage posture is a lifecycle state, not the same thing as a salience score or
> storage-temperature metaphor. Archived memory should remain durable, provenance-preserving, and
> explicitly retrievable, while default recall and resurfacing exclude it unless the caller or
> policy opts into archive recall.

The current `zone` overlay and salience signals defined in
`docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` influence ranking and
resurfacing prioritization only. Per
`docs/CONCEPTS/LAYERING_MODEL.md :: Zone is derived, not a gate`: zone must never override
domain, plane, or trust boundaries. Lifecycle state (`archived`) is an access-class transition,
not a derived attentional overlay.

### forgotten (tombstoned)

A memory record in `forgotten` state:

- has been subjected to a **governed destructive lifecycle transition** (forgetting),
- has had its semantic content removed from normal recall and derived indexes,
- retains **only a minimal non-semantic tombstone/receipt** needed for accountability — the
  tombstone must not repeat or reconstruct the forgotten semantic content,
- and is **irreversible**: a forgotten memory cannot be restored to `active` or `archived`.

Forgetting is not archiving. See
`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Deletion and correction expectations`:

> Complete forgetting is stronger than archiving. A future forget flow should be a governed
> destructive lifecycle transition: remove the semantic memory from normal recall and derived
> indexes, preserve only a minimal non-semantic tombstone/receipt needed for accountability, and
> avoid repeating the forgotten content in receipts, summaries, or recall projections.

## Governed Transitions

### active → archived

**Trigger**: a human or policy request to move a memory to cold-storage.

**Requirements**:
- explicit intent (human or policy-defined rule with receipt),
- a WriteGuard-gated write to update the memory record's lifecycle state,
- an archive receipt recording: memory id, transition initiator, timestamp, justification,
- the semantic content and all prior receipts are preserved (archive is non-destructive),
- and the memory is excluded from default recall surfaces after this transition.

**Produces**: archive receipt.

**Reversible**: yes — see `archived → active (restore)` below.

### archived → active (restore)

**Trigger**: a human request or policy-admitted restore intent.

**Requirements**:
- explicit intent with receipted restore trigger,
- a WriteGuard-gated write to update the lifecycle state back to `active`,
- a restore receipt recording: memory id, restore initiator, timestamp, justification,
- and the memory re-enters default recall surfaces after this transition.

**Produces**: restore receipt.

### active → forgotten

**Trigger**: a governed forget request (human-initiated; must be explicit and receipted).

**Requirements**:
- explicit human intent with a formal forget request — forget must not be triggered silently by
  policy, salience decay, or zone transitions,
- a forget receipt (tombstone record) written before semantic content is removed; the tombstone
  must record only: memory id, former lifecycle state, transition timestamp, initiator, and a
  non-semantic reason code — it must **not** include or reconstruct the forgotten semantic content,
- a WriteGuard-gated destructive write that removes semantic content from the memory record and
  from all derived indexes (embeddings, recall projections, companion surfaces),
- and the memory record transitions to `forgotten` / tombstone state.

**Produces**: tombstone/forget receipt (non-semantic).

**Irreversible**: a forgotten memory cannot be restored.

### archived → forgotten

Same requirements as `active → forgotten`. The memory does not need to be restored to `active`
before it can be forgotten; the transition is valid from either `active` or `archived`.

## Receipt Invariants

These invariants apply to all lifecycle transition receipts and are consistent with
`docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md :: Receipt Requirements` and
`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Relation to receipts`:

1. **Forget receipts must not repeat forgotten content.** Tombstone records must be non-semantic.
   The accountability purpose of a tombstone is to confirm that a forget happened, not to preserve
   the semantic material that was forgotten.

2. **Archive receipts preserve full provenance.** Because archive is reversible and
   non-destructive, archive receipts may reference the original content shape, but they do not
   embed it as duplicate content.

3. **All lifecycle transitions require WriteGuard.** Refer to
   `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md :: Persistence rules`: the path is
   `runtime value → proposal → governance → receipt → durable artifact`. Lifecycle mutations are
   durable mutations and must follow this path.

4. **No hidden authority.** Lifecycle state changes must not silently widen or narrow recall
   authority. Authority rules remain governed by
   `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Authority rules`.

## Lifecycle State vs Salience / Zone / Retrieval Weight

These are distinct concepts and must not be conflated.

| Concept | Defined by | Governs | Durable? |
|---|---|---|---|
| Lifecycle state (`active`, `archived`, `forgotten`) | This spec; `AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Decay / archive` | Whether a memory participates in default recall; whether it exists at all | Yes |
| Salience / attentional relevance | `SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` | Ranking and resurfacing priority | No (derived) |
| Zone | `LAYERING_MODEL.md :: Zone` | Derived attentional overlay; affects rank, not access | No (derived) |
| Retrieval weight | `LAYERING_MODEL.md`; `SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` | Position in a ranked result set | No (derived) |

Per `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md :: What salience is not`:
salience is not `review_state`, temporal validity, source role, trust, or artifact identity.
Lifecycle state is closer to `review_state` than to salience — it is a durable, governed
classification of a memory record's current standing in the system.

Per `docs/CONCEPTS/LAYERING_MODEL.md :: Zone is derived, not a gate`:
> Zone affects prioritization, not permission; it must never override domain, plane, or trust
> boundaries.

Lifecycle state is an **access-class property**, not a zone projection. A memory with low salience
is still `active`; an archived memory is not `active` even if it has high historical salience.
Zone and retrieval weight influence which `active` memories rank higher — they do not govern
whether a memory is `archived` or `forgotten`.

Archive/cold-storage is a deliberate human or policy-governed transition. It is not a passive
consequence of salience decay or zone drift.

## Retention and Recall Boundaries

When a memory is `archived`:

- default recall must exclude it (e.g., standard `/recall` or orientation surfaces must not
  surface it without explicit archive-opt-in),
- archive recall requires explicit caller intent (e.g., a deliberate "search archive" query
  parameter or policy-defined rule with receipt),
- domain, trust, and plane constraints still apply to archived recall — refer to
  `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md :: Contract Rules (must hold)` rule 2 (Domain +
  Trust gate exposure) and rule 10 (Zone influences rank, not access),
- and the retention surface (see
  `docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md :: Core archive / retention operations`) governs what
  archived recall modes are supported (Rediscover, Inspect, Cite, Extract, Materialize).

When a memory is `forgotten`:

- it must not appear in any recall surface, orientation projection, companion summary, or derived
  index,
- the tombstone record alone remains; it is not a recall artifact — it is an accountability record,
- and any derived indexes (embeddings, machine mirrors) must be updated to remove the forgotten
  memory's semantic content.

## Non-Goals

The following are explicitly out of scope for this specification:

- Runtime implementation of archive, restore, forget, tombstone, or recall-index mutation flows.
- Changing the current shipped Durable Memory and Recall behavior
  (`docs/DURABLE_MEMORY_AND_RECALL/`).
- Redefining the retention surface, salience model, layering model, WriteGuard, or receipt
  contracts.
- Specifying a vector-store schema or embedding removal procedure (implementation detail).
- Defining a policy engine for automatic archiving or forgetting (a later governed slice).
- Companion UI rendering for archived/forgotten memory states (a later governed slice).

## Acceptance Criteria

- [ ] A spec file for archived/cold-storage and forgotten/tombstone memory lifecycle exists with
  explicit state transitions and non-goals.
  Verify: `rg -n "archived|cold-storage|forgotten|tombstone|restore" docs/AGENT_MEMORY docs/CONCEPTS`

- [ ] The spec distinguishes lifecycle state from salience, zone, and retrieval weight and cites the
  relevant concept contracts.
  Verify: `rg -n "salience|zone|retrieval weight|lifecycle state|authority" docs/AGENT_MEMORY docs/CONCEPTS`

- [ ] The spec preserves governed deletion/forgetting semantics without repeating forgotten content
  in receipts.
  Verify: `rg -n "forget|forgotten|tombstone|receipt|content" docs/AGENT_MEMORY docs/CONCEPTS`

## Out of Scope

See [Non-Goals](#non-goals) above.

## Related Docs

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md` — semantic source of truth for memory lifecycle, authority, and receipt rules
- `docs/CONCEPTS/SALIENCE_AND_ATTENTIONAL_RELEVANCE_CONTRACT.md` — salience / zone / attentional relevance contract (lifecycle state is not salience)
- `docs/CONCEPTS/LAYERING_MODEL.md` — Domain / Plane / Trust / Zone orthogonal boundary model (zone is derived; not a lifecycle gate)
- `docs/CONCEPTS/ARCHIVE_BRAIN_CONTRACT.md` — archive/retention function contract (cognitive function and ontology)
- `docs/CONCEPTS/ARCHIVE_EXPOSURE_CONTRACT.md` — retention-surface exposure and safety rules (receipt requirements, domain+trust gate)
- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md` — runtime vs durable state; WriteGuard and governance path for durable mutations
- `docs/AGENT_MEMORY/DEFINE_MEMORY_CANDIDATE_MODEL.md` — memory candidate model (lifecycle precursor)
- `docs/AGENT_MEMORY/PROMOTE_REJECT_AND_REVISE_MEMORY.md` — promote/reject/revise flows (lifecycle precursor)
- `docs/DURABLE_MEMORY_AND_RECALL/` — shipped durable memory and recall subset

## Related GitHub Issues

- Governing issue: #1919
- Context issue: #1917 (Durable Memory and Recall owner-doc promotion)
