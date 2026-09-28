---
name: Write receipt provenance and note classification
description: Centralize ADR-0055 note-class execution policy and enrich filesystem write receipts.
task_id: VMW-01
source_anchor: "docs/adr/ADR-0055-vault-multiwriter-consistency-model.md :: items 1, 4, 6"
parent_capability: VAULT_MULTIWRITER_ENACTMENT
prerequisites: []
depends_on: []
can_parallelize_with: []
---

# Write Receipt Provenance and Note Classification

## Purpose

Give the shared filesystem write seam one explicit execution representation of #3131's note classes and identify every write in its receipt.

## What This Task Does

Add a centralized note-class/operation classifier aligned with the committed Mimer client-contract table, a shared rewritten-write request carrying the caller's expected content version, and one conflict-artifact grammar/classifier consumed by both staging and quarantine. Extend `WriteReceipt`/the filesystem adapter so write and append receipts carry writer identity and an UTC timestamp.

## Concretely

`_heimdal` full-note/frontmatter updates, prose, companion notes, and Episode notes are rewritten. Capture, event-log, Sources, and explicitly append-only control-note body operations remain append-only. The shared rewritten-write request carries the hash read by the caller through `write_note_relative`/`write_note_from_absolute` to `FsVaultAdapter`.

**Enforcement remains opt-in (owner decision 2026-07-13).** Version enforcement applies only to callers that pass `expected_version`. The bounded #3570 follow-ups delivered existing-target rewrite support for the registered in-repository producer families and reconciled the specified create-intent census. They did not make the shared seam require `expected_version`, establish universal no-clobber behavior for absent targets, or cover direct-filesystem clients and future/unregistered callers:

- `expected_version` omitted → the write is performed normally (enforcement deferred). The `WriteReceipt` still records the structured `note_class` outcome, so the classification is observable even before a caller opts in.
- `expected_version` provided and matching the current on-disk hash → the write proceeds.
- `expected_version` provided and stale at the first comparison (mismatched) → with VMW-02 composed with this request contract, the low-level seam preserves the caller's proposal under the shared sibling conflict-artifact grammar, leaves the canonical note unchanged, and returns a `conflict_staged` receipt. Shared production helpers raise `KnowledgeWriteConflict` carrying that receipt by default; only an explicitly conflict-aware caller opts into a normal staged-receipt return. Missing targets and races after the first comparison still fail closed with `KnowledgeWriteConflict`.

This resolves the earlier "structured non-write outcome vs. hard raise" tension in favour of the opt-in model: a versionless rewrite is a normal write plus a classified receipt, an initially stale opted-in rewrite has the structured staged-conflict outcome supplied by VMW-02 at the low-level adapter, the production helpers preserve hard-failure semantics for unaware consumers, and an in-flight race remains a hard failure. The shared artifact helper owns the sibling filename grammar and `is_conflict_artifact` predicate.

## Classification ledger (#5140, #5134, #5489)

The relative write seam owns the explicit create-once mode for the producers below. The Heimdal
single-note writers use it only when their exact-byte read finds an absent target; existing targets
use the rewritten-note CAS path. The MCP collection writer remains append-only; it is listed so the
census is complete without treating its unique-path allocation as a rewritten-note migration.

