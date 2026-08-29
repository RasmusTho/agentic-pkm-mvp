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
- Receipt event IDs are globally unique across event types; conflicting duplicates fail closed.
- A standing-answer edit detected after the Question pointer write triggers a guarded rollback of the
  pointer and refresh timestamp, preserving fail-closed semantics for the external-file race.

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
4. Run Create and write the deterministic staged draft id.
5. Emit/reuse the deterministic `expansion.create.proposed` receipt id.
6. Apply the Question update with exact-byte CAS.

If the process dies before the CAS, the deterministic draft/receipt pair is reused for the same
`question_id` plus exact evidence-generation fingerprint. The draft is not rewritten, and a reused
receipt must match both the draft byte hash and its full payload. If CAS conflicts, the retry re-reads
the Question; unchanged evidence reuses the one logical proposal, while newly appended evidence gets
a distinct generation identity rather than silently changing an old receipted draft. If source bytes
no longer match their recorded content hash, replay fails closed. If watcher composition raises or
returns structured `blocked`, the changed observation is retained for the next unchanged tick.

## Locks and races

Each Question refresh holds a process-local re-entrant lock plus an OS `flock` for the full
read/check/Create/CAS sequence. The QuestionStore guarded seam owns exact-byte conditional writes.
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
| Contradiction basis is exact or unknown | `test_invalid_contradiction_basis_degrades_to_unknown`, `test_refresh_marks_contradiction` | Passed |
| Human fields remain protected | QuestionStore CAS and human-field tests | Passed |
| Evidence entries carry content identity | `test_relevant_artifact_attaches_irrelevant_does_not` | Passed |
| Focused SQ/Create regression set | Standing Questions, Create lifecycle, and QuestionStore tests | `148 passed` |
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

The full not-PostgreSQL suite was not a valid local proof at packet creation: the host-global
`pytest-not-pg` lease was unavailable and the local watcher collection also lacked the declared
`lingua` dependency. CI remains the authoritative environment for that selected suite; the focused
watcher tests use the same production tick seam but are not a substitute for that environment proof.
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

The first row is sourced from GitHub review comments whose `original_commit_id` is
`0d032250274b54eb62c50e50e436077fb032401a`; the later rows are local independent review receipts
bound to their listed heads. The history does not itself authorize merge or acceptance. The current
exact-head independent review must be clean before selected CI and delivery gates can be treated as
valid.
