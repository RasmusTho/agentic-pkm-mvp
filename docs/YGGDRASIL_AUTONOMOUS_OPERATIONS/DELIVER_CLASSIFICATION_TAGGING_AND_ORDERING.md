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

Delivered as dormant direct composition: `app/operations/semantic_operations.py` dispatches to
`app/knowledge/semantic.py` through the existing operation kernel. The
[ArtifactContract](../contracts/ARTIFACT_CONTRACT.md#dormant-semantic-commands-autoops-06) owns the
exact admitted classification fields/values, tag normalization, and authored `member_order` UUID
list. Reorder only permutes an existing complete source list in one expected-version HKA CAS.
Explicit semantic approval and the current full selected-context GOV window remain mandatory.
The direct producer also holds the captured WSP selection record and exact approval owner's
effect fences through source/authority receipt persistence, with an owned nonblocking final guard
after all potentially blocking work. The WSP record guard is opt-in for this semantic consumer;
ordinary frozen in-flight snapshots keep their existing behavior. Decoded identity declarations
remain visible when later YAML is malformed, while unrelated malformed notes remain isolated;
generic body-edit grants and machine suggestions cannot authorize these changes. The handlers
do not initialize lists or runtime authority, install a transport, or change Canvas body policy.
Authenticated installation remains #5352 and capability acceptance remains #5329.

## Concretely

```text
artifact.tags.add(id=<note-uuid>, tags=["research"], expected_version=<raw-byte-sha256>)
collection.reorder(container_id=<note-uuid>, ordered_ids=[...], expected_version=<raw-byte-sha256>)
```

## Why This Matters

Silent adapter-specific metadata rules produce different organization depending on whether a human or agent acts.

## Acceptance Criteria

- [x] Classification and tag operations use canonical vocabulary normalization and versioned owner writes.
  Verify: `tests/operations/test_semantic_operations.py::test_classification_and_tags_use_canonical_versioned_owner_paths`
- [x] Reorder validates membership, duplicates, omissions, and version before persisting explicit order.
  Verify: `tests/operations/test_semantic_operations.py::test_reorder_validates_complete_versioned_membership`
- [x] Projection failure returns committed-with-lag recovery evidence rather than false rollback or success.
  Verify: `tests/operations/test_semantic_operations.py::test_semantic_projection_failure_is_truthful_and_recoverable`
- [x] Real handler/GOV/HKA source effects preserve identity, body, complete membership, and durable receipts across restart/replay.
  Verify: `tests/operations/test_semantic_operations.py::test_reorder_uses_hka_source_cas_and_durable_receipts`
- [x] Applicable semantic approval is required while Canvas body policy and dormant installation are preserved.
  Verify: `tests/operations/test_semantic_operations.py::test_semantic_handlers_preserve_canvas_policy_and_dormant_activation_seal`
- [x] Existing ArtifactContract and this task document the exact representation, authority, typed failures, and recovery boundary without claiming production activation.
  Verify: `docs/contracts/ARTIFACT_CONTRACT.md :: Commands`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations/test_semantic_operations.py`
- `ruff check app tests`

## Out of Scope

- New ontology terms, automatic LLM classification policy, ranking, or visual drag-and-drop.

## Restart / Durability Posture

Owner metadata/order and operation receipts survive restart; rebuildable projections may lag but expose repair state.
Known source effects retain their original receipt when authority/outbox persistence fails;
receiptless effects remain unknown. The kernel's retained reservation/outcome prevents a second
source effect after interruption. Projection repair consumes committed source/receipt evidence.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/CONCEPTS/ONTOLOGY_VOCABULARY.md`
- `docs/contracts/ARTIFACT_CONTRACT.md`

## Related GitHub Issues

AUTOOPS-02/04 prerequisites are delivered. #5335 delivers this bounded dormant implementation;
#5352 retains authenticated installation and #5329 retains capability acceptance.
