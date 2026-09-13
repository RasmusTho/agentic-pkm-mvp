---
name: Desktop Skill Launchers
description: Package thin Codex and Claude desktop launchers that delegate inquiries to the configured host runner.
task_id: BMI-04
source_anchor: docs/BUILDEROPS_MODEL_INQUIRY/README.md :: Scope
parent_capability: BuilderOps Model Inquiry
prerequisites: [BMI-02, BMI-03]
depends_on: [PRE_TICKET_INQUIRY_RECORDS.md, MODEL_TURN_ADAPTERS.md]
can_parallelize_with: []
---

# Desktop Skill Launchers

## Purpose

Let an operator begin the same inquiry from Codex Desktop or Claude Desktop without putting the
orchestrator inside either chat history or configuring providers in the local workspace.

## What This Task Does

BMI-04 delivered the fixed host-bound manual skill. FCP-04/#4697 explicitly extends its previously
question-file-only mechanics through the
[approved inquiry operation interface](README.md#approved-inquiry-operation-interface).
That section is the exact protocol, ownership, authentication, cleanup and compatibility authority;
this task no longer carries a second executable route/lock/staging recipe.

One repo-governed `SanctionedModelInquiryWorkflow` facade implements the existing skill boundary.
The repo-local skill and portable manual entrypoint delegate to it. Manual use preserves the fixed
host launch and exact question bytes. Authenticated service use additionally supplies the immutable
approval, operation key and reserved inquiry identity through the finite host protocol. Capability
readback, reservation and attempt verbs cannot call a model, and only the single approved launch
verb can reach the existing configured runner. FCP-04 delivers this bounded implementation and
its production-seam proof; the current live host wrapper's activation remains separately gated.

The operational `$HOME/.local/bin/yggdrasil-model-inquiry` wrapper, subscription session and provider
configuration remain host-owned and outside Git. The repo provides a complete operation protocol
implementation and production-seam fixtures but never inspects, replaces or provisions the live
wrapper or its credentials. ADR-0064's subscription cost/auth ruling is unchanged.

The shared facade preserves fixed alias/principal/home/public-host-key route proof, single-flight
locking, exact fixed staging, capture of exit status and stdout before cleanup, no retry after an
ambiguous outcome, and separation of cleanup failures from the original result. FCP-04 explicitly
admits one exact-path runtime cleanup helper in place of the former assistant-tool-specific
`apply_patch` deletion mechanics. The caller temp is the only unconditional deletion; ambiguous
attempts preserve staging and lock, and no durable inquiry artifact is deleted.

The dormant provider-API mechanism remains under its distinct
`yggdrasil-model-inquiry-provider-api` identity. `scripts/install_model_inquiry_host.py` owns only
that dormant wrapper and its two role entrypoints. Neither the skill facade nor this Issue may use
that installer to inspect, alter or claim readiness for the operational subscription wrapper.

## Concretely

```text
$start-model-inquiry Hur bör eventmodellen utformas?
```

## Why This Matters

The desktop apps are ergonomic front doors, not durable state machines or a reliable bridge to each
other.

## Acceptance Criteria

- [x] Both desktop skill packages preserve the exact remote-host bridge command and report its
  inquiry receipt fields. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Both packages reject local BuilderOps setup, provider configuration, credential provisioning, and
  desktop-control automation. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Both packages fail loudly for a copy/SSH failure, empty stdout, malformed JSON, or an absent
  receipt field. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Both packages atomically lock the fixed host question path rather than silently overwriting
  a concurrent inquiry. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Both packages release staging and the lock through the selected route only after a pre-launch
  failure or a verified receipt, preserving both after an ambiguous launcher result. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.
- [x] Codex local cleanup uses policy-compatible exact-target deletion for the caller temp and fixed
  staging file, never a blocked shell `rm -f`, and cannot mask the captured launcher result. Verify:
  `tests/architecture/test_agent_skill_entrypoints.py::test_model_inquiry_local_host_route_is_identity_gated_and_fail_closed`.
- [x] The Codex skill selects its local-host route only after fixed-alias, OS principal/home, and
  pinned-host-key proofs all match, invokes only the fixed host launcher, shares the fixed
  single-flight lock, strictly validates the terminal response, and preserves staging after
  ambiguous outcomes. Verify:
  `tests/architecture/test_agent_skill_entrypoints.py::test_model_inquiry_local_host_route_is_identity_gated_and_fail_closed`.
- [x] Desktop packages accept only an exit-zero terminal JSON response from the sanctioned
  subscription launcher and preserve staging after every nonzero/ambiguous result. Verify:
  `tests/governance/test_start_model_inquiry_skill.py::test_desktop_skills_route_to_macmini_launcher`.

## How to Verify (Pre-Merge)

- `pytest -q tests/architecture/test_agent_skill_entrypoints.py tests/governance/test_start_model_inquiry_skill.py`
- `python3 scripts/lint_skills_consistency.py`
- `python3 scripts/package_claude_skill.py --output /tmp/start-model-inquiry.zip`

The generated ZIP contains `start-model-inquiry/SKILL.md` at its root and is uploaded manually by
the operator. Generated archives are release artifacts and remain outside Git source control.

## Out of Scope

- automating clicks or keystrokes in the other desktop app;
- storing model transcripts in Companion UI or a human knowledge vault.
- installing Python, BuilderOps, Codex, or Claude on the local machine;
- provisioning or inspecting metered credentials or subscription-session material.

## Related Docs

- `docs/BUILDEROPS_MODEL_INQUIRY/README.md`
- `.codex/skills/README.md`

## Related GitHub Issues

- Parent feature: [#3288](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3288)
- Implementation: [#3292](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3292)
