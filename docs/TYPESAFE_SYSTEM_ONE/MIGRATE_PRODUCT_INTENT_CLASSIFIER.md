---
name: Use Jev for Product Canvas Intent Classification
description: Replace prompt-and-parse intent JSON with typed Jev judgments while preserving write gates.
task_id: TSO-03
github_issue: 5767
source_anchor: app/components/llm/intent_classifier.py :: IntentClassifierCognition.classify
parent_capability: TYPESAFE_SYSTEM_ONE
prerequisites: [TSO-01, TSO-02]
depends_on: [DEFINE_SYSTEM_ONE_JUDGMENT_CONTRACT.md, ADD_TYPESAFE_TO_MAC_EXECUTOR.md]
can_parallelize_with: [TSO-04 after TSO-01]
---

# Use Jev for Product Canvas Intent Classification

## Purpose

The canvas classifier currently asks a general completion model to return a small JSON classification. A typed judgment can remove that prompt-and-parse step while preserving the existing fail-closed and human-confirmation behavior.

## What This Task Does

- Replace the current constrained completion at the canvas intent-classifier call site with the Product-selected MARR System One operation.
- Use closed Choice sets for intent class and governance-action category; include a no-match/unknown outcome.
- Keep request state bounded to the user intent and the minimum necessary current-canvas context. Never send the full note body for this pilot.
- Map service failure, malformed output, or evaluated low confidence to the existing `UNKNOWN` result.
- Keep confirmation, Apply authorization, WriteGuard, and all durable write boundaries unchanged.

## Concretely

The classifier sends one bounded state object and named Choice questions. The returned class/action is mapped to the existing `IntentClassification`. Unknown/uncertain results remain `classified=False` and cannot authorize a mutation.

## Why This Matters

The current consumer's output is a closed semantic choice, not generated prose. Preserving the existing downstream gates prevents better-typed inference from being mistaken for permission.

## Acceptance Criteria

- [ ] The production classifier uses the Product-owned MARR judgment client and sends only its bounded request fields. Verify: `tests/components/llm/test_intent_classifier_typesafe.py::test_production_classifier_uses_marr_and_minimal_state`.
- [ ] Service errors and low-confidence answers map to `UNKNOWN` and never enter a mutation-capable class. Verify: `tests/components/llm/test_intent_classifier_typesafe.py::test_uncertain_judgment_remains_unknown_without_authorizing_write`.
- [ ] Existing confirmation and write-guard call sites remain required for governance-bearing outputs. Verify: `tests/components/llm/test_intent_classifier_typesafe.py::test_governance_judgment_still_requires_confirmation_and_write_guard`.
- [ ] The supported Product owner docs describe this as a dev-accepted route only until staged rollout acceptance. Verify: doc writeback at `docs/LLM_ROUTING.md :: Current policy and future work`.

## How to Verify (Pre-Merge)

- `pytest -q tests/components/llm/test_intent_classifier_typesafe.py tests/components/llm/test_intent_classifier.py`
- `pytest -q tests/canvas`
- `git diff --check`

## Out of Scope

- Full note-body transmission, automatic APPLY, removing confirmations, changing default chat generation, or activating Product test/prod channels.

## Related Docs

- `docs/TYPESAFE_SYSTEM_ONE/README.md`
- `docs/CANVAS_CHAT_SURFACE/README.md`
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/README.md`
- `docs/CONCEPTS/TRUST_SEMANTICS_CONTRACT.md :: Rules for writes`
