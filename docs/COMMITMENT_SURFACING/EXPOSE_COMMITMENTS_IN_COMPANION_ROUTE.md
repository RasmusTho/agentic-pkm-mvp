---
name: Expose Commitments In Companion Route
description: Expose active commitments (next_action / waiting / review_return) in companion workspace state via the companion route, read-only, backed by the durable source
task_id: COMMITMENT-SURFACING-02
source_anchor: app/api/routes/companion.py :: RuntimeState
parent_capability: Commitment Surfacing
prerequisites: [COMMITMENT-SURFACING-01]
depends_on: [PERSIST_COMMITMENTS_AS_VAULT_ARTEFACTS.md]
can_parallelize_with: []
---

State: Specification for the read-only companion-route surface. Slice 2 of the COMMITMENT_SURFACING capability (parent #1960). Depends on slice 1. Code-affecting.

# Expose Commitments In Companion Route

## Purpose

With commitments durably persisted (slice 1), the companion workspace state must expose them so the UI (slice 3) and the human can see them. This task adds a read-only commitment field to the companion workspace state in `app/api/routes/companion.py`, backed by the durable query path from slice 1 — **not** by the ephemeral `AgentState`. This is the slice that flips the long-standing architecture guard `tests/api/test_arch_commitment_and_canvas.py::test_commitments_surface_in_workspace_state` from xfail to pass.

## What This Task Does

- Adds a commitment surface to the companion workspace state model in `app/api/routes/companion.py` (a `commitment`-bearing field on the workspace/`RuntimeState`-adjacent response, matching the existing read-only projection style of `WorkspaceOrientation*` / vault-browser models with `read_only: True`).
- Populates that field by calling slice 1's durable query path and projecting it through `query_next_and_waiting_commitments` (`app/domain/commitments.py`). The route surfaces active commitments by kind/state: next_action / waiting / review_return.
- Keeps the surface strictly read-only: no write, no mutation affordance, no state transition triggered by reading. Carries an explicit `read_only` / authority-role marker consistent with the other companion read surfaces.
- Degrades honestly: if the durable read fails or returns nothing it cannot confirm, the field reports a degraded state with a reason — never a confident empty surface that contradicts the durable source (cross-task invariant CI-2).

## Concretely

```
GET /api/companion/workspace?... (or the workspace-state endpoint)
→ response includes a commitments surface, e.g.:
   "commitments": {
     "next": [ {"commitment_id": "c-001", "kind": "next_action", "summary": "Reply to Alice", "target_ref": "projects/hiring.md"} ],
     "waiting": [ ... ],
     "review_return": [ ... ],
     "read_only": true,
     "authority_role": "derived",
     "source": "vault.commitment_artefacts"
   }
```

The surfaced set comes from the durable vault artefacts (slice 1), so it is identical across two successive requests for the same underlying state, and identical before and after a process restart.

## Why This Matters

The route is the single seam between the durable source and the human-facing UI. If it read from `AgentState`, the surface would flicker and the durability work in slice 1 would be wasted (cross-task invariant CI-1). If it returned a confident empty list when the read actually degraded, the user would be told they have no commitments when the vault says otherwise — a trust violation directly analogous to the "missing commitment is a different bug" rule in `DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md`. Read-only posture preserves the governed-transition constraint from #1960.

## Acceptance Criteria

- [ ] The companion workspace state exposes active commitments (next_action / waiting / review_return) as a read-only field.
  - Verify: `tests/api/test_companion_commitments.py::test_commitments_in_workspace_state`
- [ ] The route populates the commitment surface from the durable source (slice 1's query path), not from `AgentState`.
  - Verify: `tests/api/test_companion_commitments.py::test_commitments_surface_reads_durable_source_not_agent_state` — asserts the workspace-state production call path invokes the durable commitment query, and that commitments persisted to the vault (with no live `AgentState`) appear in the response (enforcement asserted at the route call site, not the query function in isolation).
- [ ] The commitment surface is read-only: the response carries an explicit read-only marker and the read triggers no write or state transition.
  - Verify: `tests/api/test_companion_commitments.py::test_commitment_surface_is_read_only`
- [ ] The pre-existing architecture guard flips from xfail to pass: the workspace surface exposes a commitment field.
  - Verify: `tests/api/test_arch_commitment_and_canvas.py::test_commitments_surface_in_workspace_state` passes (remove the `xfail` marker in the same PR).

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api/test_companion_commitments.py tests/api/test_arch_commitment_and_canvas.py` — runs the new surface tests and confirms the architecture guard now passes.
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api tests/companion_ui -k commitment` — broader commitment-surfacing sweep (matches #1960's Suggested Validation).
- `ruff check app tests` and `mypy app` (code-affecting change).
- Confirm the new field follows the read-only projection style of the existing companion read models (`read_only: True`, `authority_role: "derived"`).

## Out of Scope

- Commitment execution; reminders/notifications; CRE reach-out.
- Changing commitment-vs-execution-plan semantics.
- The durable persistence/query path itself (slice 1).
- Rendering the surface in the UI (slice 3).
- Any write or state-transition endpoint for commitments (transitions remain governed; this is read/proposal-only).

## Related Docs

- `docs/COMMITMENT_SURFACING/README.md`
- `docs/COMMITMENT_SURFACING/PERSIST_COMMITMENTS_AS_VAULT_ARTEFACTS.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `app/api/routes/companion.py`
- `app/domain/commitments.py`
- `tests/api/test_arch_commitment_and_canvas.py`

## Related GitHub Issues

Implements COMMITMENT_SURFACING/EXPOSE_COMMITMENTS_IN_COMPANION_ROUTE. Parent: #1960. Slice 2 — depends on slice 1 (PERSIST_COMMITMENTS_AS_VAULT_ARTEFACTS). Created `agent:blocked` until slice 1 merges, `prio:med`, `area:runtime`. Use the acceptance criteria above as the issue contract.
