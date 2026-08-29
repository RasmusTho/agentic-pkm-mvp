# SQ-04 Standing Questions refresh mechanism convergence packet

State: Advisory mechanism-review evidence for Issue #3327 / PR #5174; not runtime authority.

Mechanism key: `SQ-04:question-refresh-generation`

This packet records the stateful mechanism review for the evidence-delta answer refresh. The
Standing Questions contracts, Question schema, Create contract, and guarded write seam remain the
authorities. This packet is a bounded proof map and must not be read as delivery of SQ-05, live UAT,
or human acceptance.

## Protected invariants

- `INV-SQ-A`: refresh writes only system-owned Question fields and never overwrites human-owned
  `text` or `status`.
- `INV-SQ-C`: a candidate remains provisional; only the future governed SQ-05 acceptance action may
  materialize an answer and make the Question `answered`.
- `INV-SQ-D`: an un-actioned candidate is never clobbered by a new evidence delta.
- `INV-SQ-E`: contradiction is surfaced with an exact textual basis, or degrades to `unknown`.
- Exact-byte Question CAS rejects a stale refresh after human/runtime edits.
- Evidence identity is the exact judged source bytes, not a mutable path alone; a changed source is
  blocked and hashless legacy evidence is rejected until an explicit backfill binds historical bytes.
- Watcher delivery is retryable: exception and structured-blocked refresh outcomes preserve the source
  observation instead of advancing the snapshot as if the capability succeeded.
- Receipt event IDs are globally unique across all writers targeting one configured index-outbox
  path and event types; conflicting duplicates fail closed under one shared append lock, including
  the legacy index/audit, watcher, vault-watcher, and orchestrator writers plus real-path/symlink
  aliases. The seam refuses unreadable or malformed existing JSONL and repairs only an unambiguous
  complete final record that lacks its delimiter. Separate telemetry/queue JSONL files remain
  separate sinks and are not folded into this index-outbox invariant.
- A standing-answer edit detected after the Question pointer write triggers a guarded rollback of the
  pointer and refresh timestamp, preserving fail-closed semantics for the external-file race; a
  competing Question write is retried and rollback exhaustion is fail-loud.
- The deterministic proposal pair carries an integrity-first sidecar and an atomically replaced
  draft under a draft-scoped publication lock; replay or receipt emission fails closed if staged
  draft bytes no longer match the recorded identity, while crashes between publication steps remain
  replayable.
- Deterministic replay and expiry take the same draft-scoped lock. An expiry receipt explains a
  deliberately removed proposal; a later retry rebuilds the draft under a fresh proposal receipt
  identity rather than treating changed replacement bytes as the old receipt. The expiry receipt is
  published before deletion and is bound to the proposal receipt id plus draft hash, so a failed
  receipt write preserves the draft and an old expiry cannot authorize a later generation.
- JSONL parsing treats only the byte `0x0A` as the record delimiter, so valid Unicode line-separator
  characters remain inside a JSON string and do not wedge the configured outbox.
- Question notes are excluded as evidence sources both at the watcher adapter and matcher core;
  canonical path resolution is applied to direct, traversal, and persisted evidence refs, so a
  Question edit cannot self-seed its own evidence log or answer refresh.
- Configured JSONL consumers use the shared strict reader; promotion cursors advance by validated
  records rather than silently skipping malformed or Unicode-containing records.
- JSONL receipt read/check/append is serialized per canonical index-outbox path, so the event-id
  invariant is atomic across independent writers, event types, and path aliases.
- The configured index-outbox writer census includes settings receipts, worker latency summaries,
  CLI pipe results, promotion emissions, index/audit writers, legacy emissions, orchestrator
  events, and watcher paths. Settings once-only receipt locking also canonicalizes path aliases;
  unrelated incident, telemetry, queue, and failure-report files remain separate sinks.

## States and transitions

The mechanism recognizes these states without adding a second authority store:

- `eligible/open-delta`: an open Question has evidence newer than `last_refreshed_at` and no pending
  candidate.
- `candidate-staged/pending`: Create has produced a staged provisional draft and a proposed receipt;
  the Question pointer may be conditionally advanced.
