---
name: Consolidate Semantic Identity Authority
description: Make one logical owner responsible for canonical semantic identity.
task_id: GKES-04
source_anchor: docs/architecture/functional-ontology.md :: Artifact
parent_capability: Governed Knowledge Effect Spine
prerequisites: [GKES-01, GKES-03]
depends_on: [DEFINE_EFFECT_SPINE_CONTRACTS.md, PERSIST_CANDIDATE_EVIDENCE_POSTURE.md]
can_parallelize_with: [ENFORCE_GOVERNED_EFFECT_TOKENS]
---

# Consolidate Semantic Identity Authority

## Purpose

Give canonical semantic identity one logical owner while keeping the SBS independent of source layout.

## What This Task Does

Implement the owner decision established in GKES-01: canonical IDs, aliases, legacy mapping, merge semantics and idempotent lookup/upsert. Migrate or fence parallel identity minting.

## Concretely

Use a stable identifier and alias/redirect pattern; do not make a graph or DRI projection canonical. If authoritative docs and live code prove two incompatible owners, create an owner decision brief rather than guessing.

## Why This Matters

Identity drift creates duplicated knowledge and makes correction/rebuild permanently expensive.

## Acceptance Criteria

- [ ] All identified production producers resolve/mint semantic identity through the one logical owner. Verify: `tests/heimdal/test_entity_register.py::test_only_identity_owner_mints_canonical_identity`.
- [ ] Alias and merge operations are idempotent across restart. Verify: `tests/heimdal/test_entity_register.py::test_merge_and_alias_replay_is_idempotent`.
- [ ] Legacy identity use is resolved or fail-loud rather than silently creating a second identity. Verify: `tests/heimdal/test_entity_register.py::test_legacy_identity_resolution_is_explicit`.

## How to Verify (Pre-Merge)

- `pytest -q tests/heimdal/test_entity_register.py tests/heimdal/test_attribution.py`
- `ruff check app tests`

## Out of Scope

DRI rebuild and universal entity enrichment.

## Related Docs

- `docs/architecture/functional-ontology.md`
- `docs/boundaries/SIP.md`

## Related GitHub Issues

Blocked by GKES-01 and GKES-03; unblocks GKES-07.