| Producer | Disposition | Enforcement / preservation rule |
| --- | --- | --- |
| `app/agent_memory/materialization.py::materialize_promoted_memory` | create-once | deterministic materialization path; retries preserve the first complete artifact |
| `app/agent_memory/provisional_write.py::write_provisional_memory` | create-once | UUID artifact is first-write-wins; lifecycle receipts remain replayable |
| `app/chat/session_log.py::SessionLogWriter.open_session` | create-once | session header is published once; later turns use append-only writes |
| `app/episodes/segmenter.py::_write_fusion_receipt` | create-once | deterministic receipt path is idempotent and never clobbers a prior receipt |
| `app/eval/failure_capture.py::_write_draft` | create-once | initial draft is first-write-wins; `_decide` has delivered snapshot/CAS and explicit conflict handling under #5136 / PR #5487 and #5491 / PR #5508 |
| `app/heimdal/candidate_projection.py::write_candidate_note` | create-once | deterministic candidate projection is idempotent and preserves a prior artifact |
| `app/heimdal/candidate_projection.py::write_reading_candidate_note` | create-once | deterministic reading projection is idempotent and preserves a prior artifact |
| `app/heimdal/capture_note.py::write_capture_note` | create-once/CAS | absent capture targets are first-writer-wins; existing transitions use exact-byte CAS |
| `app/heimdal/settings_notes.py::_write_settings_note` | create-once/CAS | absent control targets are first-writer-wins; existing updates use exact-byte CAS; bounded non-idempotent callers fail loudly on a losing create while idempotent readouts may return the winner |
| `app/services/commitment_persistence.py::persist_commitment` | create-once/CAS | first persistence is first-writer-wins and rejects a losing create; existing targets use exact-byte CAS (#5489 / PR #5492) |
| `app/mcp/vault_tools.py::append_note` | append-only | next-available MCP note paths preserve every earlier artifact; no create-once mode is added |

The ledger is an intent classification, not a new generic write primitive. Any writer discovered to
rewrite an existing artifact must receive its own bounded contract and verification target rather
than being silently added to this census.

## Registered write-site reconciliation

The current AST registry in `tests/properties/_machinery.py` contains 20 `write_note_relative`
call sites. This WriteGuard call-site census is separate from the eleven-entry intent registry above
and from the 14 raw-byte version reads checked by
`tests/invariants/test_vault_multiwriter.py::test_expected_version_producers_hash_the_exact_filesystem_bytes`.
It is not a count of 20 CAS obligations or a census of direct-filesystem clients.

| Registered sites | Current disposition | Delivery evidence / boundary |
| --- | --- | --- |
| `app/agent_memory/materialization.py::materialize_promoted_memory`; `app/agent_memory/provisional_write.py::write_provisional_memory`; `app/chat/session_log.py::SessionLogWriter.open_session`; `app/episodes/segmenter.py::_write_fusion_receipt`; `app/eval/failure_capture.py::_write_draft`; both `app/heimdal/candidate_projection.py` producers | Seven create-once sites | #5140 / PR #5327; shared no-clobber behavior is covered by `test_create_intended_writers_do_not_clobber_existing_artifacts`. |
| `app/heimdal/capture_note.py::write_capture_note`; `app/heimdal/settings_notes.py::_write_settings_note` | Mixed create-once/CAS sites: first creation uses create-once; existing targets use exact-byte CAS | #5134 / PR #5464 and #5467 / PR #5471; settings losing-create behavior is fail-loud for non-idempotent callers. |
| `app/briefing/compose.py::_atomic_write` (ordinal 2); `app/relevance/materialization.py::materialize_moment`; `app/eval/failure_capture.py::_decide`; `app/services/commitment_persistence.py::persist_commitment` (replacement branch); `app/heimdal/time_spend.py::write_time_spend_note`; `app/episodes/store.py::write_episode_note`; `app/standing_questions/question_store.py::QuestionStore._write` | Seven existing-target rewrite sites use the raw-byte version they read | #5134–#5139 / PRs #5464, #5316, #5487, #5484, #5483, and #5485; repairs #5489 / PR #5492 and #5491 / PR #5508 preserve conflict/loss behavior. For applicable missing-target paths, this does not claim universal no-clobber creation. |
| `app/services/commitment_persistence.py::persist_commitment` (create branch) | One additional create-once site | #5489 / PR #5492; a losing create cannot silently acknowledge the requested mutation. |
| `app/mcp/vault_tools.py::append_note` | One append-only collection producer | #5140 / PR #5327; distinct available paths preserve earlier artifacts. |
| `app/briefing/compose.py::_atomic_write` (ordinal 1) | One private staging write | Its target is private staging, not the canonical note; the canonical CAS is ordinal 2. |
| `app/heimdal/entity_register.py::EntityRegister._write_entry` | One separately owned register site | Entity-register operation-journal authority remains with #4349 / #4351 / #4352; it is not duplicated by #3570. |

These buckets account for the 20 registered relative-port call sites. The seven CAS entries describe
existing-target rewrites; notably, initial creation in Daily Briefing, Relevance, Episode, and
Standing Questions can take a versionless branch. No universal CAS or no-clobber claim follows from
the closed #3570 scope.

For the settings-note create branch, `WriteReceipt(outcome="already_exists")` is an explicit
non-canonical result. Idempotent derived/readout callers may return the verified durable winner;
non-idempotent callers must select the settings-note seam's fail-loud policy and receive
`KnowledgeWriteConflict` with the receipt attached. They must not acknowledge the requested
mutation or overwrite the concurrent winner.

## Why This Matters

VMW-02 relies on this classification to apply stale detection only to rewritten operations. Provenance lets a human understand the two sides of a staged conflict, while VMW-03 consumes the same artifact grammar to quarantine that sibling before ordinary ingest.

## Acceptance Criteria

- [ ] Runtime classification covers every decided #3131 row, including mixed control notes by operation. Verify: `tests/invariants/test_vault_multiwriter.py::test_runtime_note_classes_match_published_contract_rows`
- [ ] A rewritten write's expected hash is propagated through the public knowledge ports to the production filesystem seam; enforcement is opt-in (a versionless rewrite writes and records its `note_class`; after VMW-02 composition, an initially stale opted-in rewrite stages the proposal without overwriting canonical content). Verify: `tests/invariants/test_vault_multiwriter.py::test_rewritten_write_enforces_only_on_opt_in_expected_version_at_filesystem_seam`
- [ ] Filesystem write and append receipts carry a non-empty writer identity and UTC timestamp. Verify: `tests/invariants/test_vault_multiwriter.py::test_filesystem_write_receipt_carries_writer_provenance`
- [ ] Append-only classification is observable at the production filesystem write seam, not only in a helper test. Verify: `tests/invariants/test_vault_multiwriter.py::test_append_operation_uses_append_only_class_at_filesystem_seam`
- [ ] The shared conflict-artifact grammar identifies both VMW-02 staged artifacts and iCloud-style conflicted copies. Verify: `tests/invariants/test_vault_multiwriter.py::test_conflict_artifact_classifier_recognizes_staged_and_icloud_names`

## How to Verify (Pre-Merge)

`pytest -q tests/invariants/test_vault_multiwriter.py` and `ruff check app tests`.

## Out of Scope

VMW-01 did not itself own stale detection/conflict staging (VMW-02), watcher quarantine (VMW-03), or `append_note_relative` WriteGuard coverage (INV-VW2 / #3129); all three are delivered and composed with its shared contract, and VMW-04 registry reconciliation is delivered. Universal migration of every remaining versionless rewritten writer remains out of scope.

## Related Docs

ADR-0055; `docs/contracts/MIMER_CLIENT_CONTRACT.md :: Note-classification contract`; `app/knowledge/adapters.py`; `app/knowledge/contracts.py`.

## Related GitHub Issues

Implements child of #3132; recommend medium/high reasoning because this changes the shared write receipt contract.
