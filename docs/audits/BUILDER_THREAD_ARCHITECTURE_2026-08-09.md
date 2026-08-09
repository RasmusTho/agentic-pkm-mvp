State: Advisory architecture and red-team snapshot, 2026-08-09. Evidence baseline: origin/main at d0eb93a149fe2075d673ba09a91921dd4bd0243d. Subordinate to ADR-0010, ADR-0062, the BuilderOps vault-store owner, and live GitHub/delivery authority.
Doc role: Reference (implementation boundary and convergence review)
Authority: Evidence-based Builder System analysis only; Issue #4702 governs delivery. Draft PR
#4701 is the rejected prose-only predecessor and is not acceptance evidence.
Owner: BuilderOps governance
Temporal class: Point-in-time audit

# Builder Thread executable boundary review

## Question

What is the smallest cross-device exchange that lets Codex and Claude Code leave one attributed
question and receive a reply without creating another notes system, backlog, review lane, or
authority?

## Red-Team Verdict

The original prose-only deliberation skills were rejected. They named JCS, hard links, fsync,
conflict handling, and derived state without implementing any of them; string-presence tests could
not prove cross-device safety. The long skill names were also poor operator vocabulary and the
global discovery hooks duplicated normal delivery checkpoints.

The governing repair design is an issue-backed executable vertical slice:

- builder-thread owns explicit create/read/reply/close/archive/quarantine operations;
- builder-inbox owns read-only recipient and health views;
- app/builderops/builder_threads.py is the executable file contract;
- immutable canonical JSON envelopes are content-addressed;
- clients pin one immutable vault genesis UUID;
- shared_non_sensitive is the only privacy class;
- inbox state is reconstructed and never stored as authority.

## Authority Baseline

ADR-0010 keeps BuilderOps operating artifacts separate from repository and Product/Runtime truth.
ADR-0062 leaves GitHub, Git, CI, review, merge, dispatchers, approvals, and receipts authoritative.
The existing BuilderOps vault store already permits a dedicated shared Markdown/artifact root while
forbidding SQLite, credentials, and distributed-lock claims there. Model Inquiry supplies the
file-first no-overwrite precedent but does not own this simpler exchange.

A Builder Thread never creates or gates Issue, PR, Verify, CI, review, merge, closure, owner
decision, design, promotion, or receipt state. AgentWorklog remains the canonical monologic work-note
surface.

## Mechanism Convergence Packet

| Surface | Contract |
| --- | --- |
| Genesis | Explicit first adoption installs one immutable `.builderops/vault-genesis.json`; `builder-threads/genesis.json` must match it byte-for-byte. Every client supplies the expected UUID and every operation verifies both. Routine init never self-attests an unmarked root. |
| Contribution identity | Thread UUID is deterministically derived from vault ID plus capture key; entry IDs are UUIDv4; each filename equals SHA-256 of the complete canonical JSON envelope. One visible immutable entry-claim manifest atomically binds each entry ID to exactly one thread and one semantic-request digest before contribution publication. |
| Privacy | Only shared_non_sensitive; strict subject/content/ref/entry/output bounds and obvious credential, argv/env/stderr, and raw-private-path refusals. |
| Capture | Named recipient, reply_expected=true, typed authority-safe refs, and deterministic duplicate representation refusal. |
| Publication | Same-directory exclusive temp, file fsync, no-overwrite hard link, directory fsync, readback, temp unlink, second directory fsync. |
| Concurrency | No sequence, mutable head, shared lock, SQLite, or hidden index. The visible entry claim, a new deterministic thread destination, and each of its 128 entry slots are claimed create-if-absent and never overwritten. Independent contributions converge by set; duplicate IDs or incompatible dispositions fail closed. |
| Validation | Root/scaffold/genesis confinement plus no symlink, SQLite, conflict copy, temp/partial, unknown field/schema/path, hash mismatch, dangling lineage, or replay conflict. |
| Recovery | Caller-retained IDs for every mutation make semantic acknowledgement-loss retries idempotent. A claim-only or claim-plus-slot process death is reader-visible incomplete state and exact-writer recoverable. Exact committed temp twins and installed-final reservations are cleanup-recoverable by writers only after claim and bytes agree. Stale close/archive entries are superseded through immutable lineage. A structurally valid privacy-unsafe or conflicting disposition can receive an explicit hash-bound quarantine contribution; bytes remain immutable and normal output redacts them. Structural corruption remains a hard refusal. |
| Derived state | open, answered, closed, archived, needs_review, or quarantined, rebuilt from validated contributions. Inbox/health has a deterministic snapshot hash and no write path. |