- `accepted/terminal`: owned by the future SQ-05 governed acceptance path; SQ-04 never creates it.
- `blocked`: source identity, citation, activation, or cognition requirements cannot be satisfied.
- `deferred`: a pending candidate protects the review surface, so the new delta remains in the log.
- `retryable-failed`: watcher composition failed or returned a structured blocked result; the source
  snapshot remains at its previous cursor.
- `conflict`: the Question bytes changed during cognition; the refresh retries the same exact evidence
  generation rather than publishing stale state. A materially changed evidence generation receives a
  new deterministic identity; the prior proposal remains traceable and is never overwritten.

Terminal or indeterminate outcomes are explicit: `accepted` is terminal for SQ-04, while `blocked`,
`deferred`, `retryable-failed`, and `conflict` remain observable and replayable. A missing staged
draft is derived as no longer pending; an unreadable referenced draft is conservatively protected.

## Writers and consumers

- `match_evidence_to_open_questions` reads candidate artifacts and writes only the Question-side
  evidence log through `QuestionStore`; source artifacts are read-only.
- `refresh_answers_on_evidence_delta` reads the canonical Question, derives delta/pending state,
  invokes Create, and conditionally writes only `candidate_answer_ref` and `last_refreshed_at`.
- `run_create_pass` writes the staged compilation draft and deterministic proposed receipt. It never
  writes a canonical answer.
- `vault_watcher._finish_tick` advances the filesystem snapshot only after composition; it restores
  each affected path to its pre-tick observation when refresh is blocked or raises.
- SQ-05 is the future consumer of the staged candidate and the only owner of visual accept/dismiss;
  it is not implemented or validated by this mechanism.

## Crash ordering and replay

For one refresh generation, the durable order is:

1. Read the Question and evidence entries; resolve exact source bytes and verify each stored content
   hash before decoding text for cognition.
2. Match new evidence and append a bounded evidence entry through the guarded QuestionStore seam.
3. Capture the exact Question byte/version snapshot before cognition.
4. Run Create, acquire the deterministic draft publication lock, publish the expected draft
   identity, and atomically replace the deterministic staged draft id with its parent directory
   fsynced.
5. Emit/reuse the deterministic `expansion.create.proposed` receipt id under the shared canonical
   JSONL lock; append is one flushed/fsynced JSONL record.
6. Apply the Question update with exact-byte CAS.

If the process dies before the CAS, the deterministic draft/receipt pair is reused for the same
`question_id` plus exact evidence-generation fingerprint. The draft is not rewritten, and a reused
receipt must match both the draft byte hash and its full payload. If the process dies after the
integrity record but before the draft replace, the orphan identity is safely overwritten on retry
because no draft exists; an existing draft without its identity remains fail-closed. If CAS conflicts, the retry re-reads
the Question; unchanged evidence reuses the one logical proposal, while newly appended evidence gets
a distinct generation identity rather than silently changing an old receipted draft. If source bytes
no longer match their recorded content hash, replay fails closed. If watcher composition raises or
returns structured `blocked`, the changed observation is retained for the next unchanged tick.

## Locks and races

Each Question refresh holds a process-local re-entrant lock plus an OS `flock` for the full
read/check/Create/CAS sequence. Deterministic Create publication additionally holds a draft-scoped
OS `flock` across draft, integrity sidecar, and receipt publication, then takes the canonical
outbox lock in that order. The QuestionStore guarded seam owns exact-byte conditional writes.
The watcher owns snapshot advancement and performs the retry-preservation write after its normal
refresh. The source hash check prevents a path/provenance race from converting current bytes into a
historical evidence claim. No SQ-04 writer changes the standing answer or human-owned status.

## Focused proof map

