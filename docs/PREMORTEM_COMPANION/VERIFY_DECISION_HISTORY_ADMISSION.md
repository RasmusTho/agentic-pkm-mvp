---
name: Verify Decision History Admission
description: Reuse the Decision Calibration identity/linkage seam while making scoped admission and citation behavior explicit before personal decision reflection is introduced.
task_id: PMC-01
source_anchor: docs/PREMORTEM_COMPANION/README.md :: First delivery
parent_capability: Pre-mortem Companion
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Verify Decision History Admission

## Purpose

Prove the exact records a later read-only pre-mortem can lawfully use, without adding any reflective model behavior or changing a decision artifact.

## What This Task Does

Define and test a fail-closed admission adapter for one explicitly selected `decision_record`, its canonical outcome receipts, and historical precedents in the caller's current scope. It reuses CAL-01's stable decision identity and receipt linkage without a second resolver, excludes governance logs, and returns coverage/exclusion posture plus resolvable citations.

## Concretely

The adapter accepts one CAL-01 canonical selected identity. It rejects zero, multiple, stale, malformed, or ambiguous targets; uses the existing receipt linkage and handles its missing/duplicate/malformed outcomes explicitly; and separates admitted, excluded, and unavailable records without disclosing excluded content.

## Why This Matters

Reflective prose can be persuasive. It must never attach another decision's outcome, import governance material, or use a broad vault search as personal evidence.

## Acceptance Criteria

- [ ] Exactly one explicit canonical `decision_record` is required; missing, multiple, stale, or ambiguous selection fails closed. Verify: `tests/calibration/test_premortem_admission.py::test_selected_decision_identity_fails_closed`.
- [ ] Only CAL-01 canonical outcome receipts linked to the selected or admitted historical decisions are returned; no second decision/receipt resolver is introduced, and missing, duplicate, stale, and malformed links have explicit safe outcomes. Verify: `tests/calibration/test_premortem_admission.py::test_reuses_cal01_outcome_links_without_second_resolver`.
- [ ] Personal decision material is admitted only in current scope, while GOV decision logs and cross-scope material are excluded before rendering. Verify: `tests/calibration/test_premortem_admission.py::test_admission_excludes_governance_and_denied_scope`.
- [ ] Every admitted excerpt/outcome has a resolvable citation and no excluded title/body leaks through coverage diagnostics. Verify: `tests/calibration/test_premortem_admission.py::test_admission_returns_only_resolvable_nonleaking_citations`.
- [ ] The adapter performs no write, model call, outcome inference, schedule creation, or profile persistence. Verify: `tests/calibration/test_premortem_admission.py::test_admission_is_read_only_and_noninferential`.

## How to Verify (Pre-Merge)

- `pytest -q tests/calibration/test_premortem_admission.py`
- `pytest -q tests/services/test_outcome_receipt_log.py`
- `pytest -q tests/agent_memory/test_ask_synthesis_gate.py`

## Out of Scope

No LLM packet, option comparison, risk ontology, scheduler, decision-note writeback, outcome inference, personality/profile model, or high-stakes advice.

## Related Docs

- `docs/PREMORTEM_COMPANION/README.md`
- `docs/DECISION_CALIBRATION/README.md`

## Related GitHub Issues

Implementation issue: [#3548](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3548). TCD hint: Sol / high reasoning because identity, human knowledge, scope, and receipt semantics meet at this seam.
