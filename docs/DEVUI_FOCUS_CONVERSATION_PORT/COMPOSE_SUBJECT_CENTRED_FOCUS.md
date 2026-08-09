---
name: Compose Subject-Centred Focus
description: Add the read-only subject contract and composition for one stable Issue or capability.
task_id: FCP-01
github_issue: 4694
source_anchor: "docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md :: Minimal Focus data contract"
parent_capability: devUI Focus + Conversation Port
prerequisites: []
depends_on: []
can_parallelize_with: []
recommended_capability: "Codex Terra / high"
capability_rationale: "Bounded multi-source projection work with security-sensitive correlation and freshness invariants."
---

# Compose Subject-Centred Focus

## Purpose

Deliver the minimal read-only Focus projection for exactly one stable GitHub Issue or governed
capability without adding source authority, persistence, or inferred execution links.

## What This Task Does

- Defines and validates `SubjectRef.v1`, `SourceRef.v1`, `SourceClaim.v1`,
  `ExecutionObservation.v1`, and `FocusView.v1`.
- Extends the delivered devUI composition seam with a subject composer that reuses CKM, Cockpit,
  Builder System process, and receipt sources.
- Renders owner intent, governing source, evidence, receipts, risks, limitations, next legal step,
  and only explicitly correlated observations.
- Preserves the five evidence axes and per-source timestamps/watermarks.
- Produces fixtures consumed by the governed visual handoff.

## Concretely

For `issue:#123`, a read returns one `focus-view.v1` whose subject remains `issue:#123`; a Cockpit
observation with an explicit receipt link appears as linked evidence, while a provider session that
mentions `#123` remains unlinked and cannot change the next legal step.

## Why This Matters

Without a stable subject and positive correlation rule, Focus would recreate the same owner-side
joining burden it is meant to remove and could falsely present conversation or runtime noise as
delivery progress.

## Acceptance Criteria

- [ ] Issue and capability subjects resolve only from stable governing identities; provider session,
      transcript, PR, worker, and free-form identities are refused.
  - Verify: `tests/builderops/test_devui_focus.py::test_focus_accepts_only_governed_issue_or_capability_subjects`.
- [ ] Every claim preserves independent availability, freshness, coverage, cardinality, and linkage
      axes, including measured-empty watermarks.
  - Verify: `tests/builderops/test_devui_focus.py::test_focus_preserves_independent_evidence_axes`.
- [ ] Execution observations require a governed exact reference or explicit receipt; text,
      timestamp, branch, provider, and repository similarity never create a link.
  - Verify: `tests/builderops/test_devui_focus.py::test_focus_never_infers_execution_correlation`.
- [ ] Unavailable, unread, unsupported, unlinked, missing, and measured-empty fixtures render as
      distinct machine and owner-facing states.
  - Verify: `tests/builderops/test_devui_focus.py::test_focus_distinguishes_required_source_states`.
- [ ] Composition remains per-read, projection-only, local-admission compatible, and mutation free.
  - Verify: `tests/builderops/test_devui_focus.py::test_focus_composition_adds_no_store_or_effect`.
- [ ] Cross-field validation rejects a subject claim supported by unlinked evidence, a
      measured-empty claim without a successful watermark, or a legal next step without a workflow
      reference.
  - Verify: `tests/builderops/test_devui_focus.py::test_focus_rejects_semantically_inconsistent_claims`.

## How to Verify (Pre-Merge)

- Run the six named Focus tests.
- Run the existing devUI composition and local-admission test suites.
- Run `pytest -q tests/architecture/test_devui_focus_boundaries.py` when introduced.
- Run `git diff --check`.

## Out of Scope

- Visual implementation beyond test fixtures.
- Provider conversation launch or transcript ingestion.
- Any command, GitHub/repository mutation, task storage, session inventory, or Builder System
  Control implementation.

## Related Docs

- `docs/DEVUI_FOCUS_CONVERSATION_PORT/README.md`
- `docs/DEVUI.md`
- `app/builderops/devui_composition.py`
- `docs/development/BUILDER_SYSTEM_PROCESS_MAP.md`

## Related GitHub Issues

Filed as blocked child [#4694](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4694) of parent
#4693.
