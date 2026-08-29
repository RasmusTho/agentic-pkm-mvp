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
- Evidence identity is the judged content, not a mutable path alone; a changed source is blocked.
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
- `conflict`: the Question bytes changed during cognition; the refresh retries the same logical
  generation rather than publishing stale state.

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
`question_id` plus unconsumed `last_refreshed_at` generation. If CAS conflicts, the retry re-reads
the Question and either defers to an existing pending candidate or repeats the logical proposal
without creating a duplicate. If source bytes no longer match their recorded content hash, replay
fails closed. If watcher composition raises or returns structured `blocked`, the changed observation
is retained for the next unchanged tick.

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
| Focused SQ/Create regression set | Standing Questions, Create lifecycle, and QuestionStore tests | `133 passed` |

The full not-PostgreSQL suite was not a valid local proof at packet creation: the host-global
`pytest-not-pg` lease was unavailable and the local watcher collection also lacked the declared
`lingua` dependency. CI remains the authoritative environment for that selected suite. Live test,
Playwright/browser proof, owner observation, and SQ-05 acceptance remain unclaimed and are not
silently promoted by this packet.
