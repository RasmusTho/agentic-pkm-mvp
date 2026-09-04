---
name: Deliver Classification, Tagging, and Ordering
description: Add governed semantic metadata and explicit ordering operations through their owner-native stores
task_id: AUTOOPS-06
github_issue: 5335
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Operation families and parity scope"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: [AUTOOPS-02, AUTOOPS-04]
depends_on: [ENFORCE_OPERATION_EXECUTION_KERNEL.md, CONSOLIDATE_CREATE_AND_EDIT_OPERATIONS.md]
can_parallelize_with: [Deliver Identity-Preserving Move and Rename]
---

# Deliver Classification, Tagging, and Ordering

## Purpose

Make classification, tags, and user-authored ordering explicit operations instead of adapter-local patches.

## What This Task Does

Register handlers for classification changes, tag add/remove, and persistent order changes using
existing vocabulary, metadata, and ordering owners. Preserve canonical normalization and versions.

## Concretely

```text
artifact.tags.add(id="a-17", tags=["research"], expected_version=3)
collection.reorder(container_id="c-2", ordered_ids=[...], expected_version=9)
```

## Why This Matters

Silent adapter-specific metadata rules produce different organization depending on whether a human or agent acts.

## Acceptance Criteria

- [ ] Classification and tag operations use canonical vocabulary normalization and versioned owner writes.
  Verify: `tests/operations/test_semantic_operations.py::test_classification_and_tags_use_canonical_versioned_owner_paths`
- [ ] Reorder validates membership, duplicates, omissions, and version before persisting explicit order.
  Verify: `tests/operations/test_semantic_operations.py::test_reorder_validates_complete_versioned_membership`
- [ ] Projection failure returns committed-with-lag recovery evidence rather than false rollback or success.
  Verify: `tests/operations/test_semantic_operations.py::test_semantic_projection_failure_is_truthful_and_recoverable`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations/test_semantic_operations.py`
- `ruff check app tests`

## Out of Scope

- New ontology terms, automatic LLM classification policy, ranking, or visual drag-and-drop.

## Restart / Durability Posture

Owner metadata/order and operation receipts survive restart; rebuildable projections may lag but expose repair state.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/contracts/ARTIFACT_CONTRACT.md`

## Related GitHub Issues

Block on AUTOOPS-02/04. TCD hint: `fresh_issue_agent`, helper budget 0, reliable implementation
capability at medium-high reasoning for semantic integrity and versioned writes.
