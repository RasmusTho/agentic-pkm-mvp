---
name: Adapt Human Artifact Recovery
description: Add portable export and conflict-safe recovery for human-authored and human-accepted artifacts without importing raw-media retention semantics
task_id: GAF-05
github_issue: 5067
source_anchor: "docs/GOVERNED_ARCHIVAL_FLOW/README.md :: Artifact-Class Posture"
parent_capability: GOVERNED_ARCHIVAL_FLOW
prerequisites: [GAF-02, GAF-03]
depends_on: [IMPLEMENT_VERIFIED_TRANSITION_KERNEL.md, ADAPT_HEIMDAL_RAW_MEDIA.md]
can_parallelize_with: [Adapt Retained Source Artifacts, Govern Rebuildable Derivatives]
---

# Adapt Human Artifact Recovery

## Purpose

Give durable human-authored and human-accepted artifacts a portable recovery path while preserving
HKA as the authority for identity, generation, provenance, and governed writes.

## What This Task Does

- Implement an HKA recovery adapter under `app.archival.adapters` over the existing ArtifactContract
  and VaultPort/governed-write seams.
- Export one representative human-readable artifact plus the minimum provenance, identity,
  generation, and policy metadata required for independent recovery verification.
- Stage and verify a recovery before invoking the production governed-write path.
- Detect current-generation drift and refuse to overwrite a newer HKA artifact; surface a typed
  conflict that an owner-native workflow can resolve.
- Keep raw-evidence TTL, consent-revocation cleanup, and Heimdal liveness out of HKA policy.

## Concretely

```bash
pytest -q tests/archival/test_hka_recovery_adapter.py
```

The fixture exports a human-readable artifact, verifies it in a clean recovery target, and exercises
both unchanged-generation recovery and a newer-generation conflict through the real governed-write
seam.

## Why This Matters

Human-authored knowledge is durable meaning, not transient evidence. Reusing raw-media expiry would
risk deletion, while bypassing HKA generation checks would let recovery overwrite newer work.

## Acceptance Criteria

- [x] Exported HKA recovery material is human-readable and carries stable artifact identity,
      provenance, generation, format, and a redacted integrity proof.
      Verify: `tests/archival/test_hka_recovery_adapter.py::test_human_artifact_export_is_portable_and_provenance_complete`
- [x] Recovery stages and verifies the exact exported representation before calling the production
      HKA governed-write seam.
      Verify: `tests/archival/test_hka_recovery_adapter.py::test_hka_recovery_invokes_production_governed_write_after_verification`
- [x] A newer owner-native generation is never overwritten; the adapter reports a typed conflict
      and leaves both representations available for governed resolution.
      Verify: `tests/archival/test_hka_recovery_adapter.py::test_human_artifact_recovery_refuses_newer_generation_overwrite`
- [x] HKA recovery never inherits raw-evidence TTL, consent-revocation cleanup, or Heimdal terminal
      liveness rules.
      Verify: `tests/archival/test_hka_recovery_adapter.py::test_hka_adapter_uses_governed_write_and_never_raw_delete_policy`
- [x] The adapter creates no parallel HKA artifact registry, generation ledger, or authority store.
      Verify: `tests/architecture/test_governed_archival_contract.py::test_hka_adapter_has_no_parallel_authority_store`

## How to Verify (Pre-Merge)

1. `pytest -q tests/archival/test_hka_recovery_adapter.py`
2. `pytest -q tests/architecture/test_governed_archival_contract.py`
3. Run the existing HKA ArtifactContract and VaultPort contract suites selected by
   `scripts/select_pr_tests.py`.
4. `ruff check app/archival tests/archival tests/architecture/test_governed_archival_contract.py`

## Out of Scope

- Collaborative merge UX, arbitrary filesystem backup, replacement of HKA/VaultPort, raw-evidence
  retention, or automatic promotion of a recovered conflict.
- Treating cache, embedding, index, media raw, or retained-source bytes as HKA merely because a note
  references them.

## Restart / Durability Posture

The export, integrity proof, owner-native identity/generation, staged recovery descriptor, and final
receipt are durable. Process-local verification buffers are disposable. After restart an unfinished
recovery is pending and must be reverified; a staged copy never becomes HKA authority until the
production governed-write succeeds for the expected generation.

## Related Docs

- `docs/GOVERNED_ARCHIVAL_FLOW/README.md`
- `docs/contracts/ARTIFACT_CONTRACT.md`
- `docs/CONCEPTS/PORTABILITY_CONTRACT.md`
- `docs/architecture/ARTIFACT_CLASSIFICATION_AND_LIFECYCLE.md`
- `docs/contracts/STORE_PORT.md`

## Related GitHub Issues

One bounded adapter Issue. Execution context: `fresh_issue_agent`; helper budget `0`. TCD hint:
Terra / high because it crosses durable HKA authority and recovery conflict handling, while the
transition mechanism and exact production seam are already bounded by prior tasks.
