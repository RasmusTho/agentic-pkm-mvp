---
name: Build Vault-Native Pull-Only Moments
description: First runtime slice — compute moments from vault-native data and render them at the glance surface, pull-only, no proactivity and no external connectors.
task_id: CRE-03
source_anchor: docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md :: 7. Slicing direction (1)
parent_capability: Contextual Relevance Engine
prerequisites: [CRE-01, CRE-02]
depends_on: [DEFINE_MOMENT_AND_CONTEXT_MODEL.md, DEFINE_RELEVANCE_AND_SCARCITY_CONTRACTS.md]
can_parallelize_with: []
---

# Build Vault-Native Pull-Only Moments

## Purpose

Prove the core path end-to-end on data already in the vault, with **no proactivity** and **no
external connectors**: context model → relevance evaluator → moment artifact → glance surface. This
is the smallest slice that makes the engine real and useful.

## What This Task Does

- Computes moments from vault-native inputs only (e.g., daily notes, a manually-maintained agenda,
  existing tasks/commitments in the commitment layer).
- Materializes each moment as the vault-native artifact defined in CRE-01 (with provenance + receipt,
  via the write guard).
- Renders moments at the **glance surface** (the companion-UI "now" view) — **pull-only**: the human
  opens it; the system does not yet reach out.
- Uses the relevance evaluator contract from CRE-02 (a deterministic-fallback path is acceptable for
  this slice; the adaptive cognition can be staged).

## Concretely

The companion-UI "now" view shows, on open, the relevant moments computed from today's vault state
(e.g., a start-of-day overview drawn from the daily note + open commitments), each linking back to its
source notes with provenance. No notifications. No calendar/email.

## Why This Matters

This is the proof that the abstraction is real and not just a doc. If a moment cannot be computed from
vault data and rendered with provenance and a receipt, the contracts (tasks 1–2) need revision before
proactivity is built on top.

## Acceptance Criteria

- [ ] A moment is computed from vault-native data and materialized as the CRE-01 artifact with provenance and a receipt, via the write guard.
  - Verify: `tests/relevance/test_vault_native_moments.py::test_moment_materialized_from_vault_with_receipt` (new; sharpened against the CRE-01 schema).
- [ ] The glance surface renders the computed moments pull-only, each linking to its source with provenance; no proactive reach-out occurs.
  - Verify: `tests/companion_ui/test_now_surface.py::test_now_surface_renders_vault_native_moments_pull_only`.
- [ ] No external source is read and no notification is emitted in this slice.
  - Verify: `tests/relevance/test_vault_native_moments.py::test_no_external_source_and_no_notification`.

## How to Verify (Pre-Merge)

- `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest -q tests/relevance tests/companion_ui/test_now_surface.py`
- `ruff check app tests`
- Post a validation receipt to the parent feature issue.

## Out of Scope

- Proactive reach-out / notifications / the scarcity gate (task 4).
- External connectors (deferred slice).
- The emergent/learned pattern loop (a follow-on of task 4).

## Related Docs

- `docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md` (brief, §7)
- `docs/FINDING_AND_REORIENTING/README.md` (orientation/resurfacing reuse)
- `docs/CONCEPTS/COMMITMENT_LAYER_CONTRACT.md`

## Related GitHub Issues

Filed as `agent:blocked` (on CRE-01, CRE-02). Becomes `agent:ready` when both contracts merge. May
split into more than one issue if the evaluator and the now-surface render are large.
