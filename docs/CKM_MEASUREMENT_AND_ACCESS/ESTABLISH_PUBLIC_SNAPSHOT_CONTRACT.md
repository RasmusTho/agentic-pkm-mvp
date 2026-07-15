---
name: Establish Public Snapshot Contract
description: Define lifecycle-safe CKM identity, policy-bound envelopes, atomic state revision, complete snapshot manifests, and missing-state refusal contracts.
task_id: CKM-MA-Q1A
source_anchor: docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Accepted architecture decisions
parent_capability: CKM Measurement & Access
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Establish Public Snapshot Contract

## Purpose

Create the durable public semantics that Q1b will execute without exposing mutable row IDs or promising snapshot consistency the runtime cannot prove. This is Q1a; it is independently mergeable but never sufficient to declare Q1 delivered.

## What This Task Does

- Persist a rebuild-stable, non-reused public key for every public CKM resource, separate from names/slugs/row IDs, under accepted rename/delete/split/merge alias or tombstone semantics.
- Add CKM epoch/state revision metadata and advance revision in the same transaction as every CKM mutation.
- Define transport-neutral resource DTOs, result/error envelopes, snapshot manifest/digest, tagged value states, completeness metadata, canonical query digest, stable total order, effective audience/access-policy/redaction fields, and typed compatibility/refusal errors.
- Update mutation producers, schema migration, fixtures, and fail-loud preflight together under the invariant→producers rule.

## Concretely

`CapabilityResource.public_id` survives rebuild and rename, is never reused, and follows the accepted identity-lifecycle policy for deletion, split, and merge. A snapshot manifest binds epoch/revision, schema versions, taxonomy digest, exact watermarks, provenance, effective audience, access-policy version, redaction profile, and a completeness manifest. V1 defines no cursor contract.

## Why This Matters

Watermarks miss link, confirmation, assessment, and finding mutations. Random row IDs and mutable names cannot be a public contract. A schema without migrated producers or atomic revision advancement would create latent outage and mixed-snapshot risk.

## Acceptance Criteria

- [ ] The accepted owner policy defines rename, deletion, split, merge, alias, tombstone, and non-reuse semantics before schema implementation or migration begins.
  Verify: doc writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Pre-implementation owner gates`
- [ ] Seeded and inferred public resource identities are deterministic, survive rebuild/rename, are never reused, and preserve the accepted deletion/split/merge semantics.
  Verify: `tests/builderops/ckm/test_measurement_contract.py::test_public_identity_lifecycle_policy`
- [ ] Every CKM mutation advances state revision exactly once in the same transaction, including ingestion, linking, confirmation, assessment, findings, rebuild, and migration paths.
  Verify: `tests/builderops/ckm/test_measurement_contract.py::test_all_mutations_advance_state_revision_atomically`
- [ ] Migration/bootstrap/test producers populate the new identity and state metadata; unsupported legacy state fails loudly rather than half-initializing.
  Verify: `tests/builderops/ckm/test_measurement_contract.py::test_identity_revision_migration_updates_every_producer`
- [ ] Result/resource DTOs express projection status, candidate separation, provenance, snapshot binding, effective audience/access-policy/redaction metadata, completeness accounting, and distinct `measured`/`missing`/`unassessed`/`unsupported` values.
  Verify: `tests/builderops/ckm/test_measurement_contract.py::test_envelope_missing_states_and_projection_marker`
- [ ] Snapshot manifests distinguish included, filtered, omitted, and truncated object classes; incomplete or policy-ambiguous captures cannot claim completeness.
  Verify: `tests/builderops/ckm/test_measurement_contract.py::test_snapshot_manifest_accounts_for_complete_scope`
- [ ] Unknown schemas/versions/resources/filters/historical semantics produce typed transport-neutral errors with no fallback.
  Verify: `tests/builderops/ckm/test_measurement_contract.py::test_unsupported_versions_and_semantics_are_typed`
- [ ] The governing spec records Q1a as schema/state groundwork and keeps Q1 acceptance blocked on Q1b.
  Verify: doc writeback at `docs/CKM_MEASUREMENT_AND_ACCESS/README.md :: Implementation tasks`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/builderops/ckm/test_measurement_contract.py`
- `python3 -m pytest -q tests/builderops/ckm`
- `ruff check app tests`
- `mypy app`
- Run migration from a pre-Q1 fixture and verify no producer leaves missing identity/revision state.

## Out of Scope

- Supported query execution or CLI JSON; Q1b owns the working read path.
- Rich filters, indexes, query-plan optimization, metrics, or observation.
- General history, as-of reconstruction, rankings, gates, drift, automation, or federation.
- Pagination/cursors; they require later size evidence, retained immutable snapshots, and an accepted retention policy.

## Related Docs

- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`

## Related GitHub Issues

Implementation issue #3776 under validation parent #3775. It remains blocked until every owner gate is accepted and the Issue is reconciled to this contract. TCD hint: Sol/high or Terra/high; escalate for unresolved migration, transaction, identity, access-policy, or compatibility risk.
