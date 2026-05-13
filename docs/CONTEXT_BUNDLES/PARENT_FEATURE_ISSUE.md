State: Local draft parent feature issue. Not yet filed on GitHub as of 2026-05-13. This file is
the local source for later filing and validation tracking.

# [Feature] Context Bundles

> **Local draft only.** Do not treat this file as a live GitHub issue until it is filed.

## Context

`docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md` defines the context bundle as the inspectable bridge
between retrieval, orientation, resurfacing, companion UI, governed write proposals, provenance,
and write guards. The contract is now authored, but the repository does not yet have an
implementation-ready breakdown that says how the bundle should be shaped, emitted, consumed, and
receipted in bounded steps.

This feature exists to create that breakdown without claiming shipped runtime behavior. It is a
docs-only capability-preparation slice.

## Scope

- define one specification directory at `docs/CONTEXT_BUNDLES/`,
- break the context-bundle contract into bounded implementation tasks,
- define verification targets for schema, retrieval emission, orientation usage, resurfacing usage,
  write-proposal linkage, and receipts,
- and define the parent-level validation and acceptance path for later implementation issues.

## Source Anchors

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Required fields`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Authority flags`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to retrieval, orientation, and resurfacing`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to writeback and write guards`
- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md :: Relation to provenance and receipts`
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`
- `docs/FINDING_AND_REORIENTING/README.md`

## Constraints

- Docs-only in this PR. No runtime, schema, or API implementation changes.
- Do not claim that context bundles are already emitted or consumed unless `docs/STATUS.md` already
  says so.
- Preserve the contract distinction that a context bundle is not memory, not chat context, and not
  a new source of truth.
- Preserve write-guard and trust-semantics boundaries.
- Keep every task independently mergeable and independently verifiable.

## Acceptance Criteria

- [ ] `docs/CONTEXT_BUNDLES/README.md` exists and defines capability boundary, non-goals, task list,
  execution order, verification path, validation path, evidence surface, relationship to GitHub
  issues, and owner-doc promotion trigger.
  Verify: `docs/CONTEXT_BUNDLES/README.md`
- [ ] `docs/CONTEXT_BUNDLES/PARENT_FEATURE_ISSUE.md` exists as a local draft with the full parent
  feature issue contract shape.
  Verify: `docs/CONTEXT_BUNDLES/PARENT_FEATURE_ISSUE.md`
- [ ] The six context-bundle implementation tasks exist with required frontmatter, required
  sections, and explicit `Verify:` targets.
  Verify: `rg -n "^task_id: CONTEXT-BUNDLES-|^## (Purpose|What This Task Does|Concretely|Why This Matters|Acceptance Criteria|How to Verify \\(Pre-Merge\\)|Out of Scope|Related Docs|Related GitHub Issues)$|Verify:" docs/CONTEXT_BUNDLES/*.md`
- [ ] The breakdown preserves the contract boundary that context bundles may support answers,
  orientation, resurfacing, and proposals without silently authorizing writeback.
  Verify: doc review of `docs/CONTEXT_BUNDLES/README.md` and `docs/CONTEXT_BUNDLES/CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md`

## Out of Scope

- Implementing any runtime schema or service for context bundles.
- Creating child GitHub implementation issues in this PR.
- Claiming current runtime support in `docs/STATUS.md` beyond docs/spec preparation.
- Defining companion UI behavior beyond the bundle's implementation contract.

## Suggested Validation

- `rg -n "^task_id: CONTEXT-BUNDLES-|^source_anchor:|^parent_capability: Context Bundles" docs/CONTEXT_BUNDLES/*.md`
- `rg -n "^## (Purpose|What This Task Does|Concretely|Why This Matters|Acceptance Criteria|How to Verify \\(Pre-Merge\\)|Out of Scope|Related Docs|Related GitHub Issues)$" docs/CONTEXT_BUNDLES/*.md`
- `rg -n "Verify:" docs/CONTEXT_BUNDLES/*.md`
- `rg -n "^## (Context|Scope|Source Anchors|Constraints|Acceptance Criteria|Out of Scope|Suggested Validation|Source Docs|Implementation Tasks|Verification Path|Validation / Acceptance Path)$" docs/CONTEXT_BUNDLES/PARENT_FEATURE_ISSUE.md`

## Source Docs

- `docs/CONCEPTS/CONTEXT_BUNDLE_CONTRACT.md`
- `docs/HUMAN_FLOW_TO_RUNTIME_MAP.md`
- `docs/COMPANION_UI_PRODUCT_SPEC.md`
- `docs/FINDING_AND_REORIENTING/README.md`
- `docs/FINDING_AND_REORIENTING/DEFINE_RETRIEVAL_CAPABILITY_CONTRACT.md`
- `docs/FINDING_AND_REORIENTING/DEFINE_ORIENTATION_CAPABILITY_CONTRACT.md`
- `docs/FINDING_AND_REORIENTING/DEFINE_RESURFACING_CAPABILITY_CONTRACT.md`
- `.codex/skills/feature-breakdown/SKILL.md`

## Implementation Tasks

1. `docs/CONTEXT_BUNDLES/DEFINE_CONTEXT_BUNDLE_SCHEMA.md`
2. `docs/CONTEXT_BUNDLES/EMIT_CONTEXT_BUNDLE_FROM_RETRIEVAL.md`
3. `docs/CONTEXT_BUNDLES/USE_CONTEXT_BUNDLE_FOR_ORIENTATION.md`
4. `docs/CONTEXT_BUNDLES/USE_CONTEXT_BUNDLE_FOR_RESURFACING.md`
5. `docs/CONTEXT_BUNDLES/CONNECT_CONTEXT_BUNDLE_TO_WRITE_PROPOSALS.md`
6. `docs/CONTEXT_BUNDLES/RECORD_CONTEXT_BUNDLE_RECEIPTS.md`

## Verification Path

- Each future task PR resolves the named `Verify:` targets in the task spec it implements.
- Schema and emission tasks verify structure before downstream usage tasks are treated as complete.
- Parent-level verification checks that every implementation surface preserves provenance,
  exclusions, and authority flags.

## Validation / Acceptance Path

- File the parent issue when the repository is ready to convert this directory into execution work.
- Create child implementation issues from the task files in dependency order.
- Keep validation evidence on the future parent issue until runtime support is accepted.
- Promote owner-doc truth only after receipts show bundles are emitted, consumed, and bounded by
  write authority in the shipped runtime.
