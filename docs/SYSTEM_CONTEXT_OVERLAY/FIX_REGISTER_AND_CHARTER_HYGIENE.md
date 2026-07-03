---
name: Fix Register And Charter Hygiene
description: Fix six self-reported SBS register/charter divergences (C1,C2,C3,C4,C6,C7) found by the audit
task_id: SBI-4
source_anchor: "docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §6 (C1,C2,C3,C4,C6,C7), §14"
parent_capability: SYSTEM_CONTEXT_OVERLAY
prerequisites: []
depends_on: []
can_parallelize_with: [DEFINE_SYSTEM_CONTEXT_OVERLAY.md, COMPLETE_PENDING_BOUNDARY_CHARTERS.md]
---

# Fix Register And Charter Hygiene

## Purpose

Audit §6 found six divergences between the SBS register/charters and either the code or each
other. Per audit §13, all six are `Conform` (or `Extend` for C3) — corrections the register/charter
framework already demands of itself, not new architecture decisions. Most are self-tracked already
(see status column below); the audit adds only what the register itself gets wrong.

## What This Task Does

Fix each divergence independently (they touch different files and can land in any order within this
task, or be split into sub-PRs if that is cheaper):

- **C1** — `docs/architecture/SBS_BOUNDARY_REGISTER.md:33` anchors SIP's registered runtime module
  to `app/index/embeddings.py`, an embedding/provider wrapper that SIP's own charter
  (`docs/boundaries/SIP.md:32,55-58`) assigns to DRI and forbids treating as semantic authority.
  Fix: correct the register anchor to SIP's actual module, or mark it "no current module" if none
  exists, consistent with the register's own disclaimer convention.
- **C2** — `SBS_BOUNDARY_REGISTER.md:43` anchors OEF to a hybrid-latency metrics file
  (`app/fitness/metrics.py`); `TraceEvent`/`FitnessRule` types exist nowhere in `app/`. Already
  partially self-tracked ("Partial current CI"). Fix: annotate the register row to state plainly
  that the anchor is a partial/metrics-only surface, not the full OEF charter surface, matching what
  is actually implemented.
- **C3** — MEM contract name split: charter + schema say `MemoryItem`
  (`docs/boundaries/MEM.md:23`, `schemas/memory-item.schema.json`); SBS Part 5 + code say
  `MemoryRecord` (`app/agent_memory/memory_record.py:87`); only the latter has code. Fix: this is a
  CES glossary decision (routes through `docs/boundaries/CES.md` practice) — record which name wins
  and reconcile the losing name's references. Do not silently pick one without the CES step; if a
  CES decision is out of this task's bounded scope, record the split explicitly as a tracked
  divergence in `SBS_TRANSITION_DEBT.md` instead of resolving it unilaterally.
