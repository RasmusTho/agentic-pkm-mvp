---
name: Promote Owner Docs
description: Promote owner docs after production runtime evidence and close the parent feature.
task_id: CONTEXT-BUNDLES-RUNTIME-06
source_anchor: docs/CONTEXT_BUNDLES/README.md :: Owner-Doc Promotion Trigger
parent_capability: Context Bundles — Production Runtime Integration
prerequisites: [CONTEXT-BUNDLES-RUNTIME-01, CONTEXT-BUNDLES-RUNTIME-02, CONTEXT-BUNDLES-RUNTIME-03, CONTEXT-BUNDLES-RUNTIME-04, CONTEXT-BUNDLES-RUNTIME-05]
depends_on: [EXPOSE_BUNDLE_CONSTRUCTION_ROUTE.md, EMIT_FROM_REAL_RETRIEVAL.md, CONSUME_IN_ORIENTATION_AND_RESURFACING.md, CARRY_LINKAGE_THROUGH_WRITE_PROPOSALS.md, EXPOSE_RECEIPT_PROJECTION.md]
can_parallelize_with: []
github_issue: "https://github.com/RasmusTho/agentic-pkm-mvp/issues/1566"
---

# PROMOTE_OWNER_DOCS

## Purpose

Promote current-state owner docs to reflect shipped Context Bundle runtime integration, only after
runtime evidence exists, and close the parent feature.

## What This Task Does

Updates `docs/STATUS.md`, `docs/ARCHITECTURE.md`, and the Owner-Doc Promotion Trigger in
`docs/CONTEXT_BUNDLES/README.md` (and `docs/CONTEXT_BUNDLES_RUNTIME/README.md`) to describe shipped
runtime integration; rewrites roadmap/plan wording so it no longer reads as pending; posts the
parent-closure handoff on #1559. Owner-doc changes are bundled in this PR, not a separate follow-up.

## Concretely

After children #1560 and #1562-#1565 merge with receipts, this slice flips `docs/STATUS.md` from
"typed-contract only" to "production runtime integrated", links the delivering child PRs, marks the
Owner-Doc Promotion Trigger satisfied, and closes #1559 with a final validation receipt.

## Why This Matters

The repo keeps current-state docs honest: claiming runtime support before evidence would violate the
change-classification rules in `AGENTS.md`. This slice is the single sanctioned promotion point.

## Acceptance Criteria

- [ ] `docs/STATUS.md` reflects shipped runtime integration with linked child PRs (#1560, #1562-#1565).
  Verify: writeback to the `docs/STATUS.md` Context Bundles update block.
- [ ] Owner-Doc Promotion Trigger marked satisfied.
  Verify: writeback to `docs/CONTEXT_BUNDLES/README.md :: Owner-Doc Promotion Trigger`.
- [ ] Parent feature issue #1559 closed with a final validation receipt linking all child PRs.
  Verify: parent issue closure comment on #1559.

## How to Verify (Pre-Merge)

- Confirm children #1560 and #1562-#1565 are merged with receipts before promoting.
- Use the docs-lane PR contract: `## BuilderOps Routing` list-items and `- [x] Docs authoring lane`.
- Run `scripts/docs_guard.py` if applicable.

## Out of Scope

- Any new runtime behavior.
- Knowledge Compilation docs.

## Related Docs

- `docs/CONTEXT_BUNDLES/README.md`
- `docs/STATUS.md`
- `docs/ROADMAP.md`
- `docs/ARCHITECTURE.md`

## Related GitHub Issues

- Implementation issue: [#1566](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1566)
- Depends on: [#1560](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1560),
  [#1562](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1562)-[#1565](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1565)
- Parent feature: [#1559](https://github.com/RasmusTho/agentic-pkm-mvp/issues/1559)
