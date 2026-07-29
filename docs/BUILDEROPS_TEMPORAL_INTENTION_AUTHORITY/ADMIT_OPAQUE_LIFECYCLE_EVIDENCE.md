---
name: Admit Opaque Temporal-Intention Lifecycle Evidence
description: Admit a content-free temporal-intention record through the canonical BuilderOps PostgreSQL transaction.
task_id: TIA-01
github_issue: 4376
source_anchor: docs/adr/ADR-0065-builderops-temporal-intention-authority.md :: D8 — Delivery sequencing
parent_capability: BuilderOps Temporal Intention Authority
prerequisites: [BCP-06]
depends_on: []
can_parallelize_with: []
recommended_capability: "Codex Sol / high–xhigh"
capability_rationale: "PostgreSQL authority, concurrency, idempotency, receipt lineage, and a lifecycle state machine make this a high-risk data slice."
---

# Admit Opaque Temporal-Intention Lifecycle Evidence

## Purpose

Implement the first and only currently specified runtime slice: registry-backed, content-free
temporal-intention lifecycle evidence admitted through the canonical BuilderOps transaction after
BCP-06 proves the PostgreSQL writer.

## What This Task Does

- Registers one non-content-bearing BuilderOps record type and its closed schema.
- Defines the exact mapping from that record to the ADR-0062 PostgreSQL authority envelope.
- Atomically creates or replays one server-validated stable opaque identity under one idempotency
  identity.
- Commits guarded lifecycle state, append-only receipt lineage, and existing outbox intent in the
  delivered transaction kernel.
- Admits only `done`, `ignore`, and `never_show_again`, with receipt-backed expiry/reversal outcomes
  defined by ADR-0065.
- Builds one read-only, non-authoritative projection that can be deleted and rebuilt.

## Concretely

An authenticated request containing only the permitted envelope and semantic fields reaches the
production BuilderOps API. Equal concurrent or repeated requests return the original opaque
identity and receipt lineage. Conflicting reuse fails without partial state. Projection replay
dedupes by canonical opaque identity plus receipt lineage.

## Why This Matters

This is the smallest slice that turns the approved semantics into one durable authority without
creating an interim writer or collecting sensitive source material before policy exists.

## Acceptance Criteria

- [ ] Production admission is unavailable until live BCP-06 cutover proof exists; a test adapter or
  schema alone cannot satisfy the gate.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_admission.py::test_production_admission_requires_proven_bcp06_cutover`
- [ ] The registry record has an explicit, closed mapping to registry type, mandatory PostgreSQL
  authority-envelope fields, state payload, idempotency identity, lifecycle receipt event, and
  projection/outbox identity.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_contract.py::test_record_shape_maps_exactly_to_postgres_authority_envelope`
- [ ] Concurrent equal admissions create one stable opaque identity and one logical initial
  lifecycle effect, returning the same committed result to every caller.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_admission.py::test_concurrent_equal_admission_creates_one_opaque_identity`
- [ ] Equal replay returns the original identity and receipt lineage, while conflicting idempotency
  reuse fails closed without state, receipt, or outbox mutation.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_admission.py::test_equal_replay_returns_original_and_conflict_is_atomic`
- [ ] Guarded state, idempotent result, append-only lifecycle receipt, and outbox intent commit in
  one existing BuilderOps transaction, and pre-commit fault injection exposes none of them.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_admission.py::test_state_receipt_idempotency_and_outbox_are_one_transaction`
- [ ] Clients can admit only `done`, `ignore`, and `never_show_again`; allowed expiry or explicit
  reversal appends the defined receipt and reduces to `active` with no current disposition without
  rewriting prior lineage.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_lifecycle.py::test_closed_dispositions_and_receipt_backed_reversal`
- [ ] Every record, receipt, idempotent result, outbox payload, log, metric label, backup-visible
  value, and projection rejects prompts, summaries, free text, raw paths, raw underlying
  identifiers, fingerprints, deterministic source derivatives, HMAC material, and unknown fields.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_privacy_boundary.py::test_content_and_unknown_fields_fail_closed_across_all_surfaces`
- [ ] The projection is read-only and rebuildable; replay and full rebuild dedupe by canonical
  opaque identity plus receipt lineage and cannot cause admission or a lifecycle transition.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_projection.py::test_rebuild_dedupes_without_authority_side_effects`
- [ ] Receipt lineage survives response loss, replay, expiry/reversal, and projection rebuild
  without mutation or orphaned causal references.
  - Verify: `tests/builderops/control_plane/test_temporal_intention_lifecycle.py::test_receipt_lineage_is_append_only_and_causally_complete`

## How to Verify (Pre-Merge)

- Run the named PostgreSQL integration, concurrency, replay, privacy-boundary, lifecycle, and
  projection tests.
- Run the existing BuilderOps transaction-kernel and outbox regression tests.
- Run repository lint and type checks required for the touched implementation paths.
- Run the data/concurrency/state-machine review-before-CI convergence gate.

## Out of Scope

- Collectors, prompt or summary capture, raw sources or identifiers, fingerprints, HMACs, and
  mapping stores.
- Cross-host synchronization outside the selected authenticated BuilderOps API.
- Historical migration or compatibility writers.
- Cockpit, UI, or Product runtime projections.
- Retention enforcement, physical erasure, crypto-shredding, or key custody.
- Automatic inference of dispositions or reversals.

## Related Docs

- `docs/adr/ADR-0065-builderops-temporal-intention-authority.md`
- `docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md`
- `docs/BUILDEROPS_CONTROL_PLANE/POSTGRES_TRANSACTION_KERNEL.md`
- `docs/builderops/BUILDEROPS_VAULT_OBJECT_MODEL.md`
- `docs/BUILDEROPS_TEMPORAL_INTENTION_AUTHORITY/README.md`

## Related GitHub Issues

- BCP-06 gate: [#3793](https://github.com/RasmusTho/agentic-pkm-mvp/issues/3793).
- Live task: [#4376](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4376).
