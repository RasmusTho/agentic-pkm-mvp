---
name: Define Carrier-Neutral Delivery Contracts
description: Define immutable initiation, plan, reducer, and receipt contracts without choosing a durable intent carrier prematurely.
task_id: DDO-02
github_issue: 4165
source_anchor: docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Full capability
parent_capability: Deterministic Delivery Orchestration
prerequisites: []
depends_on: []
can_parallelize_with: [Run Independent Issues Through a Fast Lane]
---

# Define Carrier-Neutral Delivery Contracts

## Purpose

Create the stable seam that lets the compiler, reducer, BuilderOps substrate, and CKM evolve
independently.

## What This Task Does

- Defines versioned schemas for `DeliveryInitiation.v1`, `DeliveryPlan.v1`, reducer events/effects,
  structured worker/review results, and `DeliveryReceipt.v1`.
- Keeps `DeliveryInitiation.v1` carrier-neutral while the live PromotionIntent semantics and the
  cost of a separate DeliveryIntent record are evaluated.
- Defines immutable approval evidence, requested/final scope, exclusions, contract hashes,
  dependency waves, policy profile, concurrency/budget, effect allowlist, and provenance.
- Defines receipt metrics and typed terminal/exception outcomes.
- Records the owner and reversal condition for a later durable carrier decision.

## Concretely

The same canonical `DeliveryInitiation.v1` bytes produce the same content hash independent of
whether they are carried by a future DeliveryIntent record, a semantically valid PromotionIntent
extension, or a bounded CLI approval envelope. The schema contains no CKM-renderer or provider
fields.

## Why This Matters

Choosing storage or a UI before the semantic contract would couple unrelated reasons to change and
make the fast lane wait for the full control surface.

## Acceptance Criteria

- [ ] All five contracts have canonical serialization, versioning, strict validation, and stable
  hashes.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_contracts_round_trip_canonically`.
- [ ] Initiation records immutable approval evidence, exact requested scope, policy profile, budget,
  and source authority without granting effects itself.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_initiation_is_evidence_not_execution_authority`.
- [ ] Plan contract binds live input identities/hashes, exclusions, waves, expected states, and
  allowed effect classes.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_plan_binds_scope_and_expected_authority`.
- [ ] Receipt contract carries per-Issue proof, exact heads/merge identity, review disposition,
  known defects, exceptions, recovery history, and TCD metrics.
  - Verify: `tests/builderops/test_delivery_orchestration_contracts.py::test_receipt_preserves_delivery_and_tcd_evidence`.
- [ ] Schemas contain no CKM-renderer, model-provider, or static-cockpit coupling.
  - Verify: `tests/architecture/test_sbs_fitness_rules.py::test_delivery_contracts_are_carrier_and_provider_neutral`.
- [ ] The durable carrier decision is documented as a later semantic/governance gate rather than
  silently resolved by schema shape.
  - Verify: doc anchor `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md :: Architecture modules`.

## How to Verify (Pre-Merge)

- Run the four focused contract tests and the architecture fitness target.
- Run `ruff check app tests`.
- Run `mypy app`.
- Run `git diff --check`.

## Out of Scope

- Persisting or executing an initiation.
- Compiling GitHub scope.
- Choosing PromotionIntent or DeliveryIntent as the durable carrier.
- CKM UI changes.

## Related Docs

- `docs/DETERMINISTIC_DELIVERY_ORCHESTRATION/README.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/CAPABILITY_KNOWLEDGE_MODEL/README.md`

## Related GitHub Issues

Live task: [#4165](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4165). It is one of two
initial ready slices and may run in parallel with DDO-01 (#4164).
