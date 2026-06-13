State: Filed on GitHub as issue #1903 (validation hub, Status=Backlog + agent:blocked). This file is
the local source; GitHub #1903 is the authoritative backlog/validation surface. Child slices:
#1904 (ready), #1905, #1906, #1907, #1908 (blocked). Spec PR: #1902.

# [Feature] Durable Memory and Recall

## Context

The closed `docs/AGENT_MEMORY/` capability (parent #900) shipped the agent-memory model but
deliberately excluded a storage backend. Today the review queue and review decisions live in process
memory and are lost on restart, and `app/agent_memory/recall_explanation.py` and
`app/agent_memory/authority_guard.py` have zero production call sites. The 2026-06-13 runtime
evidence audit surfaced this; `docs/STATUS.md` and the Integrated Runtime v1 epic (#1874) record
durable persistence/recall as post-v1 work. This feature delivers it, governed by
`docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md` (#1369) and
`docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`.

## Scope

Durable, vault-scoped persistence of memory review decisions; startup reconciliation of the review
queue against those decisions; governed materialization of promoted semantic memory into the vault
as a human-reviewable artifact (WriteGuard + receipt); and a guarded recall-activation consumer that
wires the existing authority guard and recall explanation and emits a recall receipt. Specification
lives in `docs/DURABLE_MEMORY_AND_RECALL/`.

## Source Anchors

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Lifecycle`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Review and promotion rules`
- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md :: Authority rules`
- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md :: Persistence rules`
- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md :: Leakage prevention`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/SEPARATING_PERSISTENCE_SURFACES/DEFINE_WRITING_SURFACE_CONTRACT.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`

## Constraints

- Do not make pending (undecided) candidates durable; per #1369 they are discardable runtime state.
- Persist review decisions as receipts/traces, not as durable semantic artifacts.
- Promotion to a durable vault artifact must go through `proposal → WriteGuard → receipt → artifact`;
  no silent persistence.
- Recall must run the authority guard; activation/recall state must not persist as authority.
- All durable memory state is vault-scoped via `VaultContext`; no global/cross-vault leakage.
- Memory must not override human-authored knowledge; provenance and source links are preserved.

## Acceptance Criteria

- [ ] Review decisions persist durably, vault-scoped, and survive restart.
  Verify: `tests/agent_memory/test_review_decision_store.py::test_decisions_survive_restart`
- [ ] The review queue reconciles against persisted decisions on startup; decided candidates are not
  re-surfaced. Verify: `tests/agent_memory/test_review_queue_reconciliation.py::test_decided_candidates_not_resurfaced`
- [ ] Promotion to semantic memory materializes a vault artifact only through WriteGuard + receipt,
  preserving provenance, without overriding human-authored notes.
  Verify: `tests/agent_memory/test_memory_materialization.py::test_promotion_materializes_via_writeguard_with_receipt`
- [ ] A recall-activation consumer runs `evaluate_memory_authority` and emits a recall receipt;
  activation is not persisted as durable authority.
  Verify: `tests/agent_memory/test_guarded_recall_activation.py::test_recall_runs_authority_guard_and_emits_receipt`

## Out of Scope

- Context-bundle durable persistence (separate, lower-priority capability).
- Vector store / embedding model selection.
- Making pending candidates durable.
- Automatic (non-reviewed) promotion or recall-driven mutation.

## Suggested Validation

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/agent_memory`
- `rg -n "Verify:" docs/DURABLE_MEMORY_AND_RECALL/*.md`

## Source Docs

- `docs/CONCEPTS/AGENT_MEMORY_AND_KNOWLEDGE_CONTRACT.md`
- `docs/CONCEPTS/RUNTIME_VS_DURABLE_STATE_BOUNDARY.md`
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md`
- `docs/SEPARATING_PERSISTENCE_SURFACES/DEFINE_WRITING_SURFACE_CONTRACT.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`

## Implementation Tasks

1. `docs/DURABLE_MEMORY_AND_RECALL/PERSIST_REVIEW_DECISIONS.md`
2. `docs/DURABLE_MEMORY_AND_RECALL/RECONCILE_REVIEW_QUEUE_ON_START.md`
3. `docs/DURABLE_MEMORY_AND_RECALL/MATERIALIZE_PROMOTED_MEMORY_TO_VAULT.md`
4. `docs/DURABLE_MEMORY_AND_RECALL/ACTIVATE_GUARDED_RECALL.md`
5. `docs/DURABLE_MEMORY_AND_RECALL/SURFACE_MATERIALIZED_MEMORY_IN_COMPANION.md`

## Verification Path

- Each task PR resolves the named `Verify:` targets in its task spec.
- Persistence and reconciliation are verified before materialization and recall are accepted.
- Parent-level verification confirms governed materialization (WriteGuard + receipt), guarded recall,
  and vault-scoping.

## Validation / Acceptance Path

- Keep validation evidence on this parent issue.
- Deliver child issues in dependency order; post a validation receipt per delivered child.
- Promote owner-doc truth only after receipts show durable decisions, governed materialization, and
  guarded recall in the shipped runtime.
