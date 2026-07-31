---
name: Expose Design-Run CLI
description: Provide the explicit operator brief, admission, start, status, and result surface outside generated HTML.
task_id: CDH-04
github_issue: 4311
source_anchor: docs/CKM_DESIGN_AGENT_INTEGRATION/README.md :: Operator surfaces
parent_capability: CKM Design-Agent Integration Hub
prerequisites: [CDH-01, CDH-02, CDH-03]
depends_on: [DEFINE_DESIGN_RUN_CONTRACTS.md, REGISTER_DESIGN_AGENT_ADAPTERS.md, GOVERN_DESIGN_RUN_LIFECYCLE.md]
can_parallelize_with: []
---

# Expose Design-Run CLI

## Purpose

Give the single operator a real authenticated control surface without adding execution authority to
the generated cockpit.

## What This Task Does

Adds bounded BuilderOps CLI commands for deterministic brief creation/inspection, design-agent
listing, admission preview, local-operator approval/revocation, exact start, status, and result. The
CLI calls only the neutral design-run service/domain port, which consumes the shared model-access
substrate.

## Concretely

- Prefer canonical request files over many ambient shell arguments.
- Require explicit adapter ID, source refs, attachment digests, requested deliverable, and
  admission/approval identities.
- Derive approval actor from the authenticated local OS principal; refuse a caller-supplied actor.
- Emit structured terminal output with stable run/receipt/handoff identities and sanitized
  failures.
- Never infer cwd/repo/vault context, start from generated HTML, or call provider implementations
  directly from Click handlers.

## Why This Matters

Direction B deliberately forbids active controls. A CLI preserves that contract and makes
authentication, exact payload review, and failure handling testable.

## Acceptance Criteria

- [ ] CLI brief creation is bounded, deterministic, and requires explicit refs/digests.
  Verify: `tests/builderops/test_design_run_cli.py::test_cli_builds_only_explicit_bounded_briefs`
- [ ] Preview/admission is read-only and start invokes only the neutral service after exact
  admission/approval validation.
  Verify: `tests/builderops/test_design_run_cli.py::test_cli_preview_precedes_exact_governed_start`
- [ ] Approval/revocation derives the local authenticated actor, binds exact hashes, and stale,
  revoked, foreign, or mismatched evidence cannot reach a provider call.
  Verify: `tests/builderops/test_design_run_cli.py::test_cli_approval_and_revocation_are_exact_and_actor_bound`
- [ ] Status/result commands derive from validated durable evidence and expose typed refusal/failure
  without secrets or partial success.
  Verify: `tests/builderops/test_design_run_cli.py::test_cli_status_and_result_are_receipt_derived_and_secret_safe`
- [ ] The generated CKM HTML remains unable to start, approve, fetch, poll, or persist a run.
  Verify: `tests/builderops/test_design_run_cli.py::test_control_surface_stays_outside_static_cockpit`
- [ ] The production CKM/design-run composition submits only the provider-neutral domain request to
  the Builder System design-agent port, which consumes the shared `ModelTurnAdapter` substrate.
  Verify: `tests/builderops/ckm/test_design_cockpit.py::test_ckm_calls_only_builder_system_design_adapter_port`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/test_design_run_cli.py`
- `python3 -m pytest -q tests/builderops/ckm/test_design_cockpit.py::test_ckm_calls_only_builder_system_design_adapter_port`
- `python3 -m pytest -q tests/builderops/test_design_run_governance.py`
- `ruff check app tests`
- `mypy app`

## Out of Scope

Hosted API/UI, Companion UI, provider ranking/fallback, desktop automation, direct GitHub/repo
mutation, and visual cockpit changes.

## Related Docs

- `docs/CKM_DESIGN_AGENT_INTEGRATION/README.md`
- `docs/CKM_COCKPIT_DIRECTION_B/README.md`

## Related GitHub Issues

Create one child of #4131 after CDH-03 is terminal.
