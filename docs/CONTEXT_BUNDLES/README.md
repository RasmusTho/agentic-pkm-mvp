State: All six implementation slices delivered. Parent feature issue #894 closed 2026-05-15 after
child issues #895 (schema, PR #931), #896 (retrieval emission, PR #932), #946 (orientation, PR #950),
#947 (resurfacing, PR #951), #948 (write proposals, PR #952), and #949 (receipts, PR #954) were
all merged and validated. No runtime behavior changes are claimed here beyond the implemented
schema, orientation consumer, resurfacing consumer, write-proposal linkage, and receipt-recording
contracts at the typed-contract / pydantic layer.

# Context Bundles

## Capability Boundary

This specification directory defines the implementation-ready breakdown for the `context bundle`
capability introduced in `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`.

The capability boundary is:

- schema and contract shape for an inspectable context bundle,
- bundle emission from retrieval,
- bundle consumption by orientation,
- bundle consumption by resurfacing,
- bundle linkage to governed write proposals,
- and receipt/provenance recording for bundle use.

This directory is downstream of the concept contract and upstream of any runtime implementation. It
describes what implementation must do; it does not claim that the runtime already does it.

## Relationship to the Contract

`docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` defines what a context bundle means. This directory
breaks that contract into bounded implementation tasks that can later become GitHub issues and
independently reviewable PRs.

The contract remains the semantic source of truth. These task specs are the implementation planning
surface for that contract.

## Non-Goals

- shipping a retrieval, orientation, resurfacing, or writeback runtime in this PR,
- defining a specific storage backend beyond what each task needs to verify,
- turning context bundles into a new source of truth,
- silently promoting retrieved context into memory or knowledge,
- bypassing write guards or trust semantics,
- or rewriting the owner contract in `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`.

## Task List