- **C4** — Charter "calls allowed" contradicts the SBS Part 5 dependency table: RCA's charter omits
  HKA (`docs/boundaries/RCA.md:49` vs `SYSTEM_BREAKDOWN_STRUCTURE.md:1444`); CAO's charter omits
  HKA/SIP while SBS grants "HKA read contracts" (`docs/boundaries/CAO.md:47` vs `:1446`). Fix: sync
  direction follows `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`, because its Part 4/5 dependency model and
  ownership matrix are the declared source for boundary charters (the matrix section states it "is
  the intended source for future architecture-fitness rules (OEF) and boundary charters (CES)").
  Rows where the sync merely restates the SBS — RCA gaining HKA in "calls allowed" — are mechanical
  and can be applied directly. The row that widens a charter's authority surface — CAO gaining "HKA
  read contracts," against `CAO.md`'s own reach-around caution — must be routed through the CES
  stewardship channel, with a one-line note in the PR, rather than silently applied.
- **C6** — Live PDM storage-leak failure mode with no debt row: direct `psycopg` + raw SQL in
  `app/api/routes/search.py:6,18,41-46` and `app/store/vector_store.py:5,20,27-38`, a failure mode
  the PDM charter names by name (`docs/boundaries/PDM.md:82`) but that has no row in
  `SBS_TRANSITION_DEBT.md`. Fix: add one debt row (mechanical — the failure mode and its evidence
  are already fully specified by the audit; this task only records it in the register's own format).
- **C7** — Two legacy `app/llm/*` modules, cited by different docs. `app/llm/adapter.py` has zero
  runtime importers and is cited as the provider surface by `docs/INVENTORY.md:22-25`.
  `app/llm/embeddings.py::PROVIDER_REGISTRY` is cited as the adapter registry by `docs/LLM.md:31`
  and `docs/EMBEDDINGS.md:227`. The live canonical access layer for both is `app/components/llm/`,
  and `tests/architecture/test_import_rules.py:104-119` already enforces the split the docs do not
  describe. Fix: mark **both** legacy modules superseded in their citing docs — `app/llm/adapter.py`
  in `docs/INVENTORY.md`; `app/llm/embeddings.py` in `docs/LLM.md` and `docs/EMBEDDINGS.md` — and
  point all three at `app/components/llm/` (`docs/COMPONENTS.md:95`).

## Concretely

```bash
grep -n "app/index/embeddings.py" docs/architecture/SBS_BOUNDARY_REGISTER.md   # C1: should be gone/corrected
grep -n "app/llm/adapter.py" docs/INVENTORY.md                                 # C7: must read "superseded"
grep -n "app/llm/embeddings.py" docs/LLM.md docs/EMBEDDINGS.md                 # C7: must read "superseded"
grep -rn "MemoryItem\|MemoryRecord" docs/boundaries/MEM.md schemas/memory-item.schema.json app/agent_memory/memory_record.py
diff <(grep -A5 "^| RCA" docs/SYSTEM_BREAKDOWN_STRUCTURE.md) docs/boundaries/RCA.md  # C4 spot check
grep -n "search.py\|vector_store.py" docs/architecture/SBS_TRANSITION_DEBT.md        # C6: new row present
```

## Why This Matters

A register or charter that misreports its own anchors is worse than one with a gap it admits to —
it actively misleads the next agent that trusts it (C1/C2 would have been caught by a machine-
checkable invariant, INV-SB2, if one existed; this task is the manual fix that invariant would
otherwise have to catch repeatedly). C7 in particular means three docs currently point contributors
at legacy `app/llm/*` modules — one dead, one still a de facto registry — as if either were the
live surface.

## Acceptance Criteria

- [ ] `SBS_BOUNDARY_REGISTER.md:33` no longer anchors SIP to `app/index/embeddings.py`.
      Verify: doc writeback at `docs/architecture/SBS_BOUNDARY_REGISTER.md` — SIP row corrected or
      marked "no current module"
- [ ] `SBS_BOUNDARY_REGISTER.md:43`'s OEF row is annotated as partial/metrics-only, matching actual
      `app/` coverage.
      Verify: doc writeback at `docs/architecture/SBS_BOUNDARY_REGISTER.md` — OEF row annotation
      present
- [ ] One contract name for MEM is recorded across charter, schema, and SBS Part 5 — or, if a CES
      decision is out of scope, the split is explicitly logged as a tracked row in
      `SBS_TRANSITION_DEBT.md`.
      Verify: doc writeback at `docs/boundaries/MEM.md`, `schemas/memory-item.schema.json`,
      `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` (Part 5) all agree, OR
      `docs/architecture/SBS_TRANSITION_DEBT.md` has a new `MemoryItem`/`MemoryRecord` row
- [ ] RCA and CAO charter "calls allowed" lists match the SBS Part 5 dependency table (HKA for RCA;
      HKA/SIP for CAO).
      Verify: doc writeback at `docs/boundaries/RCA.md`, `docs/boundaries/CAO.md`
- [ ] `SBS_TRANSITION_DEBT.md` has a new debt row for the live PDM storage-leak failure mode named
      at `docs/boundaries/PDM.md:82`.
      Verify: doc writeback at `docs/architecture/SBS_TRANSITION_DEBT.md` (new row citing
      `app/api/routes/search.py` and `app/store/vector_store.py`)
- [ ] `docs/INVENTORY.md` marks `app/llm/adapter.py` as superseded, and `docs/LLM.md` +
      `docs/EMBEDDINGS.md` mark `app/llm/embeddings.py` as superseded, all pointing to
      `app/components/llm/`.
      Verify: `grep -n "app/llm/adapter.py" docs/INVENTORY.md` and
      `grep -n "app/llm/embeddings.py" docs/LLM.md docs/EMBEDDINGS.md` return only
      superseded-marked references

## How to Verify (Pre-Merge)

1. `grep -n "app/index/embeddings.py" docs/architecture/SBS_BOUNDARY_REGISTER.md` — expect no match
   (or a corrected anchor).
2. `grep -rn "app/llm/adapter.py\|app/llm/embeddings.py" docs/` — every hit is annotated superseded.
3. Manual diff of RCA/CAO charter "calls allowed" against
   `docs/SYSTEM_BREAKDOWN_STRUCTURE.md :: Part 4 - Dependency Model`.
4. `grep -n "search.py\|vector_store.py" docs/architecture/SBS_TRANSITION_DEBT.md` — new row present.
5. Confirm the MEM name decision either landed consistently in all three surfaces or is logged as an
   explicit open debt row — no silent partial fix.

## Out of Scope

- C5, C8, and the other audit §6 divergences already self-tracked as D2/D5/D6/D13/D14 in
  `SBS_TRANSITION_DEBT.md` — those need no new work, they are correctly recorded already.
- Fixing the underlying PDM storage-leak code itself (C6 only adds the debt row; the leak fix is
  separate runtime work, not a docs-hygiene task).
- Removing `app/llm/adapter.py` or `app/llm/embeddings.py` from the codebase — C7 only fixes the
  docs that present them as canonical; deletion (if warranted) is a separate code-change decision.
- Any register/charter change beyond the six named divergences.

## Related Docs

- `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §6`
- `docs/architecture/SBS_BOUNDARY_REGISTER.md`, `docs/architecture/SBS_TRANSITION_DEBT.md`,
  `docs/boundaries/SIP.md`, `docs/boundaries/OEF.md`, `docs/boundaries/MEM.md`,
  `docs/boundaries/RCA.md`, `docs/boundaries/CAO.md`, `docs/boundaries/PDM.md`, `docs/boundaries/CES.md`
- `docs/LLM.md`, `docs/EMBEDDINGS.md`, `docs/INVENTORY.md`, `docs/COMPONENTS.md`
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` (Part 5 dependency table, lines 1413-1483)

## Related GitHub Issues

One bounded issue, or split into up to six micro-issues (one per Cx item) if the implementing agent
finds any single fix (especially C3's CES step) needs its own review cycle. TCD hint: Sonnet /
medium effort for C1/C2/C6/C7 (mechanical, evidence fully specified); Sonnet / high effort if C3's
CES glossary decision or C4's dependency-table reconciliation surfaces a genuine disagreement not
resolvable from the audit text alone — escalate rather than guess which name/dependency wins.
