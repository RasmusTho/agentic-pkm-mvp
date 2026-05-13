State: Filed specification. Parent feature issue #894 and the first two child implementation issues
#895/#896 are filed on GitHub. Runtime implementation has not shipped; no runtime behavior changes
are claimed here.

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

1. [DEFINE_CONTEXT_BUNDLE_SCHEMA.md](DEFINE_CONTEXT_BUNDLE_SCHEMA.md) — filed as
   [#895](https://github.com/RasmusTho/agentic-pkm-mvp/issues/895).
2. [EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md](EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md) — filed as
   [#896](https://github.com/RasmusTho/agentic-pkm-mvp/issues/896); depends on #895.
3. [USE_CONTEXT_BUNDLE_FOR_ORIENTATION.md](USE_CONTEXT_BUNDLE_FOR_ORIENTATION.md) — not yet filed.
4. [USE_CONTEXT_BUNDLE_FOR_RESURFACING.md](USE_CONTEXT_BUNDLE_FOR_RESURFACING.md) — not yet filed.
5. [CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md](CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md) —
   not yet filed.
6. [RECORD_CONTEXT_BUNDLE_RECEIPTS.md](RECORD_CONTEXT_BUNDLE_RECEIPTS.md) — not yet filed.

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
- Runtime acceptance remains future work and should be recorded on parent feature issue
  [#894](https://github.com/RasmusTho/agentic-pkm-mvp/issues/894) plus child implementation issues.
- Owner-doc promotion is gated on implementation evidence that the runtime actually emits, consumes,
  and receipts context bundles truthfully.

## Evidence Surface

- Local task specs in this directory define the implementation contract.
- Future child PRs provide slice verification receipts.
- Parent feature issue [#894](https://github.com/RasmusTho/agentic-pkm-mvp/issues/894) is the
  authoritative backlog and validation surface for this capability.
- Owner docs such as `docs/STATUS.md` and `docs/ARCHITECTURE.md` should change only when runtime
  support is actually delivered.

## Relationship to GitHub Issues

GitHub issue state:

- Parent feature issue: [#894](https://github.com/RasmusTho/agentic-pkm-mvp/issues/894).
- `CONTEXT-BUNDLES-01`: [#895](https://github.com/RasmusTho/agentic-pkm-mvp/issues/895).
- `CONTEXT-BUNDLES-02`: [#896](https://github.com/RasmusTho/agentic-pkm-mvp/issues/896).
- `CONTEXT-BUNDLES-03` through `CONTEXT-BUNDLES-06`: not yet filed.

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

No owner-doc promotion is warranted until capability validation is complete on #894.