1. [DEFINE_CONTEXT_BUNDLE_SCHEMA.md](DEFINE_CONTEXT_BUNDLE_SCHEMA.md) — delivered, closed
   [#895](https://github.com/RasmusTho/agentic-pkm-mvp/issues/895) via PR #931.
2. [EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md](EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md) — delivered, closed
   [#896](https://github.com/RasmusTho/agentic-pkm-mvp/issues/896) via PR #932.
3. [USE_CONTEXT_BUNDLE_FOR_ORIENTATION.md](USE_CONTEXT_BUNDLE_FOR_ORIENTATION.md) — delivered, closed
   [#946](https://github.com/RasmusTho/agentic-pkm-mvp/issues/946) via PR #950.
4. [USE_CONTEXT_BUNDLE_FOR_RESURFACING.md](USE_CONTEXT_BUNDLE_FOR_RESURFACING.md) — delivered, closed
   [#947](https://github.com/RasmusTho/agentic-pkm-mvp/issues/947) via PR #951.
5. [CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md](CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md) —
   delivered, closed [#948](https://github.com/RasmusTho/agentic-pkm-mvp/issues/948) via PR #952.
6. [RECORD_CONTEXT_BUNDLE_RECEIPTS.md](RECORD_CONTEXT_BUNDLE_RECEIPTS.md) — delivered, closed
   [#949](https://github.com/RasmusTho/agentic-pkm-mvp/issues/949) via PR #954.

## Flat Execution Order

1. `DEFINE_CONTEXT_BUNDLE_SCHEMA.md`
2. `EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md`
3. `USE_CONTEXT_BUNDLE_FOR_ORIENTATION.md`
4. `USE_CONTEXT_BUNDLE_FOR_RESURFACING.md`
5. `CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md`
6. `RECORD_CONTEXT_BUNDLE_RECEIPTS.md`

## Capability-Level Acceptance Criteria

- [ ] The repository contains a bounded context-bundle schema task that preserves the contract's
  required fields and authority flags.
  Verify: `docs/CONTEXT_BUNDLES/DEFINE_CONTEXT_BUNDLE_SCHEMA.md`
- [ ] Retrieval emission, orientation usage, resurfacing usage, write-proposal linkage, and
  receipt-recording are each specified as independently mergeable tasks.
  Verify: `docs/CONTEXT_BUNDLES/*.md`
- [ ] Every task in this directory includes explicit behavioral or doc-surface `Verify:` targets.
  Verify: `rg -n "Verify:" docs/CONTEXT_BUNDLES/*.md`
- [ ] The parent feature draft defines the validation and acceptance path without claiming shipped
  runtime behavior.
  Verify: `docs/CONTEXT_BUNDLES/PARENT_FEATURE_ISSUE.md`

## Verification Path

- Task-level verification follows each task file's `How to Verify (Pre-Merge)` section.
- Contract-shape verification for this directory checks frontmatter, required sections, and inline
  `Verify:` targets.
- PR-level verification for future implementation work must resolve the named test targets on the
  head SHA of each task PR.

## Validation / Acceptance Path

- This directory is accepted at the docs/spec layer when the README, parent feature reference, and
  all six task specs are merged and internally consistent.
- All six child slices are delivered. Parent feature issue #894 is closed.
- Owner-doc promotion beyond the typed-contract layer (e.g. STATUS.md, ARCHITECTURE.md) is gated
  on runtime integration evidence in the active follow-up lane `docs/CONTEXT_BUNDLES_RUNTIME/`
  under parent #1559. Route/emission/consumption/linkage slices have merged; receipt projection and
  final owner-doc promotion remain open.

## Evidence Surface

- Task specs in this directory define the implementation contract.
- Slice verification receipts are on the closed child issues (#946–#949) and the closed parent (#894).
- Parent feature issue [#894](https://github.com/RasmusTho/agentic-pkm-mvp/issues/894) is closed
  with a full validation receipt.
- Owner docs such as `docs/STATUS.md` and `docs/ARCHITECTURE.md` should claim full runtime support
  only after #1559 closes with receipt/query projection and owner-doc promotion evidence.

## Relationship to GitHub Issues

GitHub issue state:

- Parent feature issue: [#894](https://github.com/RasmusTho/agentic-pkm-mvp/issues/894).
- `CONTEXT-BUNDLES-01`: [#895](https://github.com/RasmusTho/agentic-pkm-mvp/issues/895).
- `CONTEXT-BUNDLES-02`: [#896](https://github.com/RasmusTho/agentic-pkm-mvp/issues/896).
- `CONTEXT-BUNDLES-03`: [#946](https://github.com/RasmusTho/agentic-pkm-mvp/issues/946) — closed.
- `CONTEXT-BUNDLES-04`: [#947](https://github.com/RasmusTho/agentic-pkm-mvp/issues/947) — closed.
- `CONTEXT-BUNDLES-05`: [#948](https://github.com/RasmusTho/agentic-pkm-mvp/issues/948) — closed.
- `CONTEXT-BUNDLES-06`: [#949](https://github.com/RasmusTho/agentic-pkm-mvp/issues/949) — closed.

The local source/reference copy for the parent feature issue is
[PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md). GitHub Issue #894 is the authoritative
backlog/validation surface. Child implementation issues should continue to be created from these
task specs using the repo's `feature-breakdown` and `docs-to-issue` workflows.

## Owner-Doc Promotion Trigger

Promote current-state owner docs only after implementation receipts show all of the following:

- retrieval emits an inspectable context bundle,
- orientation and resurfacing consume it without silently turning it into authority,
- write proposals carry bundle linkage without bypassing write guards,
- and receipts expose bundle provenance and exclusions truthfully.

Capability validation is complete on #894 (closed 2026-05-15). Further owner-doc promotion
(`STATUS.md`, `ARCHITECTURE.md`) is now governed by #1559 and must wait for the receipt/query
projection (#1565) plus final owner-doc promotion (#1566).
