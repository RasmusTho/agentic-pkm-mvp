---
name: Define Profile Authority And Persistence
description: Establish the durable governed vault-profile authority, state, version, and receipt contract.
task_id: GOVPROF-01
github_issue: 4945
source_anchor: "docs/YOUTUBE_SOURCE_NOTE_V2/README.md :: D4 — resolved direction 2026-07-25"
parent_capability: Governed Vault Profile
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Define Profile Authority And Persistence

## Purpose

Make the future Profile Note and ProfileAgent authority boundary executable without implementing it yet. This first slice defines durable records, version/receipt joins, owner-correction precedence, and restart/partial-failure behavior needed by later proposal and consumer work.

## What This Task Does

Add the smallest runtime contract, schema/migration, and production-path tests that define one vault-local owner-visible Profile Note, ProfileAgent as its only approved-content writer, durable candidate/proposal/confirmation/write/receipt identities, and a version that becomes consumable only after a completed governed receipt. Direct owner corrections remain a separately attributable, higher-precedence authority source.

## Concretely

`pytest -q tests/governance/test_governed_vault_profile_contract.py` proves the production contract refuses any approved-content writer other than ProfileAgent and does not expose a version without its terminal receipt.

## Why This Matters

Without a durable authority and recovery substrate, a later proposal or consumer could mistake inference, stale state, or a partial write for owner-approved profile knowledge.

## Acceptance Criteria

- [ ] One Profile Note and ProfileAgent-only approved-content writer are defined on the production contract path, with direct owner-correction precedence explicit.
  - Verify: `tests/governance/test_governed_vault_profile_contract.py::test_only_profile_agent_can_write_approved_profile_content`
- [ ] Candidate, proposal, confirmation, write, receipt, and profile version identities are durable and joinable; only a completed receipt-bound version is consumable.
  - Verify: `tests/governance/test_governed_vault_profile_contract.py::test_profile_version_requires_completed_receipt_binding`
- [ ] Restart and partial-write failure preserve truthful non-terminal state and cannot synthesize owner approval or overwrite a direct owner correction.
  - Verify: `tests/governance/test_governed_vault_profile_contract.py::test_restart_and_partial_write_preserve_owner_precedence_without_false_approval`

## How to Verify (Pre-Merge)

- `pytest -q tests/governance/test_governed_vault_profile_contract.py`
- Run migration/schema checks required by the selected durable store.

## Out of Scope

- Candidate admission, Panel rendering/confirmation, external egress, and consumer projection.

## Restart / Durability Posture

All state required to distinguish pending, failed, approved, and consumable versions is durable. After restart, incomplete work remains visibly non-terminal; no profile is consumable unless its durable receipt binding is complete.

## Related Docs

- `docs/GOVERNED_VAULT_PROFILE/README.md`
- `docs/PANEL_AGENT.md :: Canonical confirmation semantics`

## Related GitHub Issues

Parent: #4944
