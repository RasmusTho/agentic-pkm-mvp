State: Target-state specification under serial delivery (parent #4349). EROJ-01 (#4350, committed operation identity + atomic event commit + fresh-visibility fence) is implemented; EROJ-02 (#4351) and EROJ-03 (#4352) are not yet implemented and their recovery guarantees are not claimed.
Doc role: Specification directory (capability breakdown)
Authority: Owns the bounded implementation order, cross-task recovery invariants, and acceptance path for crash-safe entity-review merge application. Subordinate to ADR-0049 and the Mimer entity-register contracts for semantic authority, `docs/EVENTS.md` for event authority, and the runtime correctness kernel for multi-store ordering.
Owner: Product/Runtime — Mimer identity resolution, with PDM persistence and OEF outbox participation
Temporal class: target-state delivery contract
Review cadence: event-driven (filing, each child merge, terminal acceptance)
Source of truth: this directory for task shape; the owner documents named above for current authority and shipped behavior
Last reviewed: 2026-07-31

# Entity-Review Operation Journal

The current entity-review application path folds the human-authored decision history in
`entities/review.md`, applies a merge to the markdown-built entity register, and then removes the
queue entry from `pending`. A stopped implementation attempt under
[#4253](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4253) proved that making those actions
restart-safe is not one bounded bug fix. Three protected failure mechanisms remained after its 2+2
repair budget was exhausted:

1. a register merge could exist without its outbox event, then later target evolution could strand
   recovery or rewrite the original merge meaning;
2. a crash during a later split could create duplicate target-side complements that the old
   source/target-only validation falsely accepted; and
3. a caller-owned transaction could expose an uncommitted outbox row to the same connection, permit
   `pending` to be cleared, and then roll the event back.

This directory replaces that exhausted implementation attempt with exactly three serial,
independently verifiable tasks. It specifies one narrow entity-review operation journal and the
minimum register lineage needed to make the existing markdown authority recoverable. It does not
introduce a generic saga framework, graph store, event store, queue, service, or new UI.

## Classification and authority boundary

**Change classification:** target-state delivery contract under serial implementation. EROJ-01's
journal and committed-visibility fence are shipped (#4350); the EROJ-02 lineage fields and EROJ-03
complement identities are not shipped and are not claimed.

**SBS classification:** Product/Runtime.

- **Primary:** SIP / Mimer entity identity — human decisions and markdown entity notes remain
  semantic authority.
- **Secondary:** PDM — the Postgres journal is operational coordination state; OEF — the existing DB
  outbox remains the canonical event queue; GOV/HKA — governed writes and client surfaces retain
  their existing authority boundaries.

The journal never decides that two entities are the same. A Bifrost/iPad action is a proposal-bound
approval, rejection, or permitted pre-application undo; the Hub alone canonicalizes an approval
into a merge operation, mutates the register, and records the durable outcome. The journal records
that Hub execution, which deterministic register effects belong to it, and whether its event is
committed and externally visible. `entities/review.md` remains the human decision history;
`_heimdal/register/*.md` remains canonical identity truth; Postgres state remains operational and
rebuildable, not cognition.

## Fixed scope

| Order | Task | Outcome |
| --- | --- | --- |
| 1 | [COMMIT_OPERATION_AND_OUTBOX_VISIBILITY.md](COMMIT_OPERATION_AND_OUTBOX_VISIBILITY.md) (EROJ-01) | Canonicalize a proposal-bound client approval in the Hub, bind its merge to a durable operation, atomically commit operation/event evidence, and require fresh visibility before clearing `pending`. |
| 2 | [PRESERVE_TARGET_EVOLUTION_LINEAGE.md](PRESERVE_TARGET_EVOLUTION_LINEAGE.md) (EROJ-02) | Preserve the original decision pair across later governed target merge/split evolution and recover its one original event without graph-only inference. |
| 3 | [GUARANTEE_GLOBALLY_UNIQUE_SPLIT_COMPLEMENTS.md](GUARANTEE_GLOBALLY_UNIQUE_SPLIT_COMPLEMENTS.md) (EROJ-03) | Give every source-redirect/target-complement pair one globally unique identity and make repeated split recovery deterministic and fail-loud. |

The implementation chain is strictly serial:

```text
EROJ-01 committed visibility
  -> EROJ-02 target-evolution lineage
    -> EROJ-03 globally unique complements and split recovery
```

Only EROJ-01 may be `agent:ready` after strict issue-contract validation. The parent validation hub,
EROJ-02, and EROJ-03 stay `agent:blocked` until their immediately preceding acceptance receipt is
recorded. No work in this chain is safe to parallelize.

## Cross-Task Invariants / Interaction Safety

- **INV-EROJ-1 — authority does not move.** A client may submit approval, rejection, or permitted
  pre-application undo for a displayed proposal, but the Hub alone canonicalizes an approval into
  an executable merge operation, mutates the register, and records the outcome. A journal row may
  reference that review signal and markdown effects; it may not create, amend, rank, or reinterpret
  the decision. Entity notes remain canonical. Outbox rows and journal rows are operational evidence
  only.
- **INV-EROJ-2 — one immutable operation identity.** The active vault identity, queue entry id,
  decision-list position, canonical digest of the exact decision mapping, original `from_id`, and
  original `into_id` determine one operation id. A retry reuses it. A different decision mapping or
  vault cannot collide with it.
- **INV-EROJ-3 — committed visibility before terminal clear.** A merge queue entry may leave
  `pending` only after a fresh database connection/transaction observes both the terminal journal
  state and the matching committed outbox row. Visibility on the writer's or caller's uncommitted
  transaction is never sufficient.
- **INV-EROJ-4 — original meaning is immutable.** The
  `heimdal.register.entity.merged` event for an entity-review operation always reports the original
  human-decided `{from_id, into_id}` plus its operation id. Later redirects or splits may determine
  where those identities resolve now, but may not rewrite the event into a different merge.
- **INV-EROJ-5 — effects are exact and complement-paired.** A source redirect and its target-side
  complement describe one relation, not two independent observations. Once EROJ-03 lands, their
  shared complement id is globally unique across the active register and is the only proof that
  split recovery may consume.
- **INV-EROJ-6 — ambiguity fails closed.** Missing schema, malformed journal data, a changed decision
  digest, unknown or cyclic lineage, duplicate complement ids, or contradictory source/target notes
  leaves the decision history unchanged and the queue entry pending. Recovery never guesses from
  aliases, labels, timestamps, or current graph shape.
- **INV-EROJ-7 — each serial stopping point is safe.** EROJ-01 refuses target-evolved recovery that
  it cannot prove. EROJ-02 refuses repeated/ambiguous split recovery that lacks unique complements.
  EROJ-03 resolves that final refusal. A partial chain may reduce availability; it may not claim
  success or clear `pending` unsafely.
- **INV-EROJ-8 — invariant and producers land together.** Every new required schema/note field is
  supplied by Alembic/bootstrap assertions, existing-resource migration or fail-loud compatibility
  preflight, every production merge/split producer, and in-process fixtures in the same child PR.
  No runtime precondition may land ahead of its producers.
- **INV-EROJ-9 — no speculative substrate.** The implementation stays on the existing
  `EntityRegister`, entity-confirmation applicator, governed note-write seam, Alembic, and DB outbox.
  It may add only the journal table/module and the concrete note fields needed by these three tasks.

## Cross-task partial-failure matrix

| Failure point | Durable evidence required after restart | Required next action | Forbidden outcome |
| --- | --- | --- | --- |
| Operation committed, no register write yet | One non-terminal operation with exact decision digest | Resume the same operation id | Mint a second operation or clear `pending` |
| Source redirect written, target complement absent | Operation plus source-side effect identity | Repair/complete the matching target side or fail closed | Treat the source redirect alone as a complete merge |
| Both register effects exist, event transaction not committed | Operation and exact register-effect proof | Commit one event for the original pair, then verify it freshly | Infer a different pair from the current redirect target |
| Event/journal commit succeeds, process stops before queue write | Fresh transaction sees both rows | Remove only that operation's queue entry, preserving decisions | Emit a second event |
| Target evolves before original event recovery | Operation retains original pair; EROJ-02 lineage proves the governed evolution | Emit the original pair once and retain current-resolution lineage | Rewrite `{from_id, into_id}` to the evolved endpoint |
| First split completes partly, retry begins | Split plan/checkpoint and stable complement ids identify exact completed effects | Resume only missing effects | Create a second complement for the same relation |
| Second split exposes duplicate/legacy-ambiguous complements | Global preflight identifies collision before terminal acceptance | Leave operation open and `pending` unchanged with repair guidance | Certify graph shape by source/target membership alone |
| Caller transaction sees its own outbox insert then rolls back | Fresh visibility check sees no committed event | Keep `pending`; retry the same operation | Clear `pending` based on same-connection visibility |

## Capability acceptance criteria

- [ ] A caller-owned transaction cannot make an uncommitted operation/event authorize queue clear;
      the retry commits exactly one visible merge event.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_caller_transaction_rollback_cannot_clear_pending_or_hide_merge_event`
- [ ] A client approval for a displayed proposal is canonicalized by the Hub before any register
      mutation; no client record is itself treated as a merge command.
      Verify: `tests/heimdal/test_entity_confirm.py::test_client_approval_is_canonicalized_by_hub_before_merge_execution`
- [ ] A register effect followed by target evolution still recovers exactly one event containing the
      original human-decided pair.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_eventless_merge_then_target_merge_backfills_original_event`
- [ ] Repeated split recovery, including a crash during a second split, produces no duplicate
      complement identity and cannot be falsely accepted from source/target shape alone.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_pending_clear_waits_for_unique_split_recovery`
- [ ] The journal schema is migration-owned, assert-only outside tests, and parity-checked with every
      producer/fixture updated.
      Verify: `tests/migrations/test_entity_review_operation_journal_schema_parity.py::test_entity_review_operation_journal_schema_matches_head`
- [ ] Current-state owners describe the delivered mechanism only after all three children pass; the
      implementation PR that first changes each contract updates that owner in the same PR.
      Verify: doc writeback at `docs/DB_SCHEMA.md :: Source Of Truth`,
      `docs/EVENTS.md :: heimdal.register.entity.merged`,
      `docs/MIMER_IPAD_THINKING_CANVAS/SIDE_BY_SIDE_ENTITY_CONFIRMATION_ON_IPAD.md :: What This Task Does`,
      and `docs/STATUS.md :: Runtime verification`

## Acceptance and handoff path

Each child implementation PR records its exact focused-test results, current-SHA CI, migration and
producer coverage where applicable, owner-doc result, and a short handoff receipt on the parent
feature issue. Because every child touches data durability, state-machine recovery, and/or
concurrency-sensitive multi-store writes, the full Tier-3 delivery path applies: independent local
review plus current-SHA CI and verified merge. Use two final review rounds when a repair changes the
same stateful mechanism; apply the mechanism-level convergence gate before another expensive proof
cycle if the repository contract triggers it.

Parent acceptance occurs only after EROJ-03 and a terminal replay covering every row of the
partial-failure matrix. The terminal receipt names the exact implementation SHAs and proves that
`entities/review.md` decision history and entity notes remain authoritative.

## Relationship to GitHub issues

Parent validation hub
[#4349](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4349) is `agent:blocked` and is never a
pickup issue. [PARENT_FEATURE_ISSUE.md](PARENT_FEATURE_ISSUE.md) is its local contract and pointer.

The strict serial children are:

1. EROJ-01 — [#4350](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4350) —
   [COMMIT_OPERATION_AND_OUTBOX_VISIBILITY.md](COMMIT_OPERATION_AND_OUTBOX_VISIBILITY.md),
   `agent:ready`.
2. EROJ-02 — [#4351](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4351) —
   [PRESERVE_TARGET_EVOLUTION_LINEAGE.md](PRESERVE_TARGET_EVOLUTION_LINEAGE.md),
   `agent:blocked` pending the accepted EROJ-01 parent receipt.
3. EROJ-03 — [#4352](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4352) —
   [GUARANTEE_GLOBALLY_UNIQUE_SPLIT_COMPLEMENTS.md](GUARANTEE_GLOBALLY_UNIQUE_SPLIT_COMPLEMENTS.md),
   `agent:blocked` pending the accepted EROJ-02 parent receipt.

[#4253](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4253) is exhausted/superseded evidence,
not an implementation prerequisite and not a task to reopen. Its stopped branch and unpushed code
are not an implementation base for these children.

## Out of scope

- Reopening, repairing, or merging the stopped #4253 implementation.
- A generic workflow engine, saga framework, graph database, event store, second outbox, background
  worker, API, UI, or queue.
- Automatic identity decisions, changing confidence thresholds, or changing the human decision-note
  shape beyond the exact immutable binding needed by the journal.
- Rebuilding all historical entity lineage. EROJ-03 covers only deterministic compatibility for
  existing redirect/complement pairs and fails loud on ambiguity.
- Treating DB state as semantic authority or deleting append-only human decision history.

## Source documents

- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
- `docs/adr/ADR-0055-multi-writer-consistency-and-conflict-model.md`
- `docs/MIMER_IPAD_THINKING_CANVAS/SIDE_BY_SIDE_ENTITY_CONFIRMATION_ON_IPAD.md`
- `docs/HEIMDAL/FABLE_COMPANION.md`
- `docs/HEIMDAL/ENTITY_IDENTIFICATION_RESEARCH.md`
- `docs/contracts/MIMER_CLIENT_CONTRACT.md`
- `docs/EVENTS.md`
- `docs/DB_SCHEMA.md`
- `docs/CONCURRENCY.md`
- `docs/RUNTIME_CORRECTNESS_KERNEL/TRANSACTIONAL_VAULT_SYNC.md`
- `docs/RUNTIME_CORRECTNESS_KERNEL/README.md`
