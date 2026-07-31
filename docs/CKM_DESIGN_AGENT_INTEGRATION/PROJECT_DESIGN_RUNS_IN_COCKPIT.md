---
name: Project Design Runs in the Cockpit
description: Render Yggdrasil-compliant read-only adapter, status, receipt, refusal, and handoff projections in Direction B.
task_id: CDH-05
github_issue: 4312
source_anchor: docs/CKM_DESIGN_AGENT_INTEGRATION/README.md :: Operator surfaces
parent_capability: CKM Design-Agent Integration Hub
prerequisites: [CDH-01, CDH-02, CDH-03, CDH-04, YGGDRASIL-DESIGN-HANDOFF]
depends_on: [DEFINE_DESIGN_RUN_CONTRACTS.md, REGISTER_DESIGN_AGENT_ADAPTERS.md, GOVERN_DESIGN_RUN_LIFECYCLE.md, EXPOSE_DESIGN_RUN_CLI.md]
can_parallelize_with: []
---

# Project Design Runs in the Cockpit

## Purpose

Extend the existing generated cockpit with owner-facing design-run evidence while preserving its
non-authoritative, deterministic, inert local-file contract.

## What This Task Does

Adds an immutable `design_hub` projection DTO to the existing cockpit render context. The CLI
composition root captures sanitized adapter descriptors and validated BuilderOps run projections
before rendering. The existing renderer displays availability, exact brief/run identity,
admission/approval state, causal receipts, typed refusals/failures, and handoff refs.

## Concretely

- Keep CKM projection digest and design-run projection digest separate and visible.
- Sort adapters, refs, receipts, states, and handoffs by explicit stable keys.
- Add no script, form, button, textarea, network link, fetch, polling, storage, or clipboard path.
- Preserve all content with JavaScript disabled and in print.
- Use the canonical Yggdrasil Design System and existing primitives only after the live
  design-system/token parity gate passes.

## Why This Matters

The cockpit should reduce operator context switching without becoming the authority or execution
surface it is observing.

## Acceptance Criteria

- [ ] Adapter selector/projection shows exactly registered availability and never implies an
  unavailable adapter can run.
  Verify: `tests/builderops/ckm/test_design_cockpit.py::test_selector_uses_registered_adapter_availability`
- [ ] Status/handoff views derive only from validated BuilderOps records/receipts and preserve
  projection identity, provenance, freshness, limitations, and non-authority language.
  Verify: `tests/builderops/ckm/test_design_cockpit.py::test_status_and_handoffs_remain_non_authoritative_projections`
- [ ] Unknown, unavailable, denied, pending, malformed, timed-out, and failed states remain
  distinct, fail closed, and never show partial success or fallback.
  Verify: `tests/builderops/ckm/test_design_cockpit.py::test_design_run_refusal_and_failure_states_are_distinct_and_fail_closed`
- [ ] Direction A and cockpit-with-design-hub-disabled output remain unchanged; enabled output is
  byte-deterministic for identical explicit inputs.
  Verify: `tests/builderops/ckm/test_design_cockpit.py::test_default_overview_is_unchanged_without_design_hub`
- [ ] HTML remains inert, JS-off complete, keyboard/200%-zoom usable, and print-complete with no
  color-only meaning.
  Verify: `tests/builderops/ckm/test_design_cockpit.py::test_design_hub_projection_preserves_direction_b_authority`
- [ ] The exact visual implementation and every visual design-run fixture have a passing Yggdrasil
  Design Handoff receipt naming the live system ID, selection/attachment mechanism, repo token
  source, matching SHA-256, and visual checks.
  Verify: `runtime receipt: ckm_design_hub.yggdrasil_handoff.v1`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_design_cockpit.py`
- `python3 -m pytest -q tests/builderops/ckm/test_overview_html.py`
- `ruff check app tests`
- `mypy app`
- Inspect desktop, narrow, 200% zoom, keyboard, JS-off, print, empty, degraded, blocked, and
  unavailable states against the exact Yggdrasil handoff.

## Out of Scope

Run start/approval, new JavaScript, live status, hosted UI, external artifact fetching, new visual
tokens/primitives without an explicit design-system proposal, and Product/Runtime surfaces.

## Related Docs

- `docs/DESIGN_PRINCIPLES.md`
- `.codex/skills/yggdrasil-design-handoff/SKILL.md`
- `docs/CKM_COCKPIT_DIRECTION_B/README.md`

## Related GitHub Issues

Create one child of #4131, initially dependency-blocked until CDH-04 and a passing Yggdrasil
handoff receipt are both terminal.
