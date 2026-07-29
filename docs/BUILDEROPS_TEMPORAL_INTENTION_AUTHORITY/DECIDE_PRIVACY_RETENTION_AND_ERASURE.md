---
name: Decide Privacy Retention And Erasure Authority
description: Produce the separate owner decision required before any content, identifiers, retention, or erasure implementation can be specified.
task_id: TIA-02
github_issue: 4377
source_anchor: docs/adr/ADR-0065-builderops-temporal-intention-authority.md :: D7 — Deferred capabilities require separate gates
parent_capability: BuilderOps Temporal Intention Authority
prerequisites: []
depends_on: []
can_parallelize_with: []
recommended_capability: "Codex Sol / high–xhigh plus explicit owner decision"
capability_rationale: "Privacy, retention, deletion, and identifier authority have high irreversible and data-governance cost."
---

# Decide Privacy, Retention, And Erasure Authority

## Purpose

Resolve the policy questions that ADR-0065 deliberately leaves undecided before any content-bearing
field, raw or derived identifier, retention rule, key material, or physical-erasure mechanism is
specified or implemented.

## What This Task Does

- Produces an owner-decision brief covering data classes, permitted purposes, scope, retention,
  backup treatment, deletion/erasure meaning, receipt immutability, identifier/linkability policy,
  key custody, and audit evidence.
- Records the accepted decision in an ADR and updates the minimum owner docs and indexes.
- States which later tasks become authorized, remain prohibited, or need a narrower additional
  decision.

## Concretely

This is a governance/docs decision lane, not implementation. Until the owner accepts the decision
and its PR merges, the first slice stays content-free and TIA-03, applicable TIA-04 scope, and
TIA-06 remain blocked.

## Why This Matters

Retention and deletion cannot be inferred safely after sensitive or linkable data has already been
made durable in records, receipts, outbox payloads, logs, metrics, backups, or projections.

## Acceptance Criteria

- [ ] A standalone owner-decision brief presents one recommendation and the genuine authority
  forks for content classes, identifiers/derivatives, retention, backup handling, receipt
  preservation, erasure meaning, and key custody.
  - Verify: `runtime receipt: temporal_intention_privacy_decision_brief.v1`
- [ ] The accepted decision is recorded in a repo ADR that explicitly states authorized,
  prohibited, and still-undecided data and lifecycle behavior.
  - Verify: doc writeback at `docs/adr/INDEX.md :: Accepted`
- [ ] The decision reconciles ADR-0065 and the BuilderOps object model without weakening the
  opaque-first first slice.
  - Verify: doc writeback at `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md :: Gated target-state boundary: temporal-intention lifecycle evidence`
- [ ] No implementation Issue depending on this decision becomes ready before the ADR PR is merged
  and the parent hub links the accepted owner decision and merge SHA.
  - Verify: `runtime receipt: temporal_intention_privacy_decision_acceptance.v1`

## How to Verify (Pre-Merge)

- Run docs governance and source-anchor validation.
- Verify the ADR index and DOCS_INDEX entries.
- Verify the live parent and dependent child labels remain truthful.

## Out of Scope

- Implementing content capture, identifiers, retention jobs, deletion, erasure, or key management.
- Relaxing the content-free contract before the decision is accepted.
- Choosing collector, sync, migration, or UI architecture except where a privacy constraint is
  necessary input to a later decision.

## Related Docs

- `docs/adr/ADR-0065-builderops-temporal-intention-authority.md`
- `docs/audits/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY_2026-07-29.md`
- `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`
- `docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/README.md`

## Related GitHub Issues

- Live task: [#4377](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4377).
