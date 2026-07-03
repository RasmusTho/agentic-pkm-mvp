---
name: Complete Pending Boundary Charters
description: Write the three remaining boundary charters (EBF first, then HIX, DRI) to reach 14/14 charter coverage
task_id: SBI-7
source_anchor: "docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §6, §14"
parent_capability: SYSTEM_CONTEXT_OVERLAY
prerequisites: []
depends_on: []
can_parallelize_with: [define-system-context-overlay.md, fix-register-and-charter-hygiene.md]
---

# Complete Pending Boundary Charters

## Purpose

Charter coverage is 11/14: HIX, EBF, and DRI charters remain pending
(`docs/architecture/traceability-matrix.md:79`, `docs/boundaries/README.md:59,64,66`). EBF's absence
is the most consequential — it is the SoI edge this overlay's classification work attaches to, and
both EXE and SFC charters already delegate real responsibilities to it
(`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:1481`, `:522`). This is already-tracked #2533-line charter
work; this task extends it, it is not a new hub.

## What This Task Does

Write `docs/boundaries/EBF.md`, `docs/boundaries/HIX.md`, and `docs/boundaries/DRI.md` using the
existing charter template (`docs/boundaries/_template.md`) and following the pattern of the eleven
already-written charters (Purpose, Owns, Does not own, Inputs/Outputs, Calls allowed/forbidden,
Invariants, Failure modes, Required tests). Order matters — write EBF first:

- **EBF (External Boundary Fabric)** — owns "external mechanisms do not become authority"
  (its primary invariant per `docs/boundaries/README.md`). It is the container for the deliberate
  integration-lifecycle-management gap the audit names (audit §7: "no runtime integration registry,"
  provider identity/versioning assigned to EBF, `SYSTEM_BREAKDOWN_STRUCTURE.md:717`) — the charter
  should state that gap as an owned-but-not-yet-implemented responsibility, not silently omit it.
  Both EXE (`SYSTEM_BREAKDOWN_STRUCTURE.md:1481`) and SFC (`:522`) charters already reference EBF
  responsibilities; this charter must not contradict what they already assume EBF owns.
- **HIX (Human Interaction & Intent)** — primary invariant "human action is explicit and
  attributable" per `docs/boundaries/README.md`. Consult `docs/HUMAN-FLOWS.md` and
  `docs/CONCEPTS/USER_NEEDS_MODEL.md` for the responsibility surface already described in prose.
- **DRI (Derived Representation & Indexing)** — primary invariant "derived representations are
  rebuildable and never source of truth" per `docs/boundaries/README.md`. Consult
  `docs/SYSTEM_OF_SYSTEMS_ARCHITECTURE.md:58` (extension fabric) and the SBI-2 classification work
  (COTS/rebuildable framing) for consistency, but do not block on SBI-2 landing first — DRI's
  charter is about the boundary's *responsibility*, not the infra classification.

Update `docs/boundaries/README.md`'s coverage table (14/14) and remove the "pending" notes at
`docs/architecture/traceability-matrix.md:79`.

## Concretely

```bash
ls docs/boundaries/EBF.md docs/boundaries/HIX.md docs/boundaries/DRI.md
grep -n "Pending" docs/boundaries/README.md   # expect no matches after this task
grep -n "HIX, EBF, and DRI remain pending" docs/architecture/traceability-matrix.md  # expect gone
```

## Why This Matters

EBF, HIX, and DRI are cited as call-targets and responsibility-holders by charters that already
exist (EXE, SFC, RCA/PDM respectively) — an incomplete charter set means those references point at
undefined territory, and the audit's own classification work (SBI-1/SBI-2) needs EBF's charter to
exist so the "port/adapter is always a SoI element" rule has an owning boundary to attach to.

## Acceptance Criteria

- [ ] `docs/boundaries/EBF.md`, `docs/boundaries/HIX.md`, `docs/boundaries/DRI.md` exist, each
      following the `_template.md` structure.
      Verify: doc writeback at `docs/boundaries/EBF.md`, `docs/boundaries/HIX.md`,
      `docs/boundaries/DRI.md` — all sections from `_template.md` present in each
- [ ] `docs/boundaries/README.md` shows 14/14 charter coverage (no "Pending" entries remain in the
      coverage table).
      Verify: doc writeback at `docs/boundaries/README.md` — coverage table has zero "Pending"
      cells
- [ ] `docs/architecture/traceability-matrix.md`'s pending note (line ~79) is removed or updated to
      reflect full coverage.
      Verify: doc writeback at `docs/architecture/traceability-matrix.md` — "HIX, EBF, and DRI
      remain pending" sentence no longer present
- [ ] EBF's charter states the integration-lifecycle-management gap as an owned-but-not-yet-built
      responsibility, consistent with EXE and SFC's existing references to EBF.
      Verify: doc writeback at `docs/boundaries/EBF.md :: Owns` — integration lifecycle management
      named explicitly

## How to Verify (Pre-Merge)

1. `diff <(grep "^## " docs/boundaries/_template.md) <(grep "^## " docs/boundaries/EBF.md)` (repeat
   for HIX, DRI) — confirm section parity with the template.
2. `grep -n "Pending" docs/boundaries/README.md` — expect no output.
3. `grep -n "EBF" docs/boundaries/EXE.md docs/boundaries/SFC.md` — confirm the new EBF charter does
   not contradict what these already assume EBF owns.
4. `grep -n "pending" docs/architecture/traceability-matrix.md` — expect no stale pending note.

## Out of Scope

- Implementing any EBF/HIX/DRI runtime module — charters are control-boundary contracts, not
  service declarations (`docs/boundaries/README.md :: Relationship to the SBS`).
- The integration-lifecycle-management mechanism itself (a future EBF-owned build) — this task only
  states it is EBF's responsibility.
- Resolving the dual-role infrastructure hazard named at EXE/OEF's attachment points — deferred to
  the companion thread per audit §2.

## Related Docs

- `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §6`
- `docs/boundaries/README.md`, `docs/boundaries/_template.md`, `docs/architecture/traceability-matrix.md`
- `docs/boundaries/EXE.md` (line 1481 reference), `docs/boundaries/SFC.md` (line 522 reference)
- `docs/HUMAN-FLOWS.md`, `docs/CONCEPTS/USER_NEEDS_MODEL.md` (HIX responsibility surface)
- Epic #2533 (architecture-foundation backlog this charter set belongs to)

## Related GitHub Issues

Recommend three issues (one per charter: EBF, HIX, DRI) sharing this task file, filed in that
order since EBF is the higher-consequence charter other boundaries already assume exists — or one
bounded issue if the implementing agent judges the three charters cheap enough to land together.
TCD hint: Sonnet / high effort per charter (real design-boundary judgment, matching the effort the
existing eleven charters required) — not mechanical transcription like the other SBI tasks.
