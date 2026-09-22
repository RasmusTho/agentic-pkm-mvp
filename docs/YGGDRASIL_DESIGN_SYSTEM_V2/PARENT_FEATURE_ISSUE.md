# Parent feature — Yggdrasil Design System v2

State: Filed live validation hub #5626 (`agent:blocked`, `action:wait-dependency`). The GitHub issue is
the authoritative backlog and validation surface. It is never direct pickup work and claims no
shipped capability.

## Context

The live Claude Design "Yggdrasil Design System" is marked Legacy. Its token sheet is copied by hand
into several consumers, and many surfaces bypass it. The owner approved the v2 refinement
(PR #5617): one generated token source, Dark kept as default, Yggdrasil Light "Shell" on trial,
density profiles, and adoption across Companion, Builder System UIs, and Bifrost.

## Scope

Validate delivery of `docs/YGGDRASIL_DESIGN_SYSTEM_V2/`: the token source and generator, live
Claude Design reconciliation, Companion and Builder migration, Bifrost adoption, and governance
promotion.

## Source Anchors

- `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Rollout`
- `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/DESIGN_PRINCIPLES.md :: 11. Shared Visual Language`

## SBS Impact

- Primary subsystem: Product System, Companion UI visual layer.
- Secondary subsystem(s): Builder System UIs (Cockpit, DevUI, Signboard, CKM), Bifrost constituent.
- Write class: presentation and tokens. Also governance docs in the final child.
- Persistence impact: per-user theme preference only (YDS-03).
- Derived/rebuildable impact: every token output is generated from the DTCG source.
- New or changed contract: token source, theme and density attributes, and design-gate hash.
- Owner-doc impact: promoted in YDS-06 only.
- Transition debt impact: retires hand-copied token sheets and local palettes.
- Boundary risk: Builder UI and Product UI share visual language only, not authority.

## Constraints

- No implementation is performed from this parent.
- No Dark token value or name changes within v2.
- Shell stays a per-user trial choice until the owner decides in YDS-06.
- YDS-01 and YDS-02 land back to back, because the live gate fails closed between them.

## Acceptance Criteria

- [ ] Every child is terminal with an exact-merge receipt on this issue, including the YDS-05 PR in
  `RasmusTho/bifrost`.
  - Verify: doc writeback at `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md :: Rollout`
- [ ] The live design system is in byte parity with the binding sheet, and the owner confirms it no
  longer shows as Legacy.
  - Verify: doc writeback at `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md :: Yggdrasil design-system gate`
- [ ] The Shell trial outcome and the governance promotion are recorded.
  - Verify: doc writeback at `docs/DESIGN_PRINCIPLES.md :: 11. Shared Visual Language`

## Implementation Tasks

In execution order:

1. `ESTABLISH_TOKEN_SOURCE_AND_GENERATOR.md` (YDS-01, #5627). The only child ready at filing.
2. `RECONCILE_LIVE_DESIGN_SYSTEM.md` (YDS-02, #5628). Right after YDS-01; the owner starts `/design-sync`.
3. `MIGRATE_COMPANION_SURFACES.md` (YDS-03, #5629) and `MIGRATE_BUILDER_SURFACES.md` (YDS-04, #5630). These can
   run in parallel.
4. `ADOPT_TOKENS_IN_BIFROST.md` (YDS-05). Filed in `RasmusTho/bifrost` after YDS-01.
5. `PROMOTE_DESIGN_SYSTEM_GOVERNANCE.md` (YDS-06, #5631). Final child, after YDS-05; carries the
   parent-closure handoff.

## Verification Path

Each child carries its own tests or doc-writeback targets. YDS-01's freshness and contrast tests
guard every later change to the tokens.

## Validation / Acceptance Path

This parent stays `agent:blocked` with `action:wait-dependency` until the children are terminal.
Each child posts an exact-SHA receipt here. After YDS-03, the owner uses Shell in the Companion and
records the trial decision here. YDS-06 re-reads live Issue and PR state, records the owner-doc
disposition, and hands this issue to `verification-and-closure`.

## Out of Scope

- Redesigning individual surfaces, renaming tokens, or Shell on iOS before the trial graduates.

## Suggested Validation

- Run each child's `Verify:` targets on its PR head.
- `python3 design-system/yggdrasil/build.py --check` on `main` after each merge.

## Source Docs

- `docs/YGGDRASIL_DESIGN_SYSTEM_V2/README.md`
- `docs/DESIGN_PRINCIPLES.md`
- `companion-ui/docs/DESIGN_HANDOFF_GOVERNANCE.md`

## Applies learning (optional)
