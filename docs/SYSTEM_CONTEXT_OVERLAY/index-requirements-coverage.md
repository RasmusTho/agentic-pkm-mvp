---
name: Index Requirements Coverage
description: Build a 20-axis SRS coverage index mapping requirement axes to owner docs, record the deliberate scale/perf-budget absence, and absorb Wave-B deferred index rows
task_id: SBI-5
source_anchor: "docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §8, §14"
parent_capability: SYSTEM_CONTEXT_OVERLAY
prerequisites: [SBI-1]
depends_on: [define-system-context-overlay.md]
can_parallelize_with: []
---

# Index Requirements Coverage

## Purpose

No document in the repo self-identifies as a requirements baseline (repo-wide grep, zero hits per
the audit). Of twenty requirement axes the audit checked, seven are scattered and two are absent
(non-functional requirements; scalability-as-requirement) — and the deliberate single-user omission
of scale/perf budgets is nowhere stated as deliberate, so it reads as an oversight rather than a
choice (audit §8).

## What This Task Does

1. Create a thin SRS index doc (recommended: `docs/REQUIREMENTS_INDEX.md`, per audit §15 Q5's
   recommendation of a separate thin index over reusing `DOCS_INDEX.md` or the traceability matrix —
   confirm this is still the owner's preference before creating it; if the owner has answered Q5
   differently, follow that answer instead). The index reproduces the 20-axis table from audit §8
   (Mission, Purpose, Stakeholder needs, System objectives, Operational concept, System context,
   Functional requirements, Non-functional requirements, Architectural constraints, Design
   principles, Assumptions, External interfaces, Supporting systems, Quality attributes,
   Verification strategy, Lifecycle, Maintainability, Scalability, Knowledge preservation, AI
   governance), each row naming its verdict (Well-specified / Scattered / Absent) and owner doc(s)
   per the audit's table.
2. Record one sentence, in an owned doc (the new index or `docs/ARCHITECTURE.md`, whichever the
   task determines fits better), stating that scale/perf budgets are deliberately absent by
   single-user design choice — resolving audit §15 Q1's silence. If the owner has not yet answered
   Q1 (adopt an NFR section vs record deliberate absence), record the "deliberate absence" framing
   as the default and flag Q1 as still open in the index's own text, rather than blocking this task
   on the owner's answer.
3. Absorb the Wave-B deferred index rows from
   `docs/audits/DOC_STALENESS_CONSOLIDATION_2026-07-02.md` ("Deferred" section): add
   `docs/DOCS_INDEX.md` rows for `schemas/README.md` and `ops/host-setup/README.md` (both files
   exist and are currently un-indexed). Do this in the same pass as the SRS index rather than as a
   separate Wave-B follow-up, since both are index-authority work that would otherwise collide.

## Concretely

```bash
ls docs/REQUIREMENTS_INDEX.md 2>&1   # should exist after this task (or the owner's chosen alternative)
grep -c "^| " docs/REQUIREMENTS_INDEX.md   # expect 20 axis rows + header
grep -n "schemas/README.md\|ops/host-setup/README.md" docs/DOCS_INDEX.md
grep -n "scale\|perf" docs/REQUIREMENTS_INDEX.md docs/ARCHITECTURE.md
```

## Why This Matters

Without a self-identifying requirements surface, every future contributor re-derives "what are the
requirements" from scattered sources, and the two silent absences (NFRs, scale/perf budgets) keep
getting re-litigated because nothing records that the second one is deliberate. The Wave-B
absorption avoids a second index-authority pass landing on the same `DOCS_INDEX.md` rows this task
touches.

## Acceptance Criteria

- [ ] An SRS index doc exists with 20 rows, one per requirement axis, each naming its verdict and
      owner doc(s).
      Verify: doc writeback at `docs/REQUIREMENTS_INDEX.md` (or owner-chosen alternative per Q5) —
      20 axis rows present
- [ ] `docs/DOCS_INDEX.md` has rows for `schemas/README.md` and `ops/host-setup/README.md`.
      Verify: doc writeback at `docs/DOCS_INDEX.md` — two new rows
- [ ] A sentence in an owned doc records the deliberate absence of scale/perf budgets (or flags Q1
      as still open if the owner has not decided between an NFR section and a deliberate-absence
      statement).
      Verify: doc writeback at `docs/REQUIREMENTS_INDEX.md` or `docs/ARCHITECTURE.md` — one sentence
      addressing the scale/perf-budget question

## How to Verify (Pre-Merge)

1. `grep -c "^| " docs/REQUIREMENTS_INDEX.md` — 20 axis rows plus header/divider.
2. `grep -n "schemas/README.md\|ops/host-setup/README.md" docs/DOCS_INDEX.md` — both present.
3. Manual check: every "Home(s)" cell in the new index resolves to a real doc path (no dangling
   reference).
4. Confirm the scale/perf-budget sentence exists and does not silently claim an NFR section exists
   when it does not.

## Out of Scope

- Writing a full SRS or drafting NFR targets — this is an index over existing docs, not a new
  requirements document (audit §8: "Recommended revisions (not an SRS draft)").
- Answering audit §15 Q1 on the owner's behalf if genuinely undecided — flag it as open rather than
  silently choosing "adopt NFRs."
- Any other Wave-B deferred item (DOCS_INDEX slimming, archive-candidate gating, BuilderOps
  projection regen, `design_handoff/` cleanup, Companion UI capability index) — only the two named
  row-adds are absorbed here.

## Related Docs

- `docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md :: §8, §15 (Q1, Q5)`
- `docs/audits/DOC_STALENESS_CONSOLIDATION_2026-07-02.md :: Deferred`
- `docs/DOCS_INDEX.md`, `docs/architecture/traceability-matrix.md`, `docs/ARCHITECTURE.md`
- `schemas/README.md`, `ops/host-setup/README.md`

## Related GitHub Issues

One bounded issue. TCD hint: Sonnet / medium effort — the 20-row table is fully specified by audit
§8; the two Wave-B row-adds are mechanical. Escalate only if Q1/Q5 owner answers are needed and
genuinely block index placement.
