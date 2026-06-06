State: Delivered. Parent feature issue #1559 closed 2026-06-04 after children #1560 (PR #1569),
#1562 (PR #1570), #1563 (PR #1571), #1564 (PR #1572), #1565 (PR #1574), and #1566 (owner-doc
promotion + closure) merged with validation receipts. Context Bundles are now wired into production
runtime — construction route, real retrieval emission, process-local emitted-bundle addressability
for orientation/resurfacing consumption, governed write-proposal linkage, and a read-only receipt
projection — as inspectable bridge objects that carry no write authority (`may_write` stays false)
and bypass no write guard, trust, or policy gate.

# Context Bundles — Production Runtime Integration

## Capability Boundary

The Context Bundles capability has two delivered layers:

- the typed-contract / Pydantic layer (closed parent #894 and children #895/#896/#946/#947/#948/#949),
  which established the pure contract building blocks;
- the production runtime integration wave (closed parent #1559 and children #1560, #1562-#1566),
  which wired those contracts into route, retrieval, consumption, proposal-linkage, receipt, and
  owner-doc surfaces.

The shipped runtime integration includes:

- a read-only production route that returns an inspectable `ContextBundle`,
- bundle emission from the real retrieval path,
- process-local emitted-bundle addressability for bundle consumption in the production orientation
  and resurfacing paths,
- bundle linkage through governed write proposals,
- a read-only receipt/query projection for bundle provenance and exclusions,
- and owner-doc promotion after runtime evidence landed.

### Emitted Bundle Addressability

The production orientation and resurfacing bundle routes consume bundles that were emitted earlier in
the same runtime process. `GET /api/context-bundles/{bundle_id}?query=...` records the emitted
bundle in a bounded in-memory registry; `/api/orientation/bundle/{bundle_id}` and
`/api/resurfacing/bundle/{bundle_id}` resolve through that registry. The registry keeps a small
least-recently-used window of emitted bundles for short-lived addressability and may evict older
entries before process restart. Callers that need a bundle for a specific read-side consumer pass
explicit non-write `intended_use` values such as
`intended_use=orient` or `intended_use=resurface`; the route maps those values to matching
non-write authority flags and keeps `may_write=false`.

This registry is an addressability cache only:

- process-local and cleared on process restart;
- bounded; older emitted bundles may miss after eviction;
- non-durable and not a DB/store import path;
- not agent memory, durable knowledge, or a receipt authority;
- not a write-authority surface (`may_write` remains false unless a later governed contract changes
  that posture);
- honest on misses: consumers return a missing-bundle response instead of reconstructing the
  synthetic construction envelope.

The construction envelope remains useful for inspecting the typed route shape, but production
orientation/resurfacing consumption must not silently substitute it for a real emitted bundle.

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

1. [EXPOSE_BUNDLE_CONSTRUCTION_ROUTE.md](EXPOSE_BUNDLE_CONSTRUCTION_ROUTE.md) — issue
   [#1560](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1560) (delivered by PR #1569).
2. [EMIT_FROM_REAL_RETRIEVAL.md](EMIT_FROM_REAL_RETRIEVAL.md) — issue
   [#1562](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1562) (delivered by PR #1570).
3. [CONSUME_IN_ORIENTATION_AND_RESURFACING.md](CONSUME_IN_ORIENTATION_AND_RESURFACING.md) — issue
   [#1563](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1563) (delivered by PR #1571).
4. [CARRY_LINKAGE_THROUGH_WRITE_PROPOSALS.md](CARRY_LINKAGE_THROUGH_WRITE_PROPOSALS.md) — issue
   [#1564](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1564) (delivered by PR #1572).
5. [EXPOSE_RECEIPT_PROJECTION.md](EXPOSE_RECEIPT_PROJECTION.md) — issue
   [#1565](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1565) (delivered by PR #1574).
6. [PROMOTE_OWNER_DOCS.md](PROMOTE_OWNER_DOCS.md) — issue
   [#1566](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1566) (delivered by PR #1577).
7. Emitted bundle source repair — issue
   [#1592](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1592) (post-closure review-thread
   repair for PR #1571).

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
- [x] Orientation and resurfacing production paths resolve emitted bundles by id without silently
  reconstructing the synthetic construction envelope.
  Verify: #1592 PR validation.
- [x] Governed write proposals carry bundle linkage without bypassing WriteGuard.
  Verify: #1564 PR validation.
- [x] A receipt/query projection exposes bundle provenance and exclusions.
  Verify: #1565 PR validation.
- [x] Owner docs are promoted only after runtime evidence exists.
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
- Post-closure review-thread repairs such as #1592 remain separate backlog receipts when merged code
  reveals a narrower runtime-source bug after the parent feature has closed.

## Relationship to GitHub Issues

- Parent feature issue: [#1559](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1559).
- `EXPOSE_BUNDLE_CONSTRUCTION_ROUTE`: [#1560](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1560).
- `EMIT_FROM_REAL_RETRIEVAL`: [#1562](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1562).
- `CONSUME_IN_ORIENTATION_AND_RESURFACING`: [#1563](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1563).
- `CARRY_LINKAGE_THROUGH_WRITE_PROPOSALS`: [#1564](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1564).
- `EXPOSE_RECEIPT_PROJECTION`: [#1565](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1565).
- `PROMOTE_OWNER_DOCS`: [#1566](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1566).
- Emitted bundle source repair: [#1592](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1592).

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

**Executed (2026-06-04) by `PROMOTE_OWNER_DOCS.md` (#1566).** All conditions are satisfied with
merged runtime evidence (#1560, #1562-#1565). `docs/STATUS.md`, `docs/ARCHITECTURE.md`,
`docs/ROADMAP.md`, and the `docs/CONTEXT_BUNDLES/README.md` trigger were promoted in #1566, and
parent feature #1559 was closed with a final validation receipt linking all child PRs.
