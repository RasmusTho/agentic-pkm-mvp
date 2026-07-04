---
name: Crosswalk Spine To SBS
description: Add spine-subsystem-to-SBS-boundary crosswalk rows to SBS_CURRENT_TO_TARGET_MAPPING.md, including the undocumented Capability to CAO+RCA split
task_id: SBI-3
source_anchor: "docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §4, §14"
parent_capability: SYSTEM_CONTEXT_OVERLAY
prerequisites: [SBI-1]
depends_on: [DEFINE_SYSTEM_CONTEXT_OVERLAY.md]
can_parallelize_with: []
---

# Crosswalk Spine To SBS

## Purpose

The 8-subsystem spine (`docs/MODULAR_ARCHITECTURE.md`) and the 8-macrodomain /
14-boundary SBS (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md`) coexist with no row-level mapping; docs cite
one taxonomy or the other with no way to translate between them, and the spine's "Capability"
subsystem silently splits across CAO and RCA with no doc stating so (audit §4).

## What This Task Does

Add 8 rows to `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` — one per spine subsystem — each
naming its SBS code(s). Use the reconciliation already worked out in audit §4:

- Human Surface → HIX
- Knowledge & Artifact → HKA (+ SIP)
- Runtime Projection → PDM + DRI
- **Capability → CAO + RCA** (the split no doc currently states — call this out explicitly, not as
  a single merged row)
- Agent/Orchestration → CAO
- Governance/Authority → GOV
- Integration Fabric → EBF
- Observability/Fitness → OEF

Note in the same pass (one sentence, not a new row) that WSP, SFC, MEM, EXE have no dedicated spine
ancestor — they are target-state refinements — and that this is exactly why the spine must stay a
*bridge* (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md:63`), not a competing decomposition.

This task completes `SBS_CURRENT_TO_TARGET_MAPPING.md`'s own charter (it already maps "current
areas" to target owners; spine subsystems are current areas it has not yet covered as first-class
rows) — it does not create a new mapping doc.

## Concretely

```bash
grep -n "^| " docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md | wc -l   # row count before/after
grep -n "Human Surface\|Knowledge & Artifact\|Runtime Projection\|Capability\|Agent/Orchestration\|Governance/Authority\|Integration Fabric\|Observability/Fitness" docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md
```

## Why This Matters

Without row-level crosswalk rows, any doc or agent that starts from spine vocabulary (used
throughout `docs/ARCHITECTURE.md` and `docs/MODULAR_ARCHITECTURE.md`) has no deterministic
way to find the SBS boundary that owns a given piece of functionality — it has to re-derive the
mapping from first principles each time, and the undocumented Capability split means two different
people will derive two different answers (one landing on CAO, one on RCA, both partially right).

## Acceptance Criteria

- [ ] All 8 spine subsystem names appear as row labels in `SBS_CURRENT_TO_TARGET_MAPPING.md`,
      each mapping to its SBS code(s).
      Verify: doc writeback at `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` — 8 new/updated
      rows, one per spine subsystem name
- [ ] The Capability row explicitly names both CAO and RCA, with a note that this split is not
      stated elsewhere in the repo.
      Verify: doc writeback at `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md :: Capability`
      row — contains both "CAO" and "RCA"
- [ ] A sentence notes that WSP, SFC, MEM, EXE have no dedicated spine ancestor and that the spine
      remains a bridge document, not a competing decomposition.
      Verify: doc writeback at `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` (prose note,
      not a table row)

## How to Verify (Pre-Merge)

1. `grep -n "CAO\|RCA" docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md` — confirm the Capability
   row names both.
2. Manual check: all 8 spine names from `docs/MODULAR_ARCHITECTURE.md` appear as row
   labels.
3. Confirm no existing row in `SBS_CURRENT_TO_TARGET_MAPPING.md` was altered in a way that changes
   its current meaning — this task adds rows, it does not edit existing target-owner claims.

## Out of Scope

- Changing any existing row's target-owner assignment in `SBS_CURRENT_TO_TARGET_MAPPING.md`.
- Resolving *which* SBS boundary is authoritative when the spine and SBS disagree — the crosswalk
  is a translation table, not an arbitration.
- The SoI/enabling-system classification (SBI-1) and infra classification (SBI-2) — this task is
  purely about the two internal structural taxonomies.

## Related Docs

- `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §4`
- `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md`, `docs/MODULAR_ARCHITECTURE.md`,
  `docs/SYSTEM_BREAKDOWN_STRUCTURE.md:63 (spine-as-bridge claim)`

## Related GitHub Issues

One bounded issue. TCD hint: Sonnet / medium effort — the mapping is fully specified by audit §4;
this is transcription into table rows, not new analysis.
