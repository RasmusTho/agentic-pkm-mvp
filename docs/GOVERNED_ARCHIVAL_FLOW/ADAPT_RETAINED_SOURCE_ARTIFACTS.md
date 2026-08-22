---
name: Adapt Retained Source Artifacts
description: Add an explicit-admission adapter for curated retained sources and media originals with stable identity, portable representation, gated restore, and policy-specific retirement
task_id: GAF-04
github_issue: 5066
source_anchor: "docs/GOVERNED_ARCHIVAL_FLOW/README.md :: Artifact-Class Posture"
parent_capability: GOVERNED_ARCHIVAL_FLOW
prerequisites: [GAF-02, GAF-03]
depends_on: [IMPLEMENT_VERIFIED_TRANSITION_KERNEL.md, ADAPT_HEIMDAL_RAW_MEDIA.md]
can_parallelize_with: [Adapt Human Artifact Recovery, Govern Rebuildable Derivatives]
---

# Adapt Retained Source Artifacts

## Purpose

Support source-rich material the user explicitly keeps for citation/re-reading without treating
pre-curation ingest, raw sensor evidence, or arbitrary files as retained artifacts.

## What This Task Does

- Implement an explicit-admission retained-source adapter under `app.archival.adapters`, using
  owner-provided identity/provenance and a PDM `StorePort` binding rather than directory scanning.
- Support one representative binary media original and one document/PDF fixture through archive,
  gated restore, verification, and policy-specific retire/delete behavior.
- Preserve content identity, origin/source role, retention policy version, representation format,
  and opaque backend reference in owner-native durable metadata/receipts.
- Require an explicit retention-surface admission/keep decision; `external_raw` staging and a bare
  `source_file` path are not admission authority.
- Keep automatic raw-evidence TTL and consent erasure out of this adapter. Early delete or legal
  retention changes require the retained-source owner policy and receipt.

## Concretely

```bash
pytest -q tests/archival/test_retained_source_adapter.py
```

The test provides an explicit artifact descriptor and authorized StorePort test binding. The adapter
never scans the filesystem or serializes an absolute source path into a durable receipt.

## Why This Matters

Media originals, PDFs, contracts, and other curated sources are durable, but their retention meaning
is not the same as Heimdal's raw-evidence TTL. This adapter proves reuse without policy collapse.

## Acceptance Criteria

- [ ] Explicitly admitted retained media/document sources preserve stable artifact/content identity,
      origin provenance, policy version, and portable format across archive and restore.
      Verify: `tests/archival/test_retained_source_adapter.py::test_retained_source_round_trip_preserves_identity_and_provenance`
- [ ] Pre-curation `external_raw`, a bare filesystem path, or a media companion note cannot authorize
      retained-source archival.
      Verify: `tests/archival/test_retained_source_adapter.py::test_retained_source_admission_requires_owner_keep_decision`
- [ ] Storage resolves through PDM StorePort and receipts carry only opaque representation refs;
      no private DSN/backend construction or absolute path becomes durable authority.
      Verify: `tests/archival/test_retained_source_adapter.py::test_retained_source_uses_store_port_and_redacted_receipts`
- [ ] Restore reuses the retained-source access gate, verifies bytes/format/provenance, and refuses a
      mismatched destination or stale generation before writing.
      Verify: `tests/archival/test_retained_source_adapter.py::test_retained_source_restore_is_gated_and_generation_bound`
- [ ] Raw-evidence TTL/consent policy is not inherited; retirement/deletion requires the exact
      retained-source policy and remains pending on physical cleanup failure.
      Verify: `tests/archival/test_retained_source_adapter.py::test_retained_source_policy_does_not_inherit_raw_ttl`

## How to Verify (Pre-Merge)

1. `pytest -q tests/archival/test_retained_source_adapter.py`
2. `pytest -q tests/stores` for the selected StorePort binding.
3. `pytest -q tests/architecture/test_governed_archival_contract.py`
4. `ruff check app/archival app/stores tests/archival`

## Out of Scope

- Automated filesystem/cloud scanning, media-library import, curation UI, legal-retention decisions,
  cloud provider selection, or moving writing-surface artifacts into retention.
- A universal retained-source database or rewrite of the existing persistence-surface contracts.

## Restart / Durability Posture

Admission, representation, policy version, receipt, and cleanup state are durable through the owner
adapter and StorePort. Process-local caches are disposable. After restart an incomplete transition is
pending/unavailable and retryable; missing durable admission is never inferred from surviving bytes.

## Related Docs

- `docs/SEPARATING_PERSISTENCE_SURFACES/DEFINE_RETENTION_SURFACE_CONTRACT.md`
- `docs/CONTEXTUALIZATION_LAYER/MEDIA_ARTIFACT_CONTRACT.md`
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md`
- `docs/contracts/STORE_PORT.md`
- `docs/CONCEPTS/PORTABILITY_CONTRACT.md`

## Related GitHub Issues

One bounded adapter Issue. Execution context: `fresh_issue_agent`; helper budget `0`. TCD hint:
Terra / high because it adds durable source handling and policy boundaries, but the adapter is
isolated behind the already-delivered transition kernel and concrete tests.