Stable mechanism/domain key: `builder-thread/artifact-publication-and-reduction-v1`. The protected
invariant is that every healthy receiver sees one pinned vault identity, at most one represented
thread per capture key, a complete immutable contribution set, and at most one current close and
archive disposition. No artifact grants delivery authority.

### States and transitions

- Valid working states are `open`, `answered`, `needs_review`, and `quarantined`. Valid terminal
  states are `closed` and `archived`; late activity deterministically returns a terminal snapshot to
  `needs_review`.
- Indeterminate states are wrong/missing genesis, active or unmatched orphaned temp artifacts, unknown paths
  or fields, non-canonical or partial JSON, bad hashes, duplicate capture/entry identity, dangling
  lineage, and multiple current dispositions. Reads fail closed rather than projecting an empty or
  healthy inbox.
- Compensated state is an explicit quarantine contribution targeting one exact structurally valid
  artifact. It can remove unsafe bytes or one conflicting disposition
  from normal reduction without deleting history. A `concurrent_conflict` disposition may target
  one quarantine decision so its sibling remains effective. It cannot compensate for structural
  corruption, wrong identity, or an incomplete directory tree.
- `create` is the only writer of an open contribution. `reply` requires the actor to equal the named
  recipient on its parent. `close` snapshots all prior hashes and may target the current close to
  supersede it. `archive` targets the current fresh close and may parent the current archive to
  supersede it. `quarantine` targets one prior artifact. Inbox/list/read/health have no writer.

### Durability, concurrency, and recovery ordering

Genesis and ordinary contributions use `exclusive temp -> bytes -> file fsync -> no-overwrite hard
link -> parent fsync -> final readback -> temp unlink -> parent fsync`. Any failed sync, unlink, link,
or readback returns failure even when the final name may already exist. Before a mutation retry, the
writer may remove a leftover temp only when it is a regular file whose installed final has identical
bytes (and, for a contribution, the expected content hash); the retry then revalidates the installed
entry. Read-only operations never clean it.

Initial thread publication uses `create deterministic destination if absent -> parent fsync ->
create entries directory -> parent fsync -> reserve one of 128 slots if absent -> parent fsync ->
atomic entry publication`. Readers wait only for the bounded live-install/temp window, never accept
a partial tree, and reject an orphan after that window. A pre-existing empty destination is left
untouched. Two identical captures converge on one deterministic destination; one wins and the other
returns a typed already-represented conflict. Different captures have independent destinations.
There is deliberately no cross-device lock:
iCloud conflict copies, duplicate capture keys, and incompatible current dispositions remain
receiver-visible conflicts.

Every mutation caller retains one UUIDv4 entry ID until readback. Its immutable claim binds the
thread plus a digest of all semantic retry fields; the generated timestamp is excluded only from
retry comparison, and the original installed timestamp is returned. Each thread has 128 immutable
entry slots. An identity marker makes a claim-plus-slot process-death window recoverable only by the
exact writer. Reservation precedes durable JSON publication, so one of two concurrent boundary
writers succeeds and the other fails without writing contribution bytes; every later 129th append
is likewise non-mutating. Quarantine entries do not recursively grow on ordinary review and remain
one explicit mutation per target/incident.

Startup and every operation revalidate all existing path components for symlinks, the two genesis
envelopes, the strict artifact tree, privacy/type/size bounds, content hashes, capture uniqueness,
lineage, and state. Static symlink confinement is guaranteed; a malicious same-host path swap
between system calls remains outside the single-operator threat model. SQLite scanning uses local
content metadata so ordinary evicted iCloud notes are not materialized merely for Builder Thread
health.

### Prior findings and convergence test matrix

