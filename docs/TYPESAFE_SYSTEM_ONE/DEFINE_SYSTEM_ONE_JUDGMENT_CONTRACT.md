---
name: Define System One Judgment Contract
description: Add a bounded, provider-neutral typed judgment contract for System One requests and answers.
task_id: TSO-01
github_issue: 5765
source_anchor: docs/TYPESAFE_SYSTEM_ONE/README.md :: Capability Contract
parent_capability: TYPESAFE_SYSTEM_ONE
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Define System One Judgment Contract

## Purpose

Product MARR and Builder adapters need the same typed meaning for `Choice`, `Score`, and `Noul` without sharing route policy or provider credentials. This slice adds only the neutral contract and validation seam.

## What This Task Does

- Define bounded request state and named question types in `llm_contract`.
- Define answer types that preserve choice/score/noul values, probabilities, confidence, and returned provider/model provenance.
- Reject unknown question/answer fields, duplicate IDs, non-finite numbers, invalid probability maps, oversized state, and answer/question mismatches.
- Keep the contract side-effect free and provider-neutral; it does not invoke TypeSafe or select routes.

## Concretely

A request contains one bounded state object and a finite set of typed questions. The response must contain exactly the matching answer IDs and answer type for each question. Invalid or partial responses fail closed.

## Why This Matters

Without a neutral contract, Product and Builder could interpret confidence, missing answers, or question meaning differently and accidentally couple their authority boundaries.

## Acceptance Criteria

- [ ] Typed judgment requests and `Choice`/`Score`/`Noul` answers round-trip with strict validation and explicit limits. Verify: `tests/llm_contract/test_system_one_judgment.py::test_judgment_contract_round_trips_typed_answers`.
- [ ] Unknown IDs, answer-type mismatch, invalid probability sums, non-finite values, and size-limit violations fail closed. Verify: `tests/llm_contract/test_system_one_judgment.py::test_invalid_judgment_payloads_are_rejected`.
- [ ] The neutral contract contains no Product/Builder route selection, credentials, retry, or mutation behavior. Verify: `tests/architecture/test_import_boundary.py::test_system_one_contract_is_policy_and_provider_neutral`.

## How to Verify (Pre-Merge)

- `pytest -q tests/llm_contract/test_system_one_judgment.py`
- `pytest -q tests/architecture/test_import_boundary.py::test_system_one_contract_is_policy_and_provider_neutral`
- `git diff --check`

## Out of Scope

- TypeSafe SDK dependency, credentials, provider requests, MARR endpoint, consumer integration, or live inference.

## Related Docs

- `docs/TYPESAFE_SYSTEM_ONE/README.md`
- `docs/CAPABILITY_CONTRACT_MODEL.md :: Standard capability contract shape`
- `docs/adr/ADR-0063-shared-llm-contract-kernel.md`
