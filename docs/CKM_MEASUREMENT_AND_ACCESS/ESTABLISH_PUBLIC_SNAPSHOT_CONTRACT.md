---
name: Establish Public Snapshot Contract
description: Define rebuild-stable CKM identity, versioned envelopes, atomic state revision, snapshot manifests, missing-state and cursor refusal contracts.
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

- Persist a rebuild-stable public key for every public CKM resource, separate from names/slugs/row IDs.
- Add CKM epoch/state revision metadata and advance revision in the same transaction as every CKM mutation.
- Define transport-neutral resource DTOs, result/error envelopes, snapshot manifest/digest, tagged value states, truncation metadata, canonical query digest, stable total order, cursor payload, and typed compatibility/refusal errors.
- Update mutation producers, schema migration, fixtures, and fail-loud preflight together under the invariant→producers rule.

## Concretely

`CapabilityResource.public_id` survives rebuild and rename. A snapshot manifest binds epoch/revision, schema versions, taxonomy digest, exact watermarks, and provenance. Cursor payloads bind snapshot/query/version/limit/last-key but are not yet exposed as a supported CLI surface until Q1b.

## Why This Matters

Watermarks miss link, confirmation, assessment, and finding mutations. Random row IDs and mutable names cannot be a public contract. A schema without migrated producers or atomic revision advancement would create latent outage and mixed-snapshot risk.

## Acceptance Criteria

- [ ] Seeded and inferred public resource identities are deterministic, survive rebuild, and do not change when display name/slug changes.
  Verify: `tests/builderops/ckm/test_measurement_contract.py::test_public_identity_survives_rebuild_and_rename`
- [ ] Every CKM mutation advances state revision exactly once in the same transaction, including ingestion, linking, confirmation, assessment, findings, rebuild, and migration paths.
  Verify: `tests/builderops/ckm/test_measurement_contract.py::test_all_mutations_advance_state_revision_atomically`
- [ ] Migration/bootstrap/test producers populate the new identity and state metadata; unsupported legacy state fails loudly rather than half-initializing.
  Verify: `tests/builderops/ckm/test_measurement_contract.py::test_identity_revision_migration_updates_every_producer`
- [ ] Result/resource DTOs express projection status, candidate separation, provenance, snapshot binding, explicit truncation, and distinct `measured`/`missing`/`not_applicable`/`unsupported` values.
  Verify: `tests/builderops/ckm/test_measurement_contract.py::test_envelope_missing_states_and_projection_marker`
- [ ] Cursor contracts bind resource, canonical query, snapshot, versions, limit, and last key; cursor payload tampering is detectable.
  Verify: `tests/builderops/ckm/test_measurement_contract.py::test_cursor_contract_binds_query_snapshot_versions`
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

## Related Docs

- `docs/CKM_MEASUREMENT_AND_ACCESS/README.md`
- `docs/audits/CKM_MEASUREMENT_AND_ACCESS_2026-07-14.md`
- `docs/adr/ADR-0057-capability-knowledge-model-kvasir.md`

## Related GitHub Issues

Implementation issue #3776 under validation parent #3775. TCD hint: Sol/high or Terra/high; escalate for unresolved migration, transaction, identity, or compatibility risk.
