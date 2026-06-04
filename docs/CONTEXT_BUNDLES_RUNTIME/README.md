State: Active feature-breakdown lane. Parent feature issue #1559 remains open as the validation hub.
Child issues #1560, #1562, #1563, and #1564 are merged; #1565 is in progress via PR #1574; #1566
remains blocked until #1565 lands and runtime evidence is complete. This directory records the
bounded integration lane and its current partial-delivery state; full owner-doc promotion waits for
#1566.

# Context Bundles — Production Runtime Integration

## Capability Boundary

The Context Bundles capability was first delivered at the typed-contract / Pydantic layer (closed
parent #894 and children #895/#896/#946/#947/#948/#949). This runtime directory is the follow-up lane
for wiring that contract into production surfaces. As of 2026-06-04, the construction route,
real-retrieval emission, production orientation/resurfacing consumption, and governed write-proposal
linkage slices are merged. Receipt/query projection and owner-doc promotion are still open.

This directory specifies the bounded work to integrate the existing contract into production runtime:

- a read-only production route that returns an inspectable `ContextBundle`,
- bundle emission from the real retrieval path,
- bundle consumption in the production orientation and resurfacing paths,
- bundle linkage through governed write proposals,
- a receipt/query projection for bundle provenance and exclusions,
- and owner-doc promotion only after runtime evidence exists.

It is downstream of `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` and downstream of the typed-contract
spec directory `docs/CONTEXT_BUNDLES/`. It does not redefine the contract.

## Relationship to the Contract and the Typed-Contract Spec

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` defines what a context bundle means (semantic source of
  truth).
- `docs/CONTEXT_BUNDLES/` specified and delivered the typed-contract / Pydantic layer.
- This directory (`docs/CONTEXT_BUNDLES_RUNTIME/`) specifies the production runtime integration of
  that delivered contract.

## Non-Goals

- Knowledge Compilation bundle wiring (kept deliberately separate).
- Implementing agent memory or promoting retrieved context into memory/knowledge.
- Cross-vault / multi-vault / vault-topology assumptions.
- Companion-UI rendering beyond the response contract.
- Bypassing WriteGuard, trust semantics, policy gates, or receipt posture.
- Claiming runtime support in owner docs before evidence exists.

## Task List

1. [EXPOSE_BUNDLE_CONSTRUCTION_ROUTE.md](EXPOSE_BUNDLE_CONSTRUCTION_ROUTE.md) — delivered, closed
   [#1560](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1560) via PR #1569.
2. [EMIT_FROM_REAL_RETRIEVAL.md](EMIT_FROM_REAL_RETRIEVAL.md) — delivered, closed
   [#1562](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1562) via PR #1570.
3. [CONSUME_IN_ORIENTATION_AND_RESURFACING.md](CONSUME_IN_ORIENTATION_AND_RESURFACING.md) —
   delivered, closed [#1563](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1563) via PR #1571.
4. [CARRY_LINKAGE_THROUGH_WRITE_PROPOSALS.md](CARRY_LINKAGE_THROUGH_WRITE_PROPOSALS.md) —
   delivered, closed [#1564](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1564) via PR #1572.
5. [EXPOSE_RECEIPT_PROJECTION.md](EXPOSE_RECEIPT_PROJECTION.md) — open
   [#1565](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1565), in progress via PR #1574.
6. [PROMOTE_OWNER_DOCS.md](PROMOTE_OWNER_DOCS.md) — blocked
   [#1566](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1566) until #1565 lands.

## Flat Execution Order

1. `EXPOSE_BUNDLE_CONSTRUCTION_ROUTE.md` (#1560)
2. `EMIT_FROM_REAL_RETRIEVAL.md` (#1562)
3. `CONSUME_IN_ORIENTATION_AND_RESURFACING.md` (#1563) and
   `CARRY_LINKAGE_THROUGH_WRITE_PROPOSALS.md` (#1564) — parallelizable after step 2
4. `EXPOSE_RECEIPT_PROJECTION.md` (#1565)
5. `PROMOTE_OWNER_DOCS.md` (#1566)

## Capability-Level Acceptance Criteria

- [x] A production route returns an inspectable `ContextBundle` envelope, read-only.
  Verify: `docs/CONTEXT_BUNDLES_RUNTIME/EXPOSE_BUNDLE_CONSTRUCTION_ROUTE.md` + #1560 PR validation.
- [x] Real retrieval emits bundles against the live vault.
  Verify: `docs/CONTEXT_BUNDLES_RUNTIME/EMIT_FROM_REAL_RETRIEVAL.md` + #1562 PR validation.
- [x] Orientation and resurfacing production paths consume bundles without authority upgrade.
  Verify: #1563 PR validation.
- [x] Governed write proposals carry bundle linkage without bypassing WriteGuard.
  Verify: #1564 PR validation.
- [ ] A receipt/query projection exposes bundle provenance and exclusions.
  Verify: #1565 PR validation.
- [ ] Owner docs are promoted only after runtime evidence exists.
  Verify: #1566 promotes `docs/STATUS.md` and closes parent #1559.

## Verification Path

- Task-level verification follows each task file's `How to Verify (Pre-Merge)` section.
- Each child PR resolves the named `Verify:` test targets on its head SHA.
- Parent-level verification checks that every production surface preserves provenance, exclusions,
  and authority flags and never upgrades `may_write`.

## Validation / Acceptance Path

- GitHub Issue #1559 is the validation hub. Each delivered child posts a validation receipt before
  the next blocked child is picked up.
- Owner-doc promotion (`docs/STATUS.md`, `docs/ARCHITECTURE.md`,
  `docs/CONTEXT_BUNDLES/README.md` Owner-Doc Promotion Trigger) happens only in the final child
  (#1566) after runtime evidence from #1560 and #1562-#1565.

## Evidence Surface

- Task specs in this directory define the implementation contract.
- Child PRs are the task verification receipts.
- Parent feature issue #1559 holds the live validation log and acceptance checklist.

## Relationship to GitHub Issues

- Parent feature issue: [#1559](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1559).
- `EXPOSE_BUNDLE_CONSTRUCTION_ROUTE`: [#1560](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1560).
- `EMIT_FROM_REAL_RETRIEVAL`: [#1562](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1562).
- `CONSUME_IN_ORIENTATION_AND_RESURFACING`: [#1563](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1563).
- `CARRY_LINKAGE_THROUGH_WRITE_PROPOSALS`: [#1564](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1564).
- `EXPOSE_RECEIPT_PROJECTION`: [#1565](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1565).
- `PROMOTE_OWNER_DOCS`: [#1566](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1566).

The local source/reference copy for the parent feature issue is
[PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md). GitHub Issue #1559 is the authoritative
backlog/validation surface.

## Owner-Doc Promotion Trigger

Promote current-state owner docs only after implementation receipts show all of the following in the
shipped runtime:

- a production route returns an inspectable bundle,
- retrieval emits bundles against the real vault,
- orientation and resurfacing consume bundles without silently turning them into authority,
- write proposals carry bundle linkage without bypassing WriteGuard,
- and receipts expose bundle provenance and exclusions truthfully.

This trigger is executed by `PROMOTE_OWNER_DOCS.md` (#1566), not before.
