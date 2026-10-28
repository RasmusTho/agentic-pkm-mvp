---
name: Consolidate Create and Edit Operations
description: Route capture, typed creation, and versioned editing through existing governed write owners
task_id: AUTOOPS-04
github_issue: 5333
source_anchor: "docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md :: Receipts and provenance"
parent_capability: Yggdrasil Autonomous Operations
prerequisites: [AUTOOPS-02]
depends_on: [ENFORCE_OPERATION_EXECUTION_KERNEL.md]
can_parallelize_with: []
---

# Consolidate Create and Edit Operations

## Purpose

Expose creation and editing without adding a generic file writer or bypassing governed-write semantics.

## What This Task Does

Register capture, typed artifact creation, metadata/content edit, and proposal-apply handlers over
existing owner-native write services. Bind expected versions, trace, policy decision, effect receipt,
and Store/index/link convergence to the operation outcome.

## Concretely

```text
artifact.update(id="...", expected_version=4, patch=...)
  -> governed owner writer -> committed source receipt -> projection convergence status
```

## Implementation posture

The AUTOOPS-04 implementation is a dormant, direct-composition seam in
`app/operations/write_operations.py`. `build_write_operation_handlers` returns handlers for
`artifact.capture`, `artifact.create`, `artifact.update`, and `proposal.apply` for explicit
composition with `OperationExecutionKernel`. It installs no HTTP route, GUI/MCP exposure, or
runtime singleton. #5352 owns authenticated installation; MVR-05C/#3861 remains its production
write-activation prerequisite and the existing pre-05C seal remains in force.

The finite owners are the existing governed capture entrypoint, the EXE/GOV
`mcp.vault.append_note` chain for typed `kind=note` creation, GOV plus HKA's versioned writer for
body editing, and `PanelConfirmationService.confirm` for an existing owner-validated proposal.
The server explicitly binds existing capture schema validation and `capture_to_inbox` execution;
the operations module imports no interaction route and refuses an absent binding.
The server pins context/generation, actor, vault root, and the existing note identity/locator;
operation arguments cannot supply arbitrary filesystem targets or artifact schemas. Direct body
editing preserves the source frontmatter and rejects metadata fields. Metadata requests must name
an existing Panel proposal and retain its field/schema, action allowlist, confirmation, and APPLY
gates. Classification/tagging ownership remains #5335.
If the existing raw frontmatter splitter cannot preserve an identity-recognized source boundary
(for example CR-only frontmatter), the dormant body-edit handler returns invalid before GOV or
source effects. It never substitutes an empty metadata prefix.

Panel source writeback now uses HKA CAS and returns its original `WriteReceipt`. A supplied caller
version is checked before graph preparation and passed unchanged to the final write. Source
failure cannot produce an executed confirmation; post-source failure preserves the source receipt
and reports recovery. The autonomous composition persists its existing GOV AuthorityReceipt at
the source-receipt checkpoint, before releasing notifications or acknowledgements. Its note
diagnostics remain pending rather than claiming an effect was already queued. Queuing a downstream
action is not proof that its semantic owner applied that action: proposal-backed operations remain
`not_acknowledged` with a pending operation receipt and retain the diagnostic source receipt
separately until the semantic owner's effect receipt is known. The same source read validates both
version and live artifact identity before authorization.

Successful capture/create/body source writes retain their GOV accountability and source receipt, but report
`convergence_pending` with Store/index/link `rebuild_required` until their existing owners reconcile
from source. This is exposed repair work, not a claim that a new repair consumer is installed.
Unknown effects and incomplete receipts require reconciliation and are never retried by these
handlers. The kernel's durable request reservation/replay remains the operation recovery boundary;
it does not replace AuthorityReceipt or extend #4659's append guarantee across processes.

The existing user-present Canvas body-edit policy (#4932) and MCP v1 capture protocol are unchanged.
This child does not establish shipped cross-surface capability acceptance; parent #5329 retains it.

## Why This Matters

An agent can only act autonomously when a bounded delegation reaches the same safe writer as the GUI.

## Acceptance Criteria

- [ ] Capture/create/update production handlers invoke only enumerated governed writer entrypoints.
  Verify: `tests/operations/test_write_operations.py::test_write_operations_invoke_only_governed_owner_entrypoints`
- [ ] Version mismatch, policy denial, validation error, and ambiguous acknowledgement remain distinct and non-retrying.
  Verify: `tests/operations/test_write_operations.py::test_write_failures_preserve_conflict_denial_validation_and_ambiguity`
- [ ] Successful outcomes bind source receipt, provenance, and projection convergence without claiming lag as full convergence.
  Verify: `tests/operations/test_write_operations.py::test_success_binds_effect_receipt_and_truthful_projection_state`
- [ ] Existing MCP v1 capture semantics remain unchanged.
  Verify: `tests/mcp/test_mimer_server.py::test_capture_preserves_governed_receipt_at_production_callsite`

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/operations/test_write_operations.py tests/mcp/test_mimer_server.py`
- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/api/test_capture_inbox_api.py`
- `ruff check app tests`

Additional owner-boundary proof:

- `tests/operations/test_write_operations.py::test_panel_confirmation_write_is_versioned_and_failures_do_not_succeed`
- `tests/operations/test_write_operations.py::test_dormant_autonomous_edit_preserves_canvas_policy_and_installation_seal`
- `tests/operations/test_write_operations.py::test_committed_source_survives_projection_and_authority_receipt_failures`
- `tests/operations/test_write_operations.py::test_replay_after_restart_never_repeats_a_committed_owner_write`

## Out of Scope

- Raw filesystem writes, arbitrary schema creation, move/rename, batch execution, or migration of the registered writer families already delivered under #3570. The finite Panel source/CAS/receipt consolidation is included in AUTOOPS-04.
- Replacing #4659's append transaction mechanism or adding a competing journal, cross-process append guarantee, authenticated runtime installation, deployment, or promotion.

## Restart / Durability Posture

Committed source effects and receipts survive restart. An unacknowledged response is recoverable by
operation identity; restart never turns uncertainty into a retry.

The dormant AUTOOPS-08 body-edit composition can explicitly call
`reconcile_write_operation` through the kernel's recovery mode. Newly recorded body-edit outbox
receipts include an original-request digest. Recovery reads the exact native source/GOV receipt,
verifies original identity/context/arguments/version and the resulting source version, and reports
remaining projection repair. Missing, legacy-unbound, or changed-source evidence stays recoverable;
the function never retries a body write. Capture/create/proposal recovery is not added by this seam.
For batch body edits, the original delegated deadline travels through the existing absolute writer
and KnowledgePort to FS CAS/conflict publication. It is checked after all native blocking work,
without extending native authority or installing a scoped-capture/production binding.

## Related Docs

- `docs/contracts/YGGDRASIL_AUTONOMOUS_OPERATIONS_CONTRACT.md`
- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md`

## Related GitHub Issues

Block on AUTOOPS-02 and use the completed #3570 writer-safety work as existing seam evidence; do not treat it as coverage for a new AUTOOPS-02 writer path. TCD hint:
`fresh_issue_agent`, helper budget 1, strongest reliable capability at high reasoning for authority-bearing writes.
