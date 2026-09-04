---
name: Consolidate Discovery and Read Operations
description: Route list, read, search, related-content, and capability discovery through owner-native read adapters
task_id: AUTOOPS-03
github_issue: 5332
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Operation families and parity scope"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: [AUTOOPS-01, AUTOOPS-02]
depends_on: [ESTABLISH_OPERATION_CONTRACTS.md, ENFORCE_OPERATION_EXECUTION_KERNEL.md]
can_parallelize_with: []
---

# Consolidate Discovery and Read Operations

## Purpose

Make existing read capabilities available through one operation boundary without changing retrieval authority.

## What This Task Does

Register list, read, search, related-content, and capability-discovery handlers that delegate to
existing APIs/services, normalize typed outcomes, and preserve provenance and explicit vault context.

## Concretely

```text
artifact.search(query="MCP parity", vault_id="...")
  -> canonical search service -> items with stable IDs, locators, provenance, and freshness
```

## Why This Matters

Human and agent flows need the same grounded discovery surface before safe mutation can be scoped.

## Acceptance Criteria

- [ ] List, read, search, and related handlers delegate to named production read owners.
  Verify: `tests/operations/test_read_operations.py::test_read_operations_delegate_to_canonical_production_services`
- [ ] Results preserve stable ID, current locator, provenance, vault context, and freshness/lag signals.
  Verify: `tests/operations/test_read_operations.py::test_read_results_preserve_identity_context_provenance_and_freshness`
- [ ] Missing context, unavailable indexes, and inaccessible artifacts return distinct typed outcomes.
  Verify: `tests/operations/test_read_operations.py::test_read_failures_are_typed_and_never_ambiguous_empty_success`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations/test_read_operations.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api/test_search_canonical_substrate.py tests/api/test_artifact_note_read_api.py`
- `ruff check app tests`

## Out of Scope

- Search ranking redesign, new index authority, writes, GUI rendering, or MCP schemas.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md`
- `docs/CONCEPTS/RETRIEVAL_CONTRACT.md`

## Related GitHub Issues

Block on AUTOOPS-01/02. TCD hint: `fresh_issue_agent`, helper budget 0, balanced implementation
capability at medium reasoning; bounded integration over existing read paths.
