---
name: Define Cloud Secret Provisioning Specification
description: Publish the BWS capability contract, bounded task breakdown, and issue traceability.
task_id: BWS-00
github_issue: 5682
source_anchor: docs/CLOUD_SECRET_PROVISIONING/README.md :: Outcome
parent_capability: CLOUD_SECRET_PROVISIONING
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Define Cloud Secret Provisioning Specification

## Purpose

The BWS Linux target spans host lookup, secret administration, token installation, and PostgreSQL deployment. A capability contract and bounded child issue set are required before implementation pickup.

## What This Task Does

Publish the capability specification, four independently verifiable implementation task specs, parent validation-hub map, and canonical document-index entries. Create the child GitHub issues from the task specs while this specification PR is open, record each child issue number in its task frontmatter, and leave implementation issues dependency-blocked until the spec PR merges.

The specification records the accepted BWS topology, preserves the Mac Keychain path, and defines durable shared-import history with fail-closed indeterminate provider outcomes, one host-local coordination lock whose sole-writer boundary requires owner qualification or shared fencing, the locked empty-database bootstrap transition, atomic systemd-token generation identity with durable remote terminal receipts, and a VM-supervised deploy worker with durable remote stages, quiescent SSH-loss recovery, and terminal receipts. It also defines the closed PostgreSQL file-consumer map, no-value-disclosure, and live-qualification boundaries without claiming runtime delivery.

## Concretely

BWS-01 through BWS-04 have one durable task file and one GitHub Issue each. The parent #5667 links the specification and child issues. The spec PR closes only the spec-delivery issue; the parent validation hub and implementation children remain open.

## Why This Matters

Without a capability contract, implementation slices can disagree on channel isolation, secret-value disclosure, or partial-failure behavior. Without task-file and issue-number traceability, later agents cannot reconstruct which contract governs each slice.

## Acceptance Criteria

- [ ] The capability README defines the accepted BWS target, task order, cross-task invariants, acceptance path, and separation between repository behavior and live qualification.
  - Verify: doc writeback at `docs/CLOUD_SECRET_PROVISIONING/README.md :: Outcome`
- [ ] Each BWS-01 through BWS-04 task file contains bounded scope, acceptance criteria, pre-merge verification, and its filed GitHub issue number.
  - Verify: `docs/CLOUD_SECRET_PROVISIONING/RESOLVE_BWS_CHANNEL_SECRETS.md :: github_issue`
  - Verify: `docs/CLOUD_SECRET_PROVISIONING/ADMINISTER_SECRETS_VALUE_FREE.md :: github_issue`
  - Verify: `docs/CLOUD_SECRET_PROVISIONING/INSTALL_VM_SECRET_TOKENS.md :: github_issue`
  - Verify: `docs/CLOUD_SECRET_PROVISIONING/DEPLOY_POSTGRES_WITH_COMPOSE_SECRETS.md :: github_issue`
- [ ] The parent validation-hub contract maps BWS-01 through BWS-04 to #5677 through #5680 in dependency order and does not make the parent pickup work.
  - Verify: `docs/CLOUD_SECRET_PROVISIONING/PARENT_FEATURE_ISSUE.md :: Child tasks`
- [ ] The document index lists the README, parent contract, spec-delivery task, and all four implementation task files.
  - Verify: `docs/DOCS_INDEX.md :: v6.0 Capability Specifications`

## How to Verify (Pre-Merge)

Run python3 scripts/docs_guard.py and git diff --check. Run python3 scripts/validate_issue_readiness.py --body-file <child-body> --label agent:ready for each implementation Issue body before any Ready label transition. Verify that each filed child remains blocked while the specification PR is open, and that this PR closes only the spec-delivery issue.

## Out of Scope

- Implementing BWS provider code, administration commands, token delivery, or Compose secret wiring.
- Live BWS account, project, machine-account, or VM operations.
- Production raw-store-key or archive-pass rotation and deletion.

## Related Docs

- docs/CLOUD_SECRET_PROVISIONING/README.md
- docs/CLOUD_SECRET_PROVISIONING/PARENT_FEATURE_ISSUE.md
- docs/DOCS_INDEX.md
- .codex/skills/feature-breakdown/SKILL.md
- .codex/skills/publish-pr/SKILL.md

## Related GitHub Issues

- Parent validation hub: #5667
- Implementation slices: #5677, #5678, #5679, #5680
- This spec-delivery Issue is closed by the specification PR after its merge.
