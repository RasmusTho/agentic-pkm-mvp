State: Filed as live validation hub #4349 (`agent:blocked`) on 2026-07-29. Children #4350–#4352 form the strict serial execution chain.
Doc role: Parent feature issue contract
Authority: Owns the capability-level acceptance ledger for `docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md`; it is never an implementation pickup.
Owner: Product/Runtime — Mimer identity resolution
Temporal class: active delivery contract
Review cadence: event-driven (filing, child handoffs, terminal acceptance)
Source of truth: `docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md`
Last reviewed: 2026-07-29

# Parent feature issue — crash-safe entity-review operation journal

Live issue: [#4349](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4349),
`feature: establish a crash-safe entity-review operation journal`.

Live labels: `type:feature`, `prio:high`, `agent:blocked`. The parent is a validation hub, never a
pickup issue.

## Context

The current entity-review applicator can mutate the markdown entity register, emit an outbox event,
and clear the human review queue across separate persistence surfaces. Issue #4253 attempted to make
that path restart-safe, but its 2+2 repair budget was exhausted after an independent mechanism review
found three protected failures: same-transaction outbox visibility could authorize a clear before
rollback; later target evolution could strand the original event; and repeated split recovery could
create duplicate complements that source/target-only validation accepted.

`docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md` converts that stopped evidence into three serial,
bounded contracts. This parent is their validation hub, not a pickup issue.

## Scope

Deliver one narrow operation journal for entity-review merge application, preserve the original
decision pair through target evolution, and give split complements globally unique identities with
deterministic recovery. Keep human decisions and markdown entity notes authoritative.

## Source Anchors

- `docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md :: Cross-Task Invariants / Interaction Safety`
- `docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md :: Cross-task partial-failure matrix`
- `docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md :: Capability acceptance criteria`
- `docs/MIMER_IPAD_THINKING_CANVAS/SIDE_BY_SIDE_ENTITY_CONFIRMATION_ON_IPAD.md :: Human flow`
- `docs/EVENTS.md :: heimdal.register.entity.merged`

## SBS Impact

- Primary subsystem: Product/Runtime SIP / Mimer entity identity
- Secondary subsystem(s): PDM migration-owned operational journal; OEF canonical DB outbox;
  GOV/HKA governed note-write and client-authority boundaries
- Write class: authority-adjacent operational coordination
- Authority impact: no semantic authority moves. The journal records execution of the exact
  human-authored decision; markdown entity notes remain canonical identity truth.

## Constraints

- Execute EROJ-01 → EROJ-02 → EROJ-03 serially; no parallel implementation.
- Preserve INV-EROJ-1 through INV-EROJ-9 and every partial-failure outcome in the specification.
- Clear `pending` only after a fresh database transaction observes the terminal journal row and
  matching committed outbox event.
- Keep the original human-decided `{from_id, into_id}` immutable across later lineage evolution.
- Add every invariant, producer, existing-resource compatibility path, and fixture in the same child.
- Add no generic saga, graph, queue, service, event-store, or UI abstraction.
- #4253 remains exhausted/superseded evidence; do not reopen or reuse its stopped implementation.

## Acceptance Criteria

- [ ] The three child issues are delivered in order and each posts focused-test, current-SHA CI,
      independent-review, owner-doc, and handoff receipts on this parent.
      Verify: parent issue checklist links accepted EROJ-01, EROJ-02, and EROJ-03 receipts
- [ ] A caller transaction rollback cannot clear the queue or hide the only merge event.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_caller_transaction_rollback_cannot_clear_pending_or_hide_merge_event`
- [ ] An eventless original merge followed by target evolution emits exactly one event for the
      original decision pair.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_eventless_merge_then_target_merge_backfills_original_event`
- [ ] A crash during a repeated split cannot create or falsely certify duplicate complements.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_pending_clear_waits_for_unique_split_recovery`
- [ ] Journal schema ownership, runtime assertion, migration, and test fixtures agree.
      Verify: `tests/migrations/test_entity_review_operation_journal_schema_parity.py::test_entity_review_operation_journal_schema_matches_head`
- [ ] A terminal replay covers every row of the specification's partial-failure matrix and records
      the exact accepted child SHAs.
      Verify: runtime receipt `entity_review_operation_journal.terminal_recovery_matrix.v1` on this parent
- [ ] Owner docs describe the delivered behavior only after the terminal receipt is accepted.
      Verify: doc writeback at `docs/STATUS.md :: Runtime verification`

## Implementation Tasks

| Order | ID | Task specification | Prerequisite | Initial state |
| --- | --- | --- | --- | --- |
| 1 | EROJ-01 / [#4350](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4350) | `docs/ENTITY_REVIEW_OPERATION_JOURNAL/COMMIT_OPERATION_AND_OUTBOX_VISIBILITY.md` | — | `agent:ready` |
| 2 | EROJ-02 / [#4351](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4351) | `docs/ENTITY_REVIEW_OPERATION_JOURNAL/PRESERVE_TARGET_EVOLUTION_LINEAGE.md` | accepted EROJ-01 receipt | `agent:blocked` |
| 3 | EROJ-03 / [#4352](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4352) | `docs/ENTITY_REVIEW_OPERATION_JOURNAL/GUARANTEE_GLOBALLY_UNIQUE_SPLIT_COMPLEMENTS.md` | accepted EROJ-02 receipt | `agent:blocked` |

## Verification Path

Each child runs its exact `Verify:` targets and the affected Heimdal/migration lanes. The future
implementation PRs use the full Tier-3 path because this work touches data, migration,
concurrency-sensitive visibility, and explicit state-machine recovery. The parent accepts only the
terminal recovery-matrix receipt after all child receipts are current.

## Validation / Acceptance Path

EROJ-01 posts its accepted receipt before EROJ-02 can become ready; EROJ-02 does the same before
EROJ-03. State changes are made by the delivery coordinator after re-validating the dependent issue
against live main. Parent closure requires the terminal receipt plus truthful current-state owner-doc
writeback. A failed/ambiguous recovery leaves the parent open and does not relax INV-EROJ-6.

## Out of Scope

Reopening #4253; runtime implementation in this docs PR; automatic entity decisions; a generic saga
or graph substrate; a second queue/outbox; UI work; historical lineage reconstruction that cannot be
deterministically proven.

## Suggested Validation

- `python3 -m pytest -q tests/heimdal/test_entity_review_operation_journal.py tests/heimdal/test_entity_register.py tests/heimdal/test_entity_confirm.py`
- `python3 -m pytest -q tests/migrations/test_entity_review_operation_journal_schema_parity.py`
- `python3 -m pytest -q -m "not pg" tests/heimdal tests/migrations`
- `python3 scripts/docs_guard.py`
- Terminal authorized-runtime replay producing
  `entity_review_operation_journal.terminal_recovery_matrix.v1`

## Source Docs

- `docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md`
- `docs/ENTITY_REVIEW_OPERATION_JOURNAL/COMMIT_OPERATION_AND_OUTBOX_VISIBILITY.md`
- `docs/ENTITY_REVIEW_OPERATION_JOURNAL/PRESERVE_TARGET_EVOLUTION_LINEAGE.md`
- `docs/ENTITY_REVIEW_OPERATION_JOURNAL/GUARANTEE_GLOBALLY_UNIQUE_SPLIT_COMPLEMENTS.md`
- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
- `docs/MIMER_IPAD_THINKING_CANVAS/SIDE_BY_SIDE_ENTITY_CONFIRMATION_ON_IPAD.md`
- `docs/EVENTS.md`
- `docs/RUNTIME_CORRECTNESS_KERNEL/TRANSACTIONAL_VAULT_SYNC.md`

## Applies learning (optional)

Applies LearningSignal `lrn_20260729110519_a46349a0`: after multiple blockers appeared in one
stateful mechanism, stop point-fixing, preserve the failure evidence, and decompose the mechanism
around independently provable transaction, lineage, and complement-identity invariants.
