---
name: Define Reading Source And Candidate Contract
description: Fix Karakeep identity, revision, provenance, cursor, deletion, and draft-candidate semantics before code.
task_id: KMA-01
source_anchor: "docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Capability boundary"
parent_capability: Karakeep Mimer Acquisition
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Define Reading Source And Candidate Contract

## Purpose

Make Karakeep a conforming KAP acquisition source without importing source-specific authority into
HKA/GOV or reusing the companion-capture path.

## What This Task Does

Define link/note/highlight raw shapes, stable source identity and revision fingerprint, timestamps,
provenance, tombstone/deletion posture, pagination/cursor semantics, error taxonomy, and the draft
`reading_source_note` candidate mapping. Reconcile required generalization of the currently YouTube-
shaped candidate model while retaining governed first-write-wins behavior.

## Concretely

Update this specification and the local KAP source/candidate contracts so implementation has named
fields and no semantic decisions remain. No runtime behavior lands in this task.

## Why This Matters

Identity, authority, and cursor mistakes would propagate into every later slice and make apparently
successful ingestion either lossy or falsely authoritative.

## SBS Impact

Product/Runtime: EBF primary; DRI and HKA/SIP/GOV secondary. Contract/docs write class; no shipped
runtime claim. External source mechanics cannot become human-knowledge authority.

## Restart / Durability Posture

The contract fixes which state is durable (raw record and cursor) and which is derived. Cursor
replay and content revisions must remain deterministic across process and host restarts.

## Acceptance Criteria

- [ ] Contract names stable item identity, content revision, provenance, and link/note/highlight
  representation. Verify: `tests/knowledge_acquisition/test_karakeep_contract.py::test_contract_fixture_covers_link_note_and_highlight_identity`.
- [ ] Cursor advances only after durable raw acceptance; deletion/tombstone never deletes a vault
  artifact automatically. Verify: `tests/knowledge_acquisition/test_karakeep_contract.py::test_cursor_and_tombstone_semantics_are_fail_safe`.
- [ ] Candidate mapping mandates `requires_review: true`, `review_state: draft`, deterministic path,
  Karakeep provenance, and KAP WriteGuard materialization. Verify: `tests/knowledge_acquisition/test_karakeep_contract.py::test_candidate_contract_is_draft_governed_and_deterministic`.
- [ ] Contract explicitly forbids `/api/capture`, companion capture, Karakeep MCP, and embedded
  endpoint/credential values. Verify: doc writeback at
  `docs/KARAKEEP_MIMER_ACQUISITION/README.md :: Capability boundary`.

## How to Verify (Pre-Merge)

- `pytest -q tests/knowledge_acquisition/test_karakeep_contract.py`
- `python3 scripts/docs_guard.py`

## Out of Scope

Runtime adapter code, service deployment, scheduling, source writes, content promotion, and secret or
endpoint selection.

## Related Docs

- `docs/KNOWLEDGE_ACQUISITION/SOURCE_PLUGIN_CONTRACT.md`
- `docs/KNOWLEDGE_ACQUISITION/REFINEMENT_PIPELINE_CONTRACT.md`
- `docs/CONTEXTUALIZATION_LAYER/INGESTION_AND_TRIAGE_POLICY.md`

## Related GitHub Issues

Future first child of the unfiled parent. TCD hint: strongest available model / high reasoning;
authority, cursor, revision, and source-contract errors would cause costly downstream rework.
