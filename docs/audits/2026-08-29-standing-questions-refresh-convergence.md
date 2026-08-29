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
- Evidence identity is the judged content, not a mutable path alone; a changed source is blocked and
  hashless legacy evidence is rejected until an explicit backfill binds historical bytes.
- Watcher delivery is retryable: exception and structured-blocked refresh outcomes preserve the source
  observation instead of advancing the snapshot as if the capability succeeded.

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

1. Read the Question and evidence entries; resolve source bytes and verify each stored content hash.
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
| Focused SQ/Create regression set | Standing Questions, Create lifecycle, and QuestionStore tests | `136 passed` |
| Matcher CAS conflict is observable and non-clobbering | `test_match_write_conflict_does_not_clobber_question` | Passed |
| Deterministic replay preserves draft bytes and receipt payload | `test_refresh_replay_reuses_draft_and_receipt_bytes` | Passed |
| Matcher CAS conflict remains watcher-retryable | `test_watcher_retries_standing_questions_matching_conflict_before_advancing_snapshot` | Passed in CI-selected watcher coverage; local collection is dependency-blocked |

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
| `3627cec12` | No production match-then-refresh caller; cognition was initially given a provenance URI as an object id; CAS baseline was captured too late. | Production watcher composition, reasoning-input materialization, and pre-cognition Question version capture were added before the next review. |
| `2f042410b` | Watcher SQ failure could advance the source snapshot; static property registrations drifted after watcher hydration moved. | Exception retry preservation was added; the census was repinned at the actual sink/producer lines. |
| `1bca186bd` | Structured blocked results were treated as success; CAS retry could orphan/duplicate draft and receipt; mutable path could replay changed evidence; contradiction basis was only nonempty; registry rows were missing. | Blocked-result retry, deterministic proposal identity, source content hashes, exact contradiction basis, and registry entries were added. |
| `bcf0f2120` | Replay did not compare full receipt payload; standing-answer bytes were outside the refresh identity; SQ-03 append lacked a fresh duplicate fold; matcher CAS conflicts were not watcher-retryable; docs overstated lifecycle. | Full payload/byte parity, standing-answer fingerprinting, post-read duplicate filtering, matcher conflict retry, and lifecycle/doc corrections were added in the current repair. |

This history does not itself authorize merge or acceptance. The current exact-head independent review
must be clean before selected CI and delivery gates can be treated as valid.
