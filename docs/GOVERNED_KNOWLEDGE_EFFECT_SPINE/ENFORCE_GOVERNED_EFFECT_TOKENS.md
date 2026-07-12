---
name: Enforce Governed Effect Tokens
description: Require exact GOV authorization before every authority-bearing effect.
task_id: GKES-05
source_anchor: docs/contracts/GOVERNED_WRITE_PROTOCOL.md :: Invariants
parent_capability: Governed Knowledge Effect Spine
prerequisites: [GKES-01]
depends_on: [DEFINE_EFFECT_SPINE_CONTRACTS.md]
can_parallelize_with: [MAKE_HEIMDAL_INTAKE_DURABLE]
---

# Enforce Governed Effect Tokens

## Purpose

Close the CAO→GOV→EXE bypass: effects must be authorized by GOV and bound to their exact intended operation.

## What This Task Does

Inventory every authority-bearing effect producer, including orchestrator vault append and eval-capture. Require a DecisionToken bound to principal, scope, operation, target, payload digest, expiry and idempotency key; reject mismatches at the production execution seam.

## Concretely

Build the owned authority contract on existing token/receipt primitives where adequate. Migrate every producer, bootstrap path and fixture in the same change, with a fail-loud preflight.

## Why This Matters

An unauthorised durable mutation is a high-blast-radius integrity failure; a partial migration is an outage risk.

## Acceptance Criteria

- [ ] The orchestrator cannot append to a vault with `decision_token=None`. Verify: `tests/orchestrator/test_executor.py::test_orchestrator_rejects_vault_append_without_decision_token`.
- [ ] Tokens mismatched to scope, operation, target or payload are rejected at the production effect call site. Verify: `tests/execution/test_execution_request.py::test_execution_rejects_mismatched_decision_token_binding`.
- [ ] Every inventoried authority-bearing producer, including eval-capture, either supplies a valid token or fails loud. Verify: `tests/architecture/test_governed_effect_producers.py::test_all_authority_bearing_effect_producers_require_decision_token`.
- [ ] Producer migrations, fixtures and preflight are complete. Verify: `tests/architecture/test_governed_effect_producers.py::test_governed_effect_preflight_covers_all_producers`.

## How to Verify (Pre-Merge)

- `pytest -q tests/orchestrator/test_executor.py tests/execution/test_execution_request.py tests/architecture/test_governed_effect_producers.py`
- `ruff check app tests`

## Out of Scope

New policy strategy, UI confirmation redesign, or non-authority-bearing projections.

## Related Docs

- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`
- `docs/architecture/SBS_FITNESS_RULES.md`

## Related GitHub Issues

Blocked by GKES-01; unblocks GKES-06.
