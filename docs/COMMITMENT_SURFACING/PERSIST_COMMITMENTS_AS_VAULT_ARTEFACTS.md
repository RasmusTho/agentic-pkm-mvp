---
name: Persist Commitments As Vault Artefacts
description: Persist CommitmentRecords as agent-maintained durable vault artefacts in the companion-note family; read/proposal-only, WriteGuard-governed, survives restart
task_id: COMMITMENT-SURFACING-01
source_anchor: docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md :: Primary concepts
parent_capability: Commitment Surfacing
prerequisites: []
depends_on: []
can_parallelize_with: []
---

State: Specification for the durable commitment foundation. Slice 1 of the COMMITMENT_SURFACING capability (parent #1960). Code-affecting.

# Persist Commitments As Vault Artefacts

## Purpose

Surfacing commitments to the human is only trustworthy if the commitments are **durable**. Today `CommitmentRecord`s have no persistence path — the planner attaches ephemeral `CommitmentHandle`s to the in-memory `AgentState`, which evaporates per request. This task creates the durable foundation: persist `CommitmentRecord`s (kind / state / target_ref / summary / source_goal) as agent-maintained vault artefacts in the **companion-note family**, so the later API and UI slices read from a stable source that survives a process restart. Per the owner decision (#1960, 2026-06-15), the substrate is the vault — not a new DB, not transient `AgentState`.

## What This Task Does

- Adds a durable persistence + query path for `CommitmentRecord`s, stored as agent-maintained vault artefacts in the companion-note family (system surface; not human-authored notes), following the existing companion-note substrate (`app/services/companion_note.py`, `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`) and the `materialize_promoted_memory` write pattern (`app/agent_memory/materialization.py`): WriteGuard asserted before a single complete file write, vault-relative path, layout-aware system folder via `get_vault_system_dir_rel()`.
- Persists the full `CommitmentRecord` shape: `commitment_id`, `commitment_kind` (open_loop / project / next_action / waiting / review_return), `state` (the `CommitmentState` family: unknown / open / next / waiting / blocked / done), `target_ref`, `summary`, `source_goal`.
- **Optional commitment-layer provenance (full-fidelity surface extension).** Four further optional frontmatter fields are persisted *only when present* so the read-only surface can render the design's provenance lines without ever fabricating data (`docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`: a waiting item depends on an actor/event; a review cycle recurs on a cadence). On `waiting` commitments: `waiting_on` (the actor/event awaited) and `waiting_since` (ISO date). On `review_return` commitments: `review_cadence` (e.g. `weekly`) and `last_reviewed` (ISO date; the surface API derives the relative "Nd ago" form server-side). An absent value is never written as an empty key and is rendered as an omitted line — never a guess.
- Provides a read/query function returning persisted `CommitmentRecord`s for the surfacing slices (reusing `query_next_and_waiting_commitments` from `app/domain/commitments.py` for the next/waiting projection rather than re-implementing it).
- Keeps writes **read/proposal-only and WriteGuard-governed**: every persistence write asserts `DEFAULT_WRITE_GUARD.assert_writes_allowed(...)` before touching the filesystem; a blocked guard raises and writes nothing (atomic-or-absent).
- **Pins the artefact shape** against the contract before implementing: decide and document whether a commitment is its own vault artefact (`vault/<system_dir>/commitments/<id>.md` style) or a section within the related note's companion note. Pin it against `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md` (a commitment is not reducible to a note; the absence of a canonical note does not mean the commitment does not exist) and `docs/COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_STATE_TRANSITIONS.md` (the `CommitmentState` family must persist unchanged — never collapsed into `review_state` / `maturity`).

## Concretely

```python
# Persist (read/proposal-only, WriteGuard-governed):
record = CommitmentRecord(
    commitment_id="c-001",
    commitment_kind="next_action",
    state="next",
    target_ref="projects/hiring.md",
    summary="Reply to Alice about the offer",
    source_goal="close the hiring loop",
)
persist_commitment(record, vault_context=ctx)   # asserts WriteGuard, writes one complete artefact

# ... process restart ...

# Query (the surfacing slices call this, NOT AgentState):
records = load_commitments(vault_context=ctx)
assert any(r.commitment_id == "c-001" and r.state == "next" for r in records)
result = query_next_and_waiting_commitments(records)   # reuse existing domain query
assert result.next_items[0].commitment_id == "c-001"
```

Expected: the artefact exists in the vault under the system-owned commitment folder, carries the full `CommitmentRecord` shape, and is re-readable after a restart with state intact. When the WriteGuard reports a write-blocked runtime state, `persist_commitment` raises `WritesBlockedError` and leaves no artefact on disk.

## Why This Matters

If commitments are not durable, the surface flickers: a commitment shown one request is gone the next, and the user stops trusting the system to carry their open loops — the exact failure the cognitive-prosthetic capability exists to prevent (`docs/COMMITMENT_AS_FIRST_CLASS/README.md`). Persisting in the vault (companion-note family) rather than a new DB honors the v6.0 DB-schema-deferral non-goal and keeps the durable source portable with the vault and inspectable by the human. If the artefact shape collapsed commitment state into note `review_state`/`maturity`, it would violate the state-axes contract and re-flatten the very distinction the commitment layer protects.

## Acceptance Criteria

- [ ] `CommitmentRecord`s persist as agent-maintained vault artefacts in the companion-note family, carrying the full shape (commitment_id / commitment_kind / state / target_ref / summary / source_goal), and are re-readable after a simulated process restart with state intact.
  - Verify: `tests/commitments/test_commitment_persistence.py::test_commitment_survives_restart`
- [ ] The persistence write path asserts the WriteGuard at its production call site; a write-blocked runtime state raises `WritesBlockedError` and leaves no artefact on disk (atomic-or-absent).
  - Verify: `tests/commitments/test_commitment_persistence.py::test_persist_blocked_by_writeguard` — patches the runtime state to a write-blocked state and asserts the production `persist_commitment` call raises and writes nothing (enforcement asserted at the call site, not the guard in isolation).
- [ ] The query path returns persisted `CommitmentRecord`s and feeds `query_next_and_waiting_commitments` without collapsing commitment state into note `review_state`/`maturity` axes.
  - Verify: `tests/commitments/test_commitment_persistence.py::test_load_feeds_next_and_waiting_query`
- [ ] The artefact-shape decision (own-artefact vs companion-note section) is pinned in this task's PR description and reflected in the implementation, consistent with `COMMITMENT_LAYER_CONTRACT.md` and `DEFINE_COMMITMENT_STATE_TRANSITIONS.md`.
  - Verify: doc/decision target — PR body records the pinned shape with a one-line rationale citing `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md :: Relation to artifacts`; the chosen path/shape is asserted by `tests/commitments/test_commitment_persistence.py::test_commitment_survives_restart`.

## How to Verify (Pre-Merge)

- `pytest -q tests/commitments/test_commitment_persistence.py` — runs the restart-survival, WriteGuard-enforcement, and query-feed assertions above.
- `ruff check app tests` and `mypy app` (code-affecting change).
- Read the new persistence module side-by-side with `app/services/companion_note.py` and `app/agent_memory/materialization.py` to confirm the write path matches the established WriteGuard-before-single-file-write pattern.
- Read the artefact frontmatter side-by-side with `docs/CONCEPTS/STATE_AXES_CONTRACT.md` to confirm no commitment state value is written into a `review_state`/`maturity` field.

## Out of Scope

- Commitment execution; reminders/notifications; CRE reach-out.
- Changing commitment-vs-execution-plan semantics.
- Exposing commitments through the companion route (slice 2) or rendering them in the UI (slice 3).
- Designing a new receipt store (commitment transitions remain receipt-bearing via the existing path per `DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md`; this slice does not invent one).
- Automatic/heuristic state transitions or auto-closure (forbidden by `DEFINE_COMMITMENT_STATE_TRANSITIONS.md`).

## Restart / Durability Posture

This slice ships the durable state that all downstream surfacing depends on, so its restart posture is the trust foundation of the whole capability.

- **Survives restart:** the persisted commitment artefacts in the vault (system-owned commitment folder, companion-note family). After a process restart, `load_commitments` returns the same `CommitmentRecord`s with the same `state` values. This is the explicit goal — the surface must not flicker.
- **Does NOT survive restart (and must not be the source):** the in-memory `AgentState` `CommitmentHandle`s the planner attaches per request. They are ephemeral by design. This slice must never make the durable surface depend on them.
- **Trust consequence if durability is not honored:** if commitments were surfaced from `AgentState`, a restart (or even the next request) would make a commitment the user was shown disappear — the user would conclude the system silently dropped a responsibility, and trust in the cognitive prosthetic collapses. Durable persistence in the vault is precisely the defense; that is why this slice is the prerequisite for slices 2 and 3.
- **Degraded-write posture:** when the WriteGuard blocks (degraded runtime state), persistence raises and writes nothing rather than leaving a half-written artefact. A blocked write honestly means "not persisted", not "persisted in an indeterminate state".

## Related Docs

- `docs/COMMITMENT_SURFACING/README.md`
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`
- `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
- `docs/COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_STATE_TRANSITIONS.md`
- `docs/COMMITMENT_AS_FIRST_CLASS/DEFINE_COMMITMENT_RECEIPT_REQUIREMENT.md`
- `app/domain/commitments.py`
- `app/services/companion_note.py`
- `app/agent_memory/materialization.py`

## Related GitHub Issues

Implements COMMITMENT_SURFACING/PERSIST_COMMITMENTS_AS_VAULT_ARTEFACTS. Parent: #1960. Slice 1 of the capability — the durable foundation slices 2 and 3 depend on. Created as `Status=Ready` / `agent:ready`, `prio:med`, `area:runtime`. Use the acceptance criteria above as the issue contract.
