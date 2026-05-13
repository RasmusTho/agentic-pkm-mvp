State: Draft specification. Not implemented. Docs-only feature-breakdown surface; no runtime behavior changes are claimed here.

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

1. [DEFINE_CONTEXT_BUNDLE_SCHEMA.md](DEFINE_CONTEXT_BUNDLE_SCHEMA.md)
2. [EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md](EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md)
3. [USE_CONTEXT_BUNDLE_FOR_ORIENTATION.md](USE_CONTEXT_BUNDLE_FOR_ORIENTATION.md)
4. [USE_CONTEXT_BUNDLE_FOR_RESURFACING.md](USE_CONTEXT_BUNDLE_FOR_RESURFACING.md)
5. [CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md](CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md)
6. [RECORD_CONTEXT_BUNDLE_RECEIPTS.md](RECORD_CONTEXT_BUNDLE_RECEIPTS.md)

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

- This directory is accepted at the docs/spec layer when the README, parent feature draft, and all
  six task specs are merged and internally consistent.
- Runtime acceptance remains future work and should be recorded on a parent feature issue plus child
  implementation issues after those are filed.
- Owner-doc promotion is gated on implementation evidence that the runtime actually emits, consumes,
  and receipts context bundles truthfully.

## Evidence Surface

- Local task specs in this directory define the implementation contract.
- Future child PRs provide slice verification receipts.
- The parent feature issue, once filed, should hold validation evidence and acceptance tracking.
- Owner docs such as `docs/STATUS.md` and `docs/ARCHITECTURE.md` should change only when runtime
  support is actually delivered.

## Relationship to GitHub Issues

No GitHub issues are created in this PR.

The local source for a future parent feature issue is
[PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md). Child implementation issues should be created
later from these task specs using the repo's `feature-breakdown` and `docs-to-issue` workflows when
the contracts are ready to enter execution.

## Owner-Doc Promotion Trigger

Promote current-state owner docs only after implementation receipts show all of the following:

- retrieval emits an inspectable context bundle,
- orientation and resurfacing consume it without silently turning it into authority,
- write proposals carry bundle linkage without bypassing write guards,
- and receipts expose bundle provenance and exclusions truthfully.
