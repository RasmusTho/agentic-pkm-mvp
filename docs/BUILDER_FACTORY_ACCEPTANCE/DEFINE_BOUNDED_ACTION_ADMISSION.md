---
name: "Define bounded action admission"
description: "FCA admits a first non-DDO workflow, but #4169 still couples its authenticated boundary to the complete DDO bridge. Resolve the contract before changing dependents."
task_id: FCA-08
github_issue: 5502
source_anchor: "docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: FCA-08 — Bounded action contract repair"
parent_capability: "BUILDER_FACTORY_ACCEPTANCE"
prerequisites: []
depends_on: []
can_parallelize_with: []
---

State: Bounded admission contract defined by #5502 at the owner anchors below. Runtime implementation, activation and deployment remain unproved.
Doc role: Target-state task specification in an existing capability directory.
Authority: Existing capability and owner documents govern the repair. This task defines work and verification, not the repaired action/data/runtime authority. Source disposition: #5399 comment 5648534770.

# Define bounded action admission

## Purpose

FCA admits a first non-DDO workflow, but #4169 still couples its authenticated boundary to the complete DDO bridge. Resolve the contract before changing dependents.

## What This Task Does

The repaired normative contract is [Bounded action admission](README.md#bounded-action-admission)
and the finite table in [Cross-Task Invariants / Interaction Safety](README.md#cross-task-invariants--interaction-safety).
The service, inquiry, FCP capability/parent, implementation plan and DDO owners use that same
contract and distinguish pickup prerequisites from the inquiry task's implementation and activation.
The following scope records the
bounded repair; it does not authorize executing any operation.

- Define the finite admission/readback responsibilities in the existing BuilderOps control-plane service and existing sanctioned destination launcher/artifacts; retain #4169 as owner of the DDO-specific compiler/reducer/CKM bridge. A stored inquiry record is not a launch receipt: name the actual launcher and any missing operation-key-to-inquiry reservation explicitly.
- Name an immutable approval manifest: owner principal, repository and Issue/question identity, source/Issue-body/AC revisions, operation type and key, exact workflow version, permitted effects, policy/config/profile bindings, expiry, and revocation semantics.
- Admit Start Model Inquiry as the first operation. Define a separately gated extension for one approved Issue workflow; inquiry approval grants no code, GitHub, merge or deploy effects.
- Specify persisted destination deduplication, status lookup after lost responses, restart reconciliation, and expiry/revocation before launch. Name stop support from the actual workflow: an unsupported stop remains unsupported; a supported stop request/acknowledgement is distinct from observed termination.
- Update #4169/#4697/#5404 dependency wording only after this contract is accepted. Make no new action service, queue or DevUI store.

## Concretely

A proposal to inspect Issue A can start one inquiry. The same approval cannot start issue-to-code for Issue A, nor an inquiry for Issue B.

## Why This Matters

The complete owner journey depends on this finite seam. Delivering the module or a fixture alone must not be described as live owner-platform acceptance.

## Acceptance Criteria

- [x] The admitted service, destination producers and exact approval/readback fields are enumerated, including per-operation permissions. Verify: doc writeback at `docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: Bounded action admission`
- [x] DDO-specific initiation remains in #4169's owning specification; the first inquiry dependency names the bounded seam and preserves its no-delivery restriction. Verify: doc writeback at `docs/DEVUI_FOCUS_CONVERSATION_PORT/START_MODEL_INQUIRY_FROM_PREVIEW.md :: What This Task Does`
  The FCP capability owner, parent task pointer and Stage A2 plan distinguish external prerequisites,
  FCP-04 deliverables and runtime Start availability.
  - Verify: doc writeback at `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: Open implementation dependencies`
  - Verify: doc writeback at `docs/DEVUI_FOCUS_CONVERSATION_PORT/PARENT_FEATURE_ISSUE.md :: Constraints`
  - Verify: doc writeback at `docs/plans/DEVUI_IMPLEMENTATION.md :: Stage A2 — Focus + external Conversation Port`
- [x] The control-plane and DDO specifications agree on the existing service, actual destination launcher, readback producer and remaining missing support; record storage, launch and observed termination are not conflated.
  - Verify: doc writeback at `docs/BUILDEROPS_CONTROL_PLANE/README.md :: Target boundary`
  - Verify: doc writeback at `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/CONNECT_CKM_INITIATION_AND_DELIVERY_RECEIPTS.md :: What This Task Does`
- [x] Lost-response, expired approval, revoked permission, changed source and stop cases have an explicit finite transition table and expected evidence. Verify: doc writeback at `docs/BUILDER_FACTORY_ACCEPTANCE/README.md :: Cross-Task Invariants / Interaction Safety`

## How to Verify (Pre-Merge)

For each AC, review the named writeback anchor and its finite examples against the current source owner; all are pre-merge document targets. Run `python3 scripts/docs_guard.py --language-only`, the current diff-aware docs guard, and `git diff --check`; verify changed index rows and all source links. Validate the final Issue body before readiness. No runtime test or live acceptance pass is implied.

## Out of Scope

No runtime implementation, provider replacement, new service, workflow activation or weakening of DDO fencing. Only the explicitly named dependent Issue contracts may be reconciled through issue maintenance; this task grants no delivery/GitHub effect to the inquiry operation.

## Restart / Durability Posture

No runtime state changes in this task.

## Related Docs

- `docs/BUILDER_FACTORY_ACCEPTANCE/README.md`
- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/CONNECT_CKM_INITIATION_AND_DELIVERY_RECEIPTS.md`
- `docs/DEVUI_FOCUS_CONVERSATION_PORT/START_MODEL_INQUIRY_FROM_PREVIEW.md`
- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`
- `docs/DEVUI_FOCUS_CONVERSATION_PORT/PARENT_FEATURE_ISSUE.md`
- `docs/plans/DEVUI_IMPLEMENTATION.md`
- `docs/BUILDEROPS_CONTROL_PLANE/README.md`

## Related GitHub Issues

Parent validation: #5399. Existing related work: #4169, #4697, #5404. Execution: [#5502](https://github.com/RasmusTho/agentic-pkm-mvp/issues/5502) from specification FCA-08. GitHub owns live readiness and delivery state. Milestone: M0.

Execution context: fresh_issue_agent; helper budget 1 for the required independent authority/mechanism review when the contract is repaired; configured Codex / high reasoning. This is a non-binding capability hint; the execution skill reclassifies the actual diff. Serial delivery is the default.
