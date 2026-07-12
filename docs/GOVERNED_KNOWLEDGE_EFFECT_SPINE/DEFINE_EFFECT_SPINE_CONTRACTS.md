---
name: Define Effect Spine Contracts
description: Define ownership and failure semantics for evidence through governed effect.
task_id: GKES-01
source_anchor: docs/contracts/GOVERNED_WRITE_PROTOCOL.md :: Invariants
parent_capability: Governed Knowledge Effect Spine
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Define Effect Spine Contracts

## Purpose

Make one implementation-independent contract for `evidence → candidate → semantic identity → proposal → decision → exact effect → terminal outcome`, before changing runtime preconditions.

## What This Task Does

Assign logical owners, required bindings, idempotency/recovery semantics, and prohibited responsibilities. Resolve semantic-identity ownership from current authoritative docs and code; escalate only if they are genuinely irreconcilable.

## Concretely

Update the relevant GOV, SIP, Heimdal, DRI and test-registry owner docs. State that tokens bind operation, target, scope, payload digest, expiry and idempotency identity; state that operation identity is independent of semantic identity unless implementation proves otherwise.

## Why This Matters

Independent fixes otherwise create incompatible token, receipt, cursor and identity semantics.

## Acceptance Criteria

- [ ] The owner docs define the chain, owners, forbidden calls and partial-failure states without prescribing modules. Verify: doc writeback at `docs/contracts/GOVERNED_WRITE_PROTOCOL.md :: Invariants`.
- [ ] A producer/consumer inventory covers all authority-bearing effects, including orchestrator and eval-capture paths. Verify: doc writeback at `docs/GOVERNED_KNOWLEDGE_EFFECT_SPINE/DEFINE_EFFECT_SPINE_CONTRACTS.md :: What This Task Does`.
- [ ] The invariant registry has production-call-site test commitments for cursor safety, token enforcement, terminal outcome and deterministic rebuild. Verify: doc writeback at `docs/testing/invariant-tests.md`.

## How to Verify (Pre-Merge)

- Review the updated contracts against `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` and `docs/architecture/functional-ontology.md`.
- Run `pytest -q tests/architecture`.

## Out of Scope

Runtime enforcement or migration work.

## Related Docs

- `docs/contracts/GOVERNED_WRITE_PROTOCOL.md`
- `docs/architecture/SBS_FITNESS_RULES.md`

## Related GitHub Issues

Create the first child issue from this specification; it unblocks the two P0 tracks.
