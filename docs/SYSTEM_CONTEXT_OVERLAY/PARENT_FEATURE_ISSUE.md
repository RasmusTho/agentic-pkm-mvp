State: **Filed as [#2833](https://github.com/RasmusTho/agentic-pkm-mvp/issues/2833) on
2026-07-03 (children #2834–#2840).** The GitHub issue is the live contract; this file is the
archived draft it was filed from.

# Parent Feature Issue — System Context Overlay (Draft)

Title shape: `docs: System Context Overlay — INCOSE/15288 context-layer vocabulary`

## Context

`docs/audits/YGGDRASIL_SYSTEM_BOUNDARY_INCOSE_2026-07-03.md` found that Mimer's internal
boundary discipline is strong and code-verified, but nothing classifies the *external things* the
system runs on or beside (Postgres, Ollama, Docker/Colima, Tailscale, iCloud, GitHub, Obsidian) as
SoI elements, enabling systems, or external systems — the same Ollama is described as both an
"optional external provider" and a first-party compose service; the same Postgres as both extension
fabric and an external durable store. The audit also found two structural taxonomies (the 8-subsystem
spine and the 8-macrodomain/14-boundary SBS) with no row-level crosswalk, and confirmed no document
self-identifies as a requirements baseline across twenty requirement axes. Per audit §13, every
finding is classified `Conform`, `Extend`, or `Reshape (routed)`; no reshape is enacted by the audit
itself. This feature makes the `Extend`/`Conform` findings executable and routes the one `Reshape`
item to an owner decision.

## Implementation Tasks

Specification directory: `docs/SYSTEM_CONTEXT_OVERLAY/` (see `README.md` for the full task index,
dependency order, and cross-task invariants).

1. [DEFINE_SYSTEM_CONTEXT_OVERLAY.md](DEFINE_SYSTEM_CONTEXT_OVERLAY.md) — SBI-1
2. [CLASSIFY_DEPLOYED_INFRASTRUCTURE.md](CLASSIFY_DEPLOYED_INFRASTRUCTURE.md) — SBI-2
3. [CROSSWALK_SPINE_TO_SBS.md](CROSSWALK_SPINE_TO_SBS.md) — SBI-3
4. [FIX_REGISTER_AND_CHARTER_HYGIENE.md](FIX_REGISTER_AND_CHARTER_HYGIENE.md) — SBI-4
5. [INDEX_REQUIREMENTS_COVERAGE.md](INDEX_REQUIREMENTS_COVERAGE.md) — SBI-5
6. [COMPLETE_PENDING_BOUNDARY_CHARTERS.md](COMPLETE_PENDING_BOUNDARY_CHARTERS.md) — SBI-7
7. [ROUTE_RESHAPE_DECISIONS_TO_OWNER.md](ROUTE_RESHAPE_DECISIONS_TO_OWNER.md) — SBI-8 (owner-gated;
   `agent:needs-human`, never `agent:ready`)

SBI-6 is deliberately unallocated (folded into SBI-1's functional-allocation pointer; see
`README.md :: SBI-6`).

## Scope

Outcome boundary: the architecture spine and SBS docs gain a consistent 15288 context-layer
vocabulary (SoI, enabling system, COTS-in-deployed-configuration, external system), the two existing
structural taxonomies are cross-walked, the register's self-reported anchors are corrected, a thin
requirements-coverage index exists, the three pending boundary charters (EBF, HIX, DRI) are
completed, and the two reshape-routed items (SoS spine-doc naming, `DESIGN_PRINCIPLES.md` §9
wording) have an owner decision on record. No runtime code changes; no owner-doc authority moves;
no new SBS boundary or subsystem is created.

## Acceptance Criteria

- [ ] SBI-1 overlay doc exists and is linked from the spine, SBS, and glossary.
      Verify: doc writeback at `docs/architecture/ :: system-context-overlay` (exact filename set by
      SBI-1) + `docs/GLOSSARY.md :: System of Systems` entry
- [ ] SBI-2 classification column/section exists in `docs/ARCHITECTURE.md :: System Context
      (Current)` covering every compose service and host process, with Ollama's dual binding
      resolved.
      Verify: doc writeback at `docs/ARCHITECTURE.md :: System Context (Current)`
- [ ] SBI-3 crosswalk rows exist in `SBS_CURRENT_TO_TARGET_MAPPING.md` for all 8 spine subsystems,
      including the Capability→CAO+RCA split.
      Verify: doc writeback at `docs/architecture/SBS_CURRENT_TO_TARGET_MAPPING.md`
- [ ] SBI-4 register/charter fixes (C1, C2, C3, C4, C6, C7) land.
      Verify: doc writeback at `docs/architecture/SBS_BOUNDARY_REGISTER.md`,
      `docs/boundaries/SIP.md`, `docs/boundaries/OEF.md`, `docs/architecture/SBS_TRANSITION_DEBT.md`,
      `docs/LLM.md`, `docs/EMBEDDINGS.md`, `docs/INVENTORY.md`
- [ ] SBI-5 requirements-coverage index exists with 20 axis rows and absorbs the Wave-B deferred
      index rows.
      Verify: doc writeback at new index doc + `docs/DOCS_INDEX.md` rows for `schemas/README.md`
      and `ops/host-setup/README.md`
- [ ] SBI-7 completes EBF, HIX, DRI charters; `docs/boundaries/README.md` shows 14/14.
      Verify: doc writeback at `docs/boundaries/EBF.md`, `docs/boundaries/HIX.md`,
      `docs/boundaries/DRI.md`, `docs/boundaries/README.md`
- [ ] SBI-8 produces an ADR (or explicit owner decline) for the SoS naming and
      `DESIGN_PRINCIPLES.md` §9 reshape questions.
      Verify: doc writeback at `docs/adr/` (new ADR) or an explicit decline recorded in
      `docs/SYSTEM_CONTEXT_OVERLAY/ROUTE_RESHAPE_DECISIONS_TO_OWNER.md`

## Verification Path

Each task's `Verify:` targets (doc writeback anchors — this is a docs-only capability, no test
suite) must resolve on `main` before the next dependent task starts. See each task file's
`## Acceptance Criteria` and `## How to Verify (Pre-Merge)`.

## Validation / Acceptance Path

- After each child merges, post a one-line validation receipt here (doc path + anchor confirmed).
- Acceptance is complete when all seven task files' acceptance criteria are verified on `main` and
  `docs/DOCS_INDEX.md` reflects every new/changed doc.
- No owner-doc promotion PR is needed beyond the task PRs themselves — this capability *is* owner-doc
  work (extending existing owner docs), not a runtime capability requiring separate promotion.
- SBI-8 closes independently of the other six: its acceptance is an ADR or recorded decline, not a
  runtime or doc-authority change, and it may close before or after the others depending on when the
  owner answers Q2/Q4.

## Role

Validation hub while SBI-1/2/3/4/5/7/8 children are outstanding (expected to file as `Backlog` +
`agent:blocked` until the first child, SBI-1, is `agent:ready`). Each delivered child posts a
validation receipt here before the next dependent child is picked up. SBI-4 and SBI-7 have no
dependency on SBI-1 and may be marked `agent:ready` immediately at filing.

## Closure condition

All capability acceptance criteria above verified on `main`, and every child issue closed (SBI-8
closes via ADR-or-decline, not via a code/doc merge of the reshape itself — the reshape enactment,
if any, is a separate future issue owned by `docs/architecture/SBS_OPERATIONALIZATION_PLAN.md`).
