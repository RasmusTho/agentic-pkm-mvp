---
name: Govern Profile Update Proposals And Confirmed Writes
description: Admit profile candidates as visible proposals and perform ProfileAgent-only confirmed writes.
task_id: GOVPROF-02
github_issue: 4946
source_anchor: "docs/PANEL_AGENT.md :: Canonical confirmation semantics"
parent_capability: Governed Vault Profile
prerequisites: [GOVPROF-01]
depends_on: [DEFINE_PROFILE_AUTHORITY_AND_PERSISTENCE.md]
can_parallelize_with: []
---

# Govern Profile Update Proposals And Confirmed Writes

## Purpose

Implement the governed transition from provenance-bearing candidate data to a visible, owner-confirmed ProfileAgent write using GOVPROF-01's durable contract.

## What This Task Does

Admit only valid `ProfileUpdateCandidate` data through the inspectable handoff boundary. ProfileAgent evaluates it and creates a distinct unchecked proposal immediately after the Profile Note frontmatter/title. A checked task item enters the governed confirmation path; a separate later pass performs the approved-content write only after policy, WriteGuard, idempotency, and receipt checks.

## Concretely

`pytest -q tests/governance/test_governed_vault_profile_proposals.py` proves candidates never enter the profile or consumer context directly, a newly created proposal cannot write in the same pass, and confirmed writes bind the candidate/proposal/confirmation/version/receipt chain.

## Why This Matters

The system may reason about owner preferences but cannot silently convert that inference into durable authority.

## Acceptance Criteria

- [ ] A `ProfileUpdateCandidate` is treated as inspectable data, not instruction or approval, and invalid/pending candidates cannot enter profile or consumer context.
  - Verify: `tests/governance/test_governed_vault_profile_proposals.py::test_candidate_admission_never_authorizes_profile_or_consumer_context`
- [ ] ProfileAgent creates a visible, distinguishable, initially unchecked proposal after the Profile Note frontmatter/title with proposed change, provenance, and uncertainty.
  - Verify: `tests/governance/test_governed_vault_profile_proposals.py::test_profile_proposal_is_visible_unchecked_and_positioned_before_content`
- [ ] Proposal creation and approved-content writing are separate passes; only a confirmed governed write emits the terminal version-bound receipt.
  - Verify: `tests/governance/test_governed_vault_profile_proposals.py::test_confirmed_write_is_separate_and_receipt_bound`

## How to Verify (Pre-Merge)

- `pytest -q tests/governance/test_governed_vault_profile_proposals.py`
- Run the focused ProfileAgent/Panel integration-equivalent test against the production confirmation call site.

## Out of Scope

- Designing a generic Panel feature, changing unrelated Panel actions, direct owner-content import, or consumer projection.

## Restart / Durability Posture

Pending proposals and confirmations recover only from GOVPROF-01 durable records. Replay is idempotent and cannot write an unconfirmed or superseded proposal; a write failure remains visible and non-consumable.

## Related Docs

- `docs/GOVERNED_VAULT_PROFILE/README.md`
- `docs/PANEL_AGENT.md :: Option B — Proposal generator + executor split (accepted decision)`
- `docs/AGENT-FLOWS.md :: Handoff artifacts and agent-to-agent continuity`

## Related GitHub Issues

Parent: #4944