| Obligation | Current probe | Result at the last focused run |
| --- | --- | --- |
| Exception refresh failure remains replayable | `test_watcher_retries_standing_questions_failure_before_advancing_snapshot` | Passed |
| Structured blocked result remains replayable | `test_watcher_retries_blocked_standing_questions_before_advancing_snapshot` | Passed |
| CAS conflict does not duplicate proposal artifacts | `test_refresh_cas_snapshot_is_taken_before_drafting` | Passed |
| Pending review is not clobbered | `test_pending_review_not_clobbered_by_new_delta` | Passed |
| Changed source bytes cannot be replayed | `test_changed_source_bytes_cannot_replay_historical_evidence` | Passed |
| Contradiction basis is exact or unknown | `test_contradiction_surfaced_not_silently_rewritten`, `test_invalid_contradiction_basis_degrades_to_unknown` | Passed |
| Human fields remain protected | QuestionStore CAS and human-field tests | Passed |
| Evidence entries carry content identity | `test_relevant_artifact_attaches_irrelevant_does_not` | Passed |
| Focused SQ/Create regression set | Standing Questions, evidence matching, Create lifecycle, QuestionStore, and JSONL outbox contract tests | `229 passed`, 4 PG projection tests skipped because no scratch database was configured |
| Changed-path CI selection covers every affected outbox/status seam | `scripts/select_pr_tests.py` plus `tests/scripts/test_select_pr_tests.py` | Initial current-head CI failed closed on four unowned paths; explicit shared-CLI, events-receipts, and observability routing was added, and selector regressions pass (`102 passed`) |
| Matcher CAS conflict is observable and non-clobbering | `test_match_write_conflict_does_not_clobber_question` | Passed |
| Deterministic replay preserves draft bytes and receipt payload | `test_refresh_replay_reuses_draft_and_receipt_bytes` | Passed |
| Matcher CAS conflict remains watcher-retryable | `test_watcher_retries_standing_questions_matching_conflict_before_advancing_snapshot` | Passed locally; CI proof is pending for the current head |
| Raw draft-byte mutation cannot replay a deterministic proposal | `test_refresh_replay_reuses_draft_and_receipt_bytes` | Passed |
| Human question edit changes refresh generation and blocks stale CAS | `test_refresh_retry_after_question_text_edit_derives_new_generation` | Passed |
| Standing-answer edit during cognition blocks stale contradiction | `test_standing_answer_edit_during_cognition_blocks_stale_contradiction` | Passed |
| Human matcher edit during judgment cannot attach stale evidence | `test_match_human_edit_during_judgment_blocks_stale_evidence` | Passed |
| Matching records exact CRLF source bytes | `test_matching_hashes_exact_source_bytes` | Passed |
| Newline-only source mutation cannot replay refresh evidence | `test_newline_only_source_mutation_cannot_replay_historical_evidence` | Passed |
| Newline-only standing-answer edit cannot pass refresh race check | `test_standing_answer_newline_edit_during_cognition_blocks_stale_refresh` | Passed |
| Conflicting duplicate receipt IDs fail closed | `test_emit_receipt_rejects_conflicting_duplicate_event_ids` | Passed |
| Matcher uses scope from the fresh CAS baseline | `test_match_uses_fresh_scope_baseline` | Passed |
| Question raw-byte version changes refresh generation | `test_question_raw_byte_version_changes_refresh_generation` | Passed |
| Snapshot retry restoration precedes persistence | `test_watcher_retry_snapshot_is_restored_before_persist_crash` | Passed in CI environment; local watcher collection is dependency-gated |
| Event IDs cannot collide across event types | `test_emit_receipt_rejects_event_id_collision_across_event_types` | Passed |
| Standing-answer edit after Question write rolls back stale candidate | `test_standing_answer_edit_between_final_check_and_cas_rolls_back_candidate` | Passed |
| Concurrent receipt writers cannot publish one event ID twice | `test_deterministic_receipt_event_id_is_atomic_across_event_types` | Passed |
| Public JSONL writer rejects an existing event-ID collision | `test_public_jsonl_writer_rejects_existing_event_id_collision` | Passed |
| Legacy JSONL writer shares global event-ID validation | `test_legacy_jsonl_writer_uses_global_event_id_seam` | Passed |
| Unreadable JSONL fails closed before append | `test_jsonl_append_fails_closed_when_existing_outbox_cannot_be_read` | Passed |
| Complete unterminated JSONL tail is repaired before append | `test_jsonl_append_repairs_complete_unterminated_record` | Passed |
| Real-path and symlink aliases share event identity | `test_jsonl_event_id_identity_is_shared_across_real_path_and_symlink` | Passed |
| Concurrent deterministic Create publication converges | `test_concurrent_deterministic_create_publication_converges` | Passed |
| Index-audit writer uses the shared event-id seam | `test_index_audit_writer_uses_shared_event_id_seam` | Passed |
| Watcher scan writer uses the shared event-id seam | `test_watcher_scan_writer_uses_shared_event_id_seam` | Passed |
| Settings receipt durable writer preserves fsync/readback behavior through shared seam | `tests/vault/test_settings_receipt_durable.py` | Passed |
| Worker latency writer preserves idempotent handler behavior through shared seam | `tests/workers/test_handler_idempotency_harness.py` | Passed |
| Settings once-only lock is shared by real-path and symlink aliases | `test_settings_receipt_aliases_share_once_only_lock` | Passed |
| Settings receipt readback rejects a valid receipt followed by malformed JSONL | `test_operation_scoped_readback_fails_closed_on_corrupt_tail` | Passed |
| Valid Unicode JSONL line-separator characters remain one record | `test_jsonl_append_preserves_unicode_line_separator_characters` | Passed |
| Expired proposal is rebuilt with a fresh receipt identity | `test_expired_draft_receipt_can_be_replayed_after_expiry` | Passed |
| Question note cannot become its own evidence | `test_question_note_cannot_become_its_own_evidence` | Passed |
| Traversal alias cannot bypass Question-note exclusion | `test_question_note_path_traversal_cannot_bypass_self_exclusion` | Passed |
| Expiry receipt failure preserves the draft for retry | `test_expiry_receipt_failure_preserves_draft_for_retry` | Passed |
| Configured JSONL consumers preserve Unicode line-separator characters | `test_configured_jsonl_consumers_preserve_unicode_line_separators` | Passed |
| Draft mutation after staging cannot be accepted by deterministic replay | `test_refresh_replay_reuses_draft_and_receipt_bytes` | Passed |
| Crash between integrity record and draft replace remains replayable | `test_crash_between_integrity_and_draft_write_remains_replayable` | Passed |
| Rollback converges after a competing Question CAS conflict | `test_standing_answer_drift_rollback_retries_after_question_conflict` | Passed |
| Bounded status, health, API, receipt, migration, and orientation readers preserve unknown-on-corruption and no-mutation defaults | Affected outbox/status/health/API/receipt suite | `135 passed`; Ruff and mypy (`935` source files) passed on the pre-doc-writeback implementation head |

