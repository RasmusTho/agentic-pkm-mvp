---
name: Start Model Inquiry from Exact Preview
description: Add the first governed devUI command using Start/Hold and the existing artifact-first inquiry receipt.
task_id: FCP-04
github_issue: 4697
source_anchor: "docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: First command flow — Start Model Inquiry"
parent_capability: devUI Focus + Conversation Port
prerequisites: [FCP-03, "accepted FCA-08 bounded inquiry admission contract (#5502)"]
depends_on: [OPEN_EXTERNAL_CONVERSATION_PORT.md]
can_parallelize_with: []
recommended_capability: "Configured strong_reasoning / dev"
capability_rationale: "Exactly-once external-host command admission and ambiguous-outcome recovery require stronger adversarial reasoning."
---

# Start Model Inquiry from Exact Preview

## Purpose

Deliver the first and only governed command in this slice: preview an exact inquiry question and
start the existing artifact-first Model Inquiry workflow once after explicit owner confirmation.

## What This Task Does

- Implements only the first operation of the [bounded action admission contract](../BUILDER_FACTORY_ACCEPTANCE/README.md#bounded-action-admission)
  repaired by #5502, through the existing authenticated BuilderOps control-plane service and
  sanctioned inquiry destination. #4169 retains DDO-specific initiation and is not a dependency
  on the complete DDO portfolio for this inquiry. The contract alone is not implemented admission.
  Admission, destination reservation and readback are FCP-04 implementation deliverables, not
  prerequisites that must be delivered before this task can begin. Pickup requires the accepted
  contract, delivered FCP-03 and fresh live Issue readiness; runtime Start requires this task's
  verified implementation.
- Implements the [approved inquiry operation interface](../BUILDEROPS_MODEL_INQUIRY/README.md#approved-inquiry-operation-interface)
  through `SanctionedModelInquiryWorkflow`, its manual facade entrypoint, finite capabilities /
  reserve / attempt / approved-launch / readback verbs, and the existing destination artifact owner.
  This explicitly replaces the former assumption of unchanged question-file-only mechanics.
  One executable facade owns route/lock/staging/cleanup; manual skill use delegates to it.
  The owner contract admits its exact-path runtime cleanup helper instead of assistant-only
  `apply_patch` deletion, without expanding the cleanup matrix or destructive authority.
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

The service's current `POST /v1/inquiries` stores a `ModelInquiry` record; it does not call the
fixed host-local `yggdrasil-model-inquiry` launcher. The existing destination artifacts and runner
produce inquiry execution/terminal evidence. This slice must supply the missing durable
operation-key/approval-to-inquiry reservation, conflict checks, authenticated status lookup and
restart reconciliation at those existing owners before Start is available. It must bind the
complete immutable approval/readback fields and finite recovery cases in the owner contract,
including current permission, expiry, source, policy and workflow revalidation immediately before
launch. An unknown attempt is reconciled before any further launch.

Reserve, attempt and readback authenticate the exact service-owned approval; SSH access and manifest
text alone do not authorize an operation. The destination re-reads current permission, sources,
expiry, workflow/policy/profile and authority epoch immediately before a runner effect. Initial
subjects remain an exact configured Issue or explicit-null pre-ticket question; no capability-subject
reader, arbitrary source fetch or general command expansion is admitted. The concrete production
constructor, facade and destination must succeed with only the host-process/provider boundary
faked. A permanently unwired port is insufficient. Live wrapper installation/confirmation, credential
scope changes, deployment and an actual inquiry remain separate operator gates.

The current inquiry workflow supports no stop request or acknowledgement. Render stop as
unsupported and preserve the existing skill's ambiguity/lock rules; Hold before invocation remains
the only no-call choice. An inquiry terminal result is not proof of a requested process stop.
Inquiry approval still grants no code, GitHub, merge, deploy or Issue-delivery effect.

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

- [x] Preview validation requires every exact input, source, destination, effect, rule, expiry,
  receipt, refusal and hash binding, including the bounded operation-aware interface.
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_command_preview_requires_complete_exact_binding`
- [x] Changed or expired preview material withdraws Start; final current source/profile/permission
  checks cannot be replaced by stored or client-supplied snapshots.
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_stale_or_changed_preview_cannot_start`
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_destination_final_revalidation_prevents_revoked_launch`
- [x] Start is unavailable without an authenticated owner principal, and loopback/Host admission
  never substitutes for action authentication. Every control verb authenticates its exact approval.
  - Verify: `tests/api/test_devui_model_inquiry_command.py::test_start_requires_authenticated_action_boundary`
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_operation_protocol_authenticates_every_control_verb`
- [x] Hold invokes nothing; replay after double submit, refresh or restart returns existing/active/
  ambiguous readback without relaunch. The exact reserved ID survives every invocation boundary.
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_operation_key_replay_never_relaunches_inquiry`
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_operation_entry_is_consumed_once`
- [x] Production invocation reuses only the existing skill-owned workflow boundary through its
  complete concrete constructor/facade/destination path; manual use delegates to the same mechanics.
  - Verify: `tests/architecture/test_devui_focus_boundaries.py::test_model_inquiry_adapter_reuses_existing_workflow`
  - Verify: `tests/api/test_devui_model_inquiry_command.py::test_production_constructor_reaches_sanctioned_inquiry_protocol`
  - Verify: `tests/governance/test_start_model_inquiry_skill.py::test_manual_skill_facade_preserves_fixed_route_and_exact_question`
- [x] Valid and ambiguous results preserve the existing receipt and recovery contract, with only
  the exact-path runtime cleanup substitution permitted and no protected-state deletion.
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_receipt_and_ambiguous_outcomes_preserve_workflow_contract`
  - Verify: `tests/governance/test_start_model_inquiry_skill.py::test_facade_cleanup_preserves_ambiguous_recovery_state`
- [x] The command has no forbidden direct effect, and an unsupported wrapper refuses before reservation.
  - Verify: `tests/architecture/test_devui_focus_boundaries.py::test_start_model_inquiry_has_no_forbidden_effect`
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_unsupported_operation_capabilities_refuse_before_reservation`
- [x] Nonvisual fixtures cover exact preview, Start/Hold, staleness, valid/ambiguous receipt and
  workflow unavailable without prescribing visual treatment or claiming owner acceptance.
  - Verify: `tests/builderops/test_devui_model_inquiry_command.py::test_model_inquiry_emits_design_handoff_fixtures`


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

The nonvisual implementation and production-seam proof are delivered by [#4697](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4697);
GitHub owns its delivery/closure state. Live host/service activation remains separately gated.
Delivery posts its command/receipt validation to the parent, which remains open for capability
acceptance and owner-doc reconciliation.
