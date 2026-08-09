---
name: Start Model Inquiry from Exact Preview
description: Add the first governed devUI command using Start/Hold and the existing artifact-first inquiry receipt.
task_id: FCP-04
github_issue: 4697
source_anchor: "docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: First command flow — Start Model Inquiry"
parent_capability: devUI Focus + Conversation Port
prerequisites: [FCP-03, "authenticated action boundary #4169"]
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
- Produces the complete preview-state contract for exact input/source/destination/side-effect/
  non-effect/approval/expiry/receipt details without choosing a visual treatment.
- Revalidates the authenticated principal, proposal, pack, sources, workflow contract, destination
  operation-key support, and expiry immediately before Start.
- Routes Start through the separately authenticated action boundary and maps it to the existing
  `.codex/skills/start-model-inquiry/SKILL.md` path with one destination-owned operation key; Hold
  makes no workflow invocation.
- Adds bounded operation-key/readback support to the existing inquiry artifacts so refresh, process
  restart, or ambiguous response cannot launch a second inquiry for the same proposal.
- Maps valid terminal fields to the receipt view and malformed/nonzero/empty outcomes to honest
  ambiguity without retry or protected-state cleanup.

## Concretely

The owner previews exact question bytes, source versions, pack/proposal hashes, destination,
side effects, non-effects, expiry, and expected receipt. Hold makes no call. Start revalidates and
calls the existing workflow once; a malformed response renders ambiguous and does not retry.

The loopback-only `/api/devui` read route never admits Start. A replayed operation key returns the
existing inquiry/receipt or an honest active/ambiguous readback from the artifact-first destination.

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
- [ ] Start is unavailable without an authenticated owner principal, and local loopback/Host
      admission never substitutes for action authentication.
  - Verify: `tests/api/test_devui_model_inquiry_command.py::test_start_requires_authenticated_action_boundary`.
- [ ] Hold invokes nothing; duplicate submit, browser refresh, or process restart reuses the same
      destination operation key and returns the existing inquiry/receipt or active/ambiguous
      readback without a second launch.
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_operation_key_replay_never_relaunches_inquiry`.
- [ ] The adapter invokes only the existing start-model-inquiry boundary and does not reproduce its
      host, lock, staging, credential, subscription, cleanup, or provider logic.
  - Verify: `tests/architecture/test_devui_focus_boundaries.py::test_model_inquiry_adapter_reuses_existing_workflow`.
- [ ] A valid response requires non-empty `inquiry_id`, `final_state`, `terminal_receipt_id`, and
      `human_readable_report`; invalid/nonzero/empty results render ambiguous and trigger no retry.
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_receipt_and_ambiguous_outcomes_preserve_workflow_contract`.
- [ ] No GitHub, repository, delivery-run, CKM, provider-session, or task mutation is made by the
      preview or adapter.
  - Verify: `tests/architecture/test_devui_focus_boundaries.py::test_start_model_inquiry_has_no_forbidden_effect`.
- [ ] The adapter emits complete design-handoff fixtures for exact preview, Start/Hold, stale
      invalidation, valid receipt, ambiguous receipt, and provider/workflow unavailable states.
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_model_inquiry_emits_design_handoff_fixtures`.

## How to Verify (Pre-Merge)

- Run all named unit and architecture tests.
- Use workflow fakes to prove unauthenticated refusal, Hold, duplicate submit, refresh/restart
  readback, stale preview, valid receipt, ambiguous response, and unavailable destination behavior
  without contacting providers in unit tests.
- Complete one governed end-to-end receipt on the configured path when the Issue contract admits
  live validation.
- Run `git diff --check`.

## Out of Scope

- Inquiry promotion, Issue creation, docs change, or delivery initiation.
- Any `Apply/Hold` command.
- General DDO/GitHub/repository commands or live delivery controls.
- Provider adapter, credential, or route-selection changes. The only admitted destination change is
  bounded operation-key/readback support in the existing artifact-first inquiry flow.
- Browser layout, interaction geometry, or visual implementation; FCP-02 owns the governed handoff.

## Related Docs

- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`
- `.codex/skills/start-model-inquiry/SKILL.md`
- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `docs/BUILDEROPS_MODEL_INQUIRY/PROMOTION_AND_TRACEABILITY.md`

## Related GitHub Issues

Filed as final blocked child [#4697](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4697).
Delivery posts its command/receipt validation to the parent, which remains open for capability
acceptance and owner-doc reconciliation.
