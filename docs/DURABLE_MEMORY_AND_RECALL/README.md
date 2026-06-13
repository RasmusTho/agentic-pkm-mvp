State: Specification directory (spec/source layer). Not yet delivered. Parent feature issue #1903 filed as the validation hub; child slices #1904–#1908 created in dependency order (#1904 ready, rest blocked). Spec PR #1902. Docs/spec authoring lane — this directory specifies what must be built; it does not itself ship runtime behavior.

Doc role: Capability specification and delivery index for durable agent-memory persistence and guarded recall activation.
Authority: Navigates the durable-memory capability. Semantic authority remains in `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`; the runtime-vs-durable boundary remains in `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`; current runtime posture remains in `docs/STATUS.md`.

# Durable Memory and Recall

## Capability Boundary

The closed `docs/AGENT_MEMORY/` capability (parent #900) delivered the memory *model* — candidate
modeling, review queue, promote/reject/revise flows, recall explanation, and an authority guard —
but explicitly listed "defining a specific vector store or storage backend" as a non-goal. As a
result, two facts hold in the current runtime:

- the review queue and review decisions live in process memory only and are lost on restart
  (`app/agent_memory/review_queue.py`, the module-level singleton in `app/api/routes/companion.py`);
- `app/agent_memory/recall_explanation.py` and `app/agent_memory/authority_guard.py` are
  implemented and tested but have **zero production call sites** — no path recalls promoted memory
  into reasoning context, so the guard is dormant by design, not by defect.

This capability closes that gap. Its boundary is:

- **persist review decisions durably** as governance receipts so a reviewed candidate is not
  re-surfaced as new after a restart;
- **reconcile the in-memory review queue on startup** against persisted decisions;
- **materialize promoted semantic memory into the vault** as a human-reviewable artifact, reached
  only through the governed `proposal → WriteGuard → receipt → artifact` path;
- **activate guarded recall** by wiring the existing `authority_guard` and `recall_explanation`
  into a recall-activation consumer that emits a recall receipt;
- **surface materialized memory and recall provenance** in the Companion UI.

## Owner decision basis

This capability was authorized by the owner on 2026-06-13 following the runtime evidence audit, with
two binding choices recorded:

1. Agent-memory persistence is prioritized ahead of context-bundle persistence; memory storage is
   vault-scoped from day one via `VaultContext`/`VaultManager`.
2. When memory is promoted to durable semantic knowledge, it **materializes as a vault artifact**
   (the writing surface), not merely as a hidden machine receipt. The receipt remains the
   accountability record; the vault note is the durable semantic surface.

## Relationship to the governing boundary (must not contradict)

`docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md` (issue #1369, closed) is binding:

- a **pending** review-queue entry is runtime state and is discardable; this capability does **not**
  make pending candidates durable (see `RECONCILE_REVIEW_QUEUE_ON_START`, not "persist the queue");
- a **review decision** is a governance outcome that may persist **as a receipt/trace**;
- a runtime-derived value becomes a durable artifact only through
  `runtime value → proposal → governance → receipt → durable artifact` — never silent persistence;
- **activation/recall state must never persist as authority**: what was recalled for a task is
  recorded in a recall receipt, not stamped as a durable property of the artifact.

## Cross-task invariant: promotion is terminal only on materialization

A promote-to-semantic decision becomes *terminal* — the state that suppresses a candidate from the
pending review set — only once its vault artifact is successfully materialized. A blocked or failed
materialization records a failed-attempt receipt and keeps the promotion **actionable** (the
candidate stays reviewable/retryable). This prevents a promoted candidate from silently disappearing
from review with no artifact and no retry path. The invariant is shared by `PERSIST_REVIEW_DECISIONS`
(represents terminal vs. non-terminal), `MATERIALIZE_PROMOTED_MEMORY_TO_VAULT` (marks terminal only
on success), and `RECONCILE_REVIEW_QUEUE_ON_START` (suppresses only terminal decisions).

## Non-Goals

- making pending (undecided) candidates durable across restart;
- making agent memory a hidden source of truth or letting it override human-authored knowledge;
- introducing memory recall that authorizes mutation without review (the authority guard still gates);
- a specific vector store or embedding model choice;
- reopening or re-litigating the closed `docs/AGENT_MEMORY/` slices.

## Task List

1. [PERSIST_REVIEW_DECISIONS.md](PERSIST_REVIEW_DECISIONS.md)
2. [RECONCILE_REVIEW_QUEUE_ON_START.md](RECONCILE_REVIEW_QUEUE_ON_START.md)
3. [MATERIALIZE_PROMOTED_MEMORY_TO_VAULT.md](MATERIALIZE_PROMOTED_MEMORY_TO_VAULT.md)
4. [ACTIVATE_GUARDED_RECALL.md](ACTIVATE_GUARDED_RECALL.md)
5. [SURFACE_MATERIALIZED_MEMORY_IN_COMPANION.md](SURFACE_MATERIALIZED_MEMORY_IN_COMPANION.md)

## Flat Execution Order

1. `PERSIST_REVIEW_DECISIONS` — durable, vault-scoped decision receipts (foundation; ready first)
2. `RECONCILE_REVIEW_QUEUE_ON_START` — startup reconciliation against persisted decisions
3. `MATERIALIZE_PROMOTED_MEMORY_TO_VAULT` — governed write-proposal materializes promoted memory
4. `ACTIVATE_GUARDED_RECALL` — recall-activation consumer wires authority guard + recall receipt
5. `SURFACE_MATERIALIZED_MEMORY_IN_COMPANION` — companion UI surfaces artifact + recall provenance

This is a dependency chain, not a parallel fan-out. Only task 1 is independently ready; tasks 2–5
unblock as their prerequisites merge. The parent feature issue is the validation hub across the chain.

## Capability-Level Acceptance Criteria

- [ ] Review decisions survive a process restart and a reviewed candidate is not re-surfaced as new.
  Verify: `tests/agent_memory/test_review_decision_store.py::test_decisions_survive_restart`
- [ ] Promoted semantic memory materializes as a vault artifact only through WriteGuard + receipt,
  preserving provenance, and never overrides human-authored notes.
  Verify: `tests/agent_memory/test_memory_materialization.py::test_promotion_materializes_via_writeguard_with_receipt`
- [ ] Recalled memory passes through `authority_guard` and emits a recall receipt; activation state
  is not persisted as durable authority.
  Verify: `tests/agent_memory/test_guarded_recall_activation.py::test_recall_runs_authority_guard_and_emits_receipt`
- [ ] All durable memory state is vault-scoped via `VaultContext` (no global/cross-vault leakage).
  Verify: `tests/agent_memory/test_review_decision_store.py::test_decision_store_is_vault_scoped`

## Verification Path

- Each task PR resolves the named `Verify:` targets in its task spec's `How to Verify (Pre-Merge)`.
- The persistence and reconciliation tasks verify decision durability and queue reconciliation
  before materialization and recall tasks are treated as complete.
- Parent-level verification checks that memory remains inspectable and non-authoritative, that
  materialization is governed (WriteGuard + receipt), and that recall is guarded and explainable.

## Validation / Acceptance Path

- File the parent feature issue (done) as the validation hub; keep validation evidence there.
- Deliver child issues in dependency order; each delivered child posts a validation receipt on the
  parent before the next is picked up.
- Promote owner-doc truth (`docs/STATUS.md`, `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
  "Relationship to shipped reality") only after receipts show durable decisions, governed
  materialization, and guarded recall in the shipped runtime.

## Evidence Surface

- Local task specs in this directory define the implementation contract.
- Each delivered slice's PR is its verification receipt.
- The parent feature issue holds validation evidence and the acceptance checklist.
- Owner docs change to claim live behavior only when the owner-doc promotion conditions are met.

## Owner-Doc Promotion Trigger

Promote current-state owner docs only after implementation receipts show all of the following:

- review decisions persist as receipts and survive restart, vault-scoped;
- the review queue reconciles against persisted decisions on startup;
- promotion to semantic memory materializes a vault artifact through WriteGuard + receipt, with
  provenance preserved and no override of human-authored content;
- recall runs the authority guard, emits a recall receipt, and does not persist activation as authority.

## Relationship to GitHub Issues

- Predecessor capability (closed): `docs/AGENT_MEMORY/`, parent #900.
- Governing boundary (closed): #1369 (`docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`).
- Spec PR: #1902.
- Parent feature issue (validation hub): #1903.
- Child slices (dependency order):
  - #1904 — PERSIST_REVIEW_DECISIONS (`agent:ready`)
  - #1905 — RECONCILE_REVIEW_QUEUE_ON_START (`agent:blocked`, depends on #1904)
  - #1906 — MATERIALIZE_PROMOTED_MEMORY_TO_VAULT (`agent:blocked`, depends on #1904)
  - #1907 — ACTIVATE_GUARDED_RECALL (`agent:blocked`, depends on #1906)
  - #1908 — SURFACE_MATERIALIZED_MEMORY_IN_COMPANION (`agent:blocked`, depends on #1906, #1907)