The first independent review of SHA `c728e815f1c13c0505ef80f5e85aac945166ecba` found the same
mechanism-key blockers: check-then-act duplicate capture, visible partial scaffold, stale-close
dead-end, incomplete private-path/type/confinement validation, foreign-recipient reply completion,
suppressed cleanup-sync failure, self-attested root, and incompatible retry acceptance. That SHA is
rejected evidence. The repaired publishable SHA must receive a fresh independent convergence review
before affected-surface validation.

The next convergence review rejected SHA `3e1c9e26cb42277585396b1239e7569cabbc5a67`
for missing CLI idempotency input, unrecoverable committed-temp cleanup residue, concurrent
active-bound overflow, concurrent quarantine-decision conflicts, receiver-side reply binding gaps,
two privacy variants, and a plain docs-guard failure. That SHA is also rejected evidence. The next
review must reproduce the new CLI retries, cleanup recovery, pre-publication entry bound,
quarantine-conflict recovery, receiver validation, privacy variants, and plain docs guard on the
exact repaired SHA.

The following review rejected SHA `94bdd49964b0733ae47d60afa16fe7c2b754f21c`
for optional service request identities, thread-local rather than vault-wide entry-ID uniqueness,
pre-identity temp cleanup, lone-quarantine neutralization, remaining absolute-POSIX-path variants,
and non-total JSON error handling for storage and group-usage failures. That SHA is rejected
evidence. The next review must reproduce service and CLI acknowledgement-loss retry, global ID
conflict, genesis-first non-mutation, real-sibling quarantine recovery, the expanded privacy matrix,
and bounded JSON for both storage and unknown-command failures on the exact repaired SHA.

Review of SHA `5c3e3ed663e0c8be45befe23f1b4a4e48f9ff639` then found that exact-thread
operations bypassed global duplicate-ID validation and synchronized cross-thread reuse could persist
two contributions before post-write refusal. It also found hostile command names echoed through JSON,
URL query/userinfo, network/Windows/encoded-path privacy variants, and `concurrent_conflict` accepted
against a lone non-disposition artifact. That SHA is rejected evidence. The repaired mechanism adds
the visible atomic entry-claim manifest, enforces it on every read/write path, redacts usage failures,
and expands the privacy and disposition-sibling probes before another exact-SHA review.

Review of SHA `616a8cfd0b6835979420a4f50f8fcad08d57dd6a` found that the global claim did
not bind request semantics in a claim-only crash window, non-create mutations lacked caller-owned
request identity, a claim-plus-empty-slot process death was not recoverable, one recognized temp
cleanup race could be misclassified, path configuration could escape the JSON boundary, and the
privacy normalizer missed encoded, Unicode-separator, Windows/UNC, URL-credential, and common token
forms. That SHA is rejected evidence. The repaired mechanism binds a timestamp-excluded request
digest for every contribution kind, retains identity-marked slots until final installation,
normalizes privacy input with bounded decoding, and exercises every mutation crash/retry path.