An earlier full not-PostgreSQL run at the pre-current repair head was deliberately interrupted
after `1,724 passed, 6 skipped, 513 deselected` because its estimated completion time was
disproportionate; it is not a current full-suite proof. The current watcher core collection passes
16 tests locally, while optional watcher scenarios remain dependency-gated in this environment.
CI remains the authoritative environment for the selected full suite; focused watcher tests use the
same production tick seam but are not a substitute for that environment proof.
Live test, Playwright/browser proof, owner observation, and SQ-05 acceptance remain unclaimed and are
not silently promoted by this packet.

## Prior review findings and attempted fixes

The convergence history is part of the review evidence. Each row is bound to the exact local head
where the finding was observed; a later head invalidates the earlier clean/unclean conclusion.

| Review head | Finding | Disposition in the next repair |
| --- | --- | --- |
| `0d0322502` (GitHub review original commit) | No production match-then-refresh caller; cognition was initially given a provenance URI as an object id; CAS baseline was captured too late. | Production watcher composition, reasoning-input materialization, and pre-cognition Question version capture were added before the next review. |
| `3627cec12` (local follow-up) | Watcher SQ failure could advance the source snapshot; static property registrations drifted after watcher hydration moved. | Exception retry preservation was added; the census was repinned at the actual sink/producer lines. |
| `1bca186bd` | Structured blocked results were treated as success; CAS retry could orphan/duplicate draft and receipt; mutable path could replay changed evidence; contradiction basis was only nonempty; registry rows were missing. | Blocked-result retry, deterministic proposal identity, source content hashes, exact contradiction basis, and registry entries were added. |
| `bcf0f2120` | Replay did not compare full receipt payload; standing-answer bytes were outside the refresh identity; SQ-03 append lacked a fresh duplicate fold; matcher CAS conflicts were not watcher-retryable; docs overstated lifecycle. | Full payload/byte parity, standing-answer fingerprinting, post-read duplicate filtering, matcher conflict retry, and lifecycle/doc corrections were added in the current repair. |
| `efe48163d` | Fresh review found source content hashes were still derived from newline-normalized text, so CRLF↔LF mutations could retain identity. | Raw bytes now travel separately from cognition text through matcher, watcher, refresh, and Create fingerprints; exact-byte regressions were added. |
| `c360e8096` | Fresh review found standing-answer fingerprints and the pre-CAS race check still used newline-normalized text. | Standing-answer reads now retain raw bytes, generation fingerprints hash them, and the final race check compares exact bytes with a newline-only regression. |
| `e9602573d` | Fresh review found conflicting duplicate receipts, stale matcher scope, missing Question raw-byte generation binding, and snapshot persistence before retry restoration. | Duplicate receipt payloads now fail closed; matcher scope and refresh generation use fresh exact baselines; watcher scans without persisting until retry restoration is applied. |
| `f9508f065` | Fresh review found event IDs were only checked within one event type and that standing-answer validation had a final check-to-write race. | Event IDs are checked globally; a changed standing answer after pointer write triggers a versioned compensating rollback before the refresh is reported drafted. |
| `2916fc5ce` | Exact-head Sol review found the global event-id check was still read-then-append and non-atomic; a staged draft could be mutated before receipt/replay and receipted with new bytes; rollback silently swallowed a Question CAS conflict. | A shared JSONL append lock now covers every public writer's event-id check and append; integrity-first sidecar publication plus atomic draft replace makes the staging crash window replayable, with pre-receipt/replay raw-byte checks; rollback retries against fresh Question versions and fails loud if it cannot converge. |
| `d6df515ba` | Follow-up Sol review found the first repair still left public JSONL writers without event-id validation and left a crash between draft write and sidecar write permanently stranded. | This repair round moved event-id uniqueness into the shared public writer seam, added an independent-writer collision probe, and changed staging order to integrity-first plus atomic draft replacement, with an explicit crash/replay probe. |
| `4da79b80a174311bf12038b155b46f48239fecd1` | Exact-head Sol review still found three P1s: the legacy writer and path aliases could bypass global event-id uniqueness, outbox read/parse failures could append fail-open, and JSON/delimiter plus draft/sidecar publication were not protected against crash/concurrent-writer residue. | This repair adds one canonical locked JSONL record seam for legacy and event writers, strict fail-closed inspection with complete-tail repair and fsynced single-record append, a draft-scoped publication lock, and parent-directory fsync after atomic draft/sidecar replacement. New focused probes cover each finding and concurrent Create convergence. |
| `f2fb014c21a5d26e4358e7a1bd9b21283508751c` | Exact-head Sol review found a remaining P1: production writers in `app/outbox/events.py`, `app/outbox/legacy_events.py`, `app/watcher/watcher.py`, and `app/watcher/vault_watcher.py` still directly appended to the configured index outbox, bypassing the shared seam and invalidating the all-writer claim. | This repair routes those writers and the adjacent orchestrator writer through `append_jsonl_record(..., require_event_id=True)`, adds direct index-audit and watcher collision probes, and narrows the invariant wording to the configured index-outbox sink rather than unrelated telemetry/queue JSONL files. |
| `f1d487e4aef4ee27263cb9ab2b8e89b6cf64c651` | Fresh exact-head Sol census found two additional configured index-outbox bypasses: settings receipts and worker latency summaries directly appended bytes, leaving the all-writer claim incomplete. | This repair routes settings receipt publication through the shared seam while retaining its durable parent-fsync/readback contract, routes worker latency publication through `append_jsonl_outbox_event`, and also folds the CLI pipe and promotion consumer direct paths into the shared record seam. The focused writer/settings/worker/promotion regression set passed. |
| `d320aef5a13cab9372e7081dd0bb004fd79d41a6` | Fresh exact-head Sol census found the settings once-only lock was still lexical-path based, so real-path and symlink writers could both pass the operation check and append duplicate operation receipts. | This repair canonicalizes the settings receipt path before deriving both the once-only lock and readback path, with a regression asserting alias lock identity. The durable parent-fsync/readback behavior remains intact. |
| `4482d74624c3b8906a9c24331d851231fbb2b7e7` | Fresh exact-head review found settings receipt readback still used a local parser that skipped malformed lines; a valid receipt followed by corrupt JSONL could therefore be accepted and bypass the strict shared reader. | Readback now uses `read_jsonl_outbox_records`, so unreadable or malformed tails fail closed. The regression appends a malformed tail after a valid receipt and proves both readback and once-only retry reject the corrupted sink. |
| `6ea11278ac8997e8d4d390dfa022fdb76ccadd23` | Fresh exact-head Sol review found valid Unicode U+2028 could wedge JSONL parsing; draft replay and expiry could race or leave an expired proposal receipt stranded; and the watcher/matcher admitted a Question note as its own evidence. | JSONL now splits only on the byte newline delimiter; replay and expiry share the draft lock, and an expiry receipt causes a retry to rebuild with a fresh proposal identity; Question-note sources are excluded at both production adapter and matcher boundaries. Focused regressions cover all three repairs. |
| `3c04dc3883c34b5e28eff978496b43b6c99034dd` | Fresh exact-head Sol review found four configured JSONL consumers still used `splitlines()`; expiry authorization matched only draft id and deleted before receipt publication; and Question-note exclusion was bypassable by traversal and persisted source rebuilds. | All configured consumers now use the strict shared reader; expiry receipts precede deletion and bind proposal receipt id plus draft hash, with receipt failure preserving the draft; canonical Question-source exclusion is reapplied to traversal and persisted refs. Focused regressions cover each finding. |
| `2a5322bd9f002dbff09fcc9be2bbff781946e152` | Exact-head review found status event/SLA corruption was collapsed to zero-valued counters. | Status models and orientation now preserve `None`/unknown for unreadable outbox diagnostics, with corruption regression coverage. |
| `dc807116d39a8171266797301344ea842c8d1021` | Exact-head review found an oversized single JSONL record could disappear from a bounded tail as a successful empty read. | The shared bounded reader now raises `JsonlOutboxCorruptionError` when no delimiter exists in the retained tail; status, SLA, and orientation regressions cover the path. |
| `bacc1c150a819b41c404f700e26072bfb3b79a91` | Exact-head review found health-contract dead-letter diagnostics still converted corrupt tails into empty/pass values. | Health contract and CLI now propagate nullable fields and `unknown` status; malformed and oversized health snapshots are covered. |
| `d51a2f497113c5225e8549d37b421b440484c21b` | Exact-head review found the default CLI health outbox check still created a missing parent/file. | CLI health path validation is now non-mutating and has a `run_health` no-parent/no-file regression. |
| `6b99aa53187845678eeaab5cd586511efa19d3f9` | Fresh exact-head review was CLEAN for the cumulative outbox read/append and diagnostic-reader convergence; local CLI collection remained unavailable in the reviewer environment because `lingua` was absent. | No source repair required at that head. The subsequent audit/doc writeback changes require a fresh exact-head review before publication. |
| `e976725fbfb3145296d3f9aace8b6d723a6f356e` | Current-head CI failed before pytest selection because four changed diagnostic surfaces were unowned by `scripts/select_pr_tests.py`; the same run also reported the mirror-census fault-injection gate failure. | Routing repair is staged in the next candidate: shared `app/cli.py` selects the broad suite, events-doctor/legacy outbox select `events_receipts`, and orientation selects `observability`; CI must be rerun on that candidate before closure. |

The first row is sourced from GitHub review comments whose `original_commit_id` is
`0d032250274b54eb62c50e50e436077fb032401a`; the later rows are local independent review receipts
bound to their listed heads. The history does not itself authorize merge or acceptance. The current
exact-head independent review must be clean before selected CI and delivery gates can be treated as
valid.
