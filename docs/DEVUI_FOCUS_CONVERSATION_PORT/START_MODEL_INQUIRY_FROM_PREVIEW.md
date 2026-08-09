---
name: Start Model Inquiry from Exact Preview
description: Add the first governed devUI command using Start/Hold and the existing artifact-first inquiry receipt.
task_id: FCP-04
github_issue: 4697
source_anchor: "docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: First command flow — Start Model Inquiry"
parent_capability: devUI Focus + Conversation Port
prerequisites: [FCP-03]
depends_on: [OPEN_EXTERNAL_CONVERSATION_PORT.md]
can_parallelize_with: []
recommended_capability: "Codex Sol / high"
capability_rationale: "Exactly-once external-host command admission and ambiguous-outcome recovery require stronger adversarial reasoning."
---

# Start Model Inquiry from Exact Preview

## Purpose

Deliver the first and only governed command in this slice: preview an exact inquiry question and
start the existing artifact-first Model Inquiry workflow once after explicit owner confirmation.

## What This Task Does

- Defines and validates `TypedCommandProposal.v1` for `start_model_inquiry` only.
- Renders exact input/source/destination/side-effect/non-effect/approval/expiry/receipt details.
- Revalidates the proposal, pack, sources, workflow contract, and expiry immediately before Start.
- Maps Start to the existing `.codex/skills/start-model-inquiry/SKILL.md` path exactly once and Hold
  to no workflow invocation.
- Maps valid terminal fields to the receipt view and malformed/nonzero/empty outcomes to honest
  ambiguity without retry or protected-state cleanup.

## Concretely

The owner previews exact question bytes, source versions, pack/proposal hashes, destination,
side effects, non-effects, expiry, and expected receipt. Hold makes no call. Start revalidates and
calls the existing workflow once; a malformed response renders ambiguous and does not retry.

## Why This Matters

This is the first durable-consequence boundary in the Conversation Port. Reimplementing the
launcher or treating an uncertain response as failure could duplicate an inquiry or destroy the
existing recovery evidence.

## Acceptance Criteria

- [ ] Proposal validation requires exact inputs, source refs, destination, side effects,
      non-effects, approval rule, absolute expiry, expected receipt fields, refusal conditions, and
      canonical proposal/context hashes.
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_command_preview_requires_complete_exact_binding`.
- [ ] Changed question, pack, source version, correlation, workflow contract, or expiry withdraws
      Start and requires a new preview.
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_stale_or_changed_preview_cannot_start`.
- [ ] Hold invokes nothing; double submit invokes the governed route at most once for the bound
      proposal; browser refresh cannot create a second effect.
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_start_hold_and_double_submit_are_safe`.
- [ ] The adapter invokes only the existing start-model-inquiry boundary and does not reproduce its
      host, lock, staging, credential, subscription, cleanup, or provider logic.
  - Verify: `tests/architecture/test_devui_focus_boundaries.py::test_model_inquiry_adapter_reuses_existing_workflow`.
- [ ] A valid response requires non-empty `inquiry_id`, `final_state`, `terminal_receipt_id`, and
      `human_readable_report`; invalid/nonzero/empty results render ambiguous and trigger no retry.
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_receipt_and_ambiguous_outcomes_preserve_workflow_contract`.
- [ ] No GitHub, repository, delivery-run, CKM, provider-session, or task mutation is made by the
      preview or adapter.
  - Verify: `tests/architecture/test_devui_focus_boundaries.py::test_start_model_inquiry_has_no_forbidden_effect`.
- [ ] Browser acceptance covers exact preview, keyboard Start/Hold, stale invalidation, valid
      receipt, ambiguous receipt, and provider/workflow unavailable states.
  - Verify: `tests/browser/test_devui_model_inquiry_command.py::test_model_inquiry_command_acceptance_matrix`.

## How to Verify (Pre-Merge)

- Run all named unit, architecture, and browser acceptance tests.
- Use workflow fakes to prove Hold, double-submit, refresh, stale preview, valid receipt, ambiguous
  response, and unavailable destination behavior without contacting providers in unit tests.
- Complete one governed end-to-end receipt on the configured path when the Issue contract admits
  live validation.
- Run `git diff --check`.

## Out of Scope

- Inquiry promotion, Issue creation, docs change, or delivery initiation.
- Any `Apply/Hold` command.
- General DDO/GitHub/repository commands or live delivery controls.
- Inquiry launcher, provider adapter, or credential changes.

## Related Docs

- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`
- `.codex/skills/start-model-inquiry/SKILL.md`
- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/BUILDEROPS_MODEL_INQUIRY/PROMOTION_AND_TRACEABILITY.md`

## Related GitHub Issues

Filed as final blocked child [#4697](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4697).
Delivery posts its command/receipt validation to the parent, which remains open for capability
acceptance and owner-doc reconciliation.