| Invariant / transition / crash point | Focused proof |
| --- | --- |
| Pinned root and subsystem genesis; explicit adoption; symlink ancestors; partial/mismatched non-mutation | `test_root_and_genesis_validation_fail_closed`, `test_genesis_pair_refusal_is_non_mutating` |
| Wrong pin or mismatched genesis cannot clean a committed temp twin | `test_wrong_identity_never_cleans_committed_temp_twins` |
| Unknown, partial, conflict-copy, symlink, hash, and SQLite refusal | `test_validator_rejects_unknown_partial_conflict_and_sqlite_artifacts` |
| Every envelope field is typed; hostile filenames are not echoed | `test_malformed_field_types_and_hostile_filenames_fail_typed_and_redacted` |
| Concurrent identical capture and independent reply convergence; entry replay | `test_concurrent_writers_and_replay_conflicts_converge_fail_closed` |
| Concurrent exact entry-ID retry installs one physical envelope | `test_concurrent_exact_entry_retry_reserves_one_physical_artifact` |
| Reader cannot observe a partial final initial tree; pre-existing destination is untouched | `test_initial_thread_tree_is_atomically_visible_to_readers`, `test_preexisting_empty_thread_destination_is_untouched` |
| Late activity, superseding close/archive, incompatible disposition retry | `test_stale_dispositions_can_be_superseded_and_retries_conflict` |
| File/link/fsync ordering and final cleanup-sync failure | `test_atomic_publication_uses_fsynced_temp_and_no_overwrite_link`, `test_atomic_publication_reports_final_directory_sync_failure_and_retries` |
| Post-publication acknowledgement loss and exact recovery | `test_create_acknowledgement_loss_reconciles_on_exact_retry` |
| Supported CLI mutation lost-ack retry, total init/config JSON, and typed bounded failures | `test_cli_round_trip_covers_complete_thread_surface`, `test_cli_json_failures_are_typed_bounded_and_retry_conflicts_do_not_append` |
| Public service requires caller-owned request identity for every mutation; entry ID is unique vault-wide | `test_public_service_requires_request_identity_and_retries_exactly`, `test_entry_id_is_unique_across_the_entire_vault` |
| Claim-plus-slot process death and changed-semantics retry for each append mutation | `test_all_append_mutations_recover_exactly_after_claim_and_slot_crash` |
| Concurrent cross-thread ID reuse has one claim winner; claim-only crash supports exact recovery | `test_concurrent_cross_thread_entry_id_claim_allows_one_winner`, `test_claim_only_crash_is_recovered_by_exact_create_retry` |
| Temp-unlink failure, exact twin cleanup, later writer retry, and vanishing recognized-temp race | `test_temp_unlink_failure_is_recovered_by_exact_writer_retry`, `test_reader_tolerates_only_a_recognized_temp_that_vanishes_during_walk` |
| Concurrent contradictory quarantine decisions and decision quarantine recovery | `test_concurrent_quarantine_conflict_fails_closed_and_is_recoverable` |
| A lone quarantine decision cannot be neutralized as a concurrent conflict | `test_single_quarantine_decision_cannot_be_neutralized_as_concurrent` |
| Concurrent 128-entry boundary reservation and non-mutating 129th refusal | `test_entry_bound_is_reserved_before_publication_and_129th_is_non_mutating` |
| Privacy patterns, actor identity, capture gate, bounds | `test_capture_gate_and_shared_non_sensitive_privacy_boundary` |
| Recipient-bound answer plus immutable/idempotent inbox | `test_inbox_is_bounded_read_only_and_idempotent` |
| Structurally valid privacy incidents, unsafe identity/ref redaction, and incompatible quarantine retry | `test_quarantine_preserves_bytes_and_redacts_unsafe_artifact`, `test_structural_quarantine_recovers_privacy_unsafe_identity_and_refs`, `test_structural_quarantine_redacts_unsafe_open_source_ref` |
| Recomputed capture key and active-close archive targeting | `test_receiver_recomputes_capture_key_and_rejects_non_active_archive_target` |

## Workflow Simplification

- The existing no-PR analysis checkpoint routes monologic material to AgentWorklog and invokes a
  thread only for the three-part capture gate.
- Resume reads one exact Builder-Thread-Ref already present in handoff/current context; it does not
  search broadly.
- Epic delivery performs at most one explicit/configured read-only inbox scan at intake, not closure.
- Verification reads only an explicit Builder-Thread-Ref and never mutates or gates.
- Inbox review is explicit or automation-configured and remains separate from learning retrospective.
- No automatic session capture is allowed.

## devUI Reconciliation

The delivered read-only Focus composer and external Conversation Port contract on current main are
adjacent but separate. The port is an isolated, user-mediated external conversation flow; it does
not ingest Builder Thread artifacts or authorize a Builder Thread provider. This slice adds no
devUI provider, ingestion, session inventory, command, persistence, or UI. A future read-only
contribution may consume bounded Builder Thread summaries only through a separate governed
specification that preserves provider isolation and projection-only authority.

## Test Map

- tests/builderops/test_builder_threads.py exercises root/genesis refusal, complete CLI lifecycle,
  privacy/capture bounds, content-addressed replay, concurrent writers, no-overwrite publication,
  unsafe-artifact quarantine, and read-only inbox idempotence.
- tests/architecture/test_agent_skill_entrypoints.py enforces portable names, executable routing,
  shared-contract linkage, simplified hooks, AgentWorklog separation, and absence of the rejected
  names.

## Residual Risk

iCloud remains a synchronized artifact transport, not a distributed lock. A malicious same-host
process can still swap path components between checks; the single-operator trust model does not add
a filesystem broker. Any synchronized conflict remains visible and blocks state reduction.
