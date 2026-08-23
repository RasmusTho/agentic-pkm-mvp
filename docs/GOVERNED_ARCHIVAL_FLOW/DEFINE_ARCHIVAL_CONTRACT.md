---
name: Define Governed Archival Contract
description: Define the type-neutral identity, representation, policy, receipt, liveness, and adapter contract without creating a central archive authority
task_id: GAF-01
github_issue: 5063
source_anchor: "docs/GOVERNED_ARCHIVAL_FLOW/README.md :: Capability Boundary"
parent_capability: GOVERNED_ARCHIVAL_FLOW
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Define Governed Archival Contract

## Purpose

Turn the accepted architecture boundary into one executable vocabulary that adapters can implement
without sharing an artifact ontology, database, retention policy, or access policy.

## What This Task Does

- Add `docs/contracts/GOVERNED_ARCHIVAL_FLOW.md` as the target owner contract, subordinate to HKA,
  SIP, GOV, PDM, DRI, and class-specific owner docs.
- Add provider-free typed values and protocols under `app/archival/` for artifact identity,
  representation identity, authority owner, durability/derivation class, generation, policy profile,
  transition stage, typed liveness, and redacted receipts.
- Define one public adapter protocol for enumerate/resolve, authorize read, immutable pre-effect
  operation binding and readback, reserve/copy/verify/receipt/activate/retire/complete, exact
  restore and receipt readback, all-representation cleanup proof, and doctor/reconcile.
- Add ARCHIVE-MUST/GATE/DOCTOR entries to the existing invariant registry; do not create a second
  registry.
- Encode that location is never identity and that class-specific owner state remains authoritative.

## Concretely

```bash
pytest -q tests/archival/test_contracts.py
pytest -q tests/architecture/test_governed_archival_contract.py
```

No production producer imports the new service in this task. The result is an enabling contract and
testable adapter surface.

## Why This Matters

Without a narrow common contract, later adapters either copy Heimdal's raw-audio policy into every
artifact type or create another central registry that competes with HKA/PDM/GOV/SIP authority.

## Acceptance Criteria

- [ ] The contract represents source/human/derived/receipt classes, durable/ephemeral/rebuildable
      posture, owner authority, identity, generation, provenance, and representation without
      deriving any of them from a path.
      Verify: `tests/archival/test_contracts.py::test_artifact_classification_preserves_authority_and_durability_axes`
- [ ] Adapter and receipt types carry opaque representation refs and reject path text as identity or
      access authority.
      Verify: `tests/archival/test_contracts.py::test_location_cannot_mint_identity_or_access_authority`
- [ ] The transition kernel consumes only the published `ArchivalAdapter`; the contract carries
      immutable operation binding, owner-native readback, exact restore, and cleanup-proof types
      without adding a kernel registry, lock, content store, or artifact/policy authority.
      Verify: `tests/architecture/test_governed_archival_contract.py::test_transition_kernel_uses_only_published_archival_adapter`
      Verify: `tests/architecture/test_governed_archival_contract.py::test_transition_kernel_has_no_private_persistence_or_content_store`
- [ ] Policy profiles distinguish raw evidence, retained source, HKA recovery, and rebuildable
      derivative outcomes rather than exposing one universal delete rule.
      Verify: `tests/archival/test_contracts.py::test_policy_profiles_keep_class_specific_terminal_outcomes`
- [ ] The architecture test proves the common contract names HKA/SIP/GOV/PDM/DRI ownership and
      forbids a central archive authority/store.
      Verify: `tests/architecture/test_governed_archival_contract.py::test_contract_preserves_sbs_ownership_and_forbids_central_registry`
- [ ] The normative contract and invariant registry contain the promoted MUST/GATE/DOCTOR kernel.
      Verify: `tests/architecture/test_governed_archival_contract.py::test_normative_contract_and_invariant_registry_match`
      Verify: doc writeback at `docs/testing/invariant-tests.md :: Governed archival flow`

## How to Verify (Pre-Merge)

1. `pytest -q tests/archival/test_contracts.py`
2. `pytest -q tests/architecture/test_governed_archival_contract.py`
3. `python3 scripts/validate_issue_readiness.py --body-file <GAF-01-issue-body> --label agent:ready`
4. `ruff check app/archival tests/archival tests/architecture/test_governed_archival_contract.py`

## Out of Scope

- Runtime orchestration, persistence migration, backend selection, production adapter wiring, or
  artifact-class retention changes.
- A generic archive table, content store, cloud provider, or universal artifact ID.

## Related Docs

- `docs/GOVERNED_ARCHIVAL_FLOW/README.md`
- `docs/audits/GOVERNED_ARCHIVAL_FLOW_2026-08-22.md`
- `docs/architecture/ARTIFACT_CLASSIFICATION_AND_LIFECYCLE.md`
- `docs/contracts/ARTIFACT_CONTRACT.md`
- `docs/contracts/STORE_PORT.md`
- `docs/testing/invariant-tests.md`

## Related GitHub Issues

One bounded implementation Issue. Execution context: `fresh_issue_agent`; helper budget `0`.
TCD hint: Terra / high because the output is architecture-bearing but locally contract-testable.
