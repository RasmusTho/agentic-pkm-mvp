---
name: Preserve Entity-Review Target-Evolution Lineage
description: Recover the one original merge event after its target later merges or splits, using operation-bound lineage rather than inference from the current redirect graph.
task_id: EROJ-02
source_anchor: "docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md :: Cross-task partial-failure matrix"
parent_capability: Entity-Review Operation Journal
prerequisites:
  - EROJ-01 accepted parent receipt
depends_on:
  - COMMIT_OPERATION_AND_OUTBOX_VISIBILITY.md
can_parallelize_with: []
---

# Preserve Entity-Review Target-Evolution Lineage

## Purpose

Allow an EROJ-01 operation whose register effects exist but whose event was not committed to recover
after the original target has subsequently undergone a governed merge or split. The recovered event
must still mean exactly what the human decided: original source into original target.

## What This Task Does

- Extend entity-register merge/split note effects with the minimum operation-linked lineage needed to
  prove how the original `into_id` evolved. Lineage records stable entity ids, governing operation
  identity where present, predecessor/successor relation, and mutation kind; it does not copy labels
  or infer identity from aliases.
- Teach journal recovery to start from the operation's immutable original pair, validate the original
  source effect, and follow only explicit governed lineage from the original target to its current
  resolution.
- Emit the missing `heimdal.register.entity.merged` event once with the original `{from_id, into_id,
  operation_id}`. Current resolved targets may be included only as additive resolution context; they
  cannot replace the original pair.
- Make target merge and target split producers write lineage in the same guarded note mutations that
  change redirects. Update parsers, render/round-trip behavior, fixtures, and compatibility handling
  in the same PR.
- Reject missing links, forks without an explicit split relation, cycles, operation mismatch, and
  source/target contradictions before event commit or queue clear.
- Preserve the safe EROJ-02 stopping point: repeated or legacy-ambiguous split complements remain a
  fail-closed refusal until EROJ-03 supplies globally unique complement identity.

## Concretely

Suppose operation `op1` applies the human decision `S -> T`, writes the register effects, and stops
before committing its event. A later governed operation changes `T -> U`. Recovery loads `op1`,
proves the original `S -> T` effect and the explicit `T -> U` lineage, then emits exactly one event
whose semantic pair remains `S -> T`. It may report that `T` currently resolves to `U`; it may not
rewrite the event to `S -> U`.

If `T` split into `T1` and `T2`, recovery requires an explicit lineage relation that identifies the
successor relevant to the original effect. If the register contains only labels, aliases, or an
ambiguous fork, recovery stops with `pending` intact.

## Why This Matters

The current redirect graph describes where an id resolves now, not which historical human decision
created an eventless effect. Reconstructing the original event from current graph shape silently
changes history after target evolution. The journal already holds the original pair; explicit
lineage is needed only to prove that current notes are a lawful evolution of that pair.

## Acceptance Criteria

- [ ] An eventless `S -> T` entity-review merge followed by governed `T -> U` evolution recovers one
      event for original `S -> T`, while additive resolution context identifies `U`.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_eventless_merge_then_target_merge_backfills_original_event`
- [ ] A target split preserves the original operation identity and can prove the relevant successor
      without rewriting the original event pair.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_target_split_lineage_preserves_original_operation_identity`
- [ ] Missing, contradictory, fork-ambiguous, or cyclic target lineage fails before event commit and
      leaves the exact decision history and pending entry unchanged.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_contradictory_or_cyclic_target_evolution_fails_closed`
- [ ] Recovery uses the journal's original pair plus explicit lineage and never graph-only replay,
      labels, aliases, or timestamps.
      Verify: `tests/heimdal/test_entity_confirm.py::test_apply_merge_recovers_after_target_evolution_without_graph_replay`
- [ ] Every merge/split producer, note parser/renderer, and fixture writes or preserves the required
      lineage; unambiguous legacy notes remain readable and ambiguous legacy recovery fails loud.
      Verify: `tests/heimdal/test_entity_register.py::test_lineage_round_trip_covers_every_merge_and_split_producer`
- [ ] EROJ-01 transaction visibility remains mandatory after lineage recovery.
      Verify: `tests/heimdal/test_entity_review_operation_journal.py::test_target_evolution_recovery_still_requires_fresh_event_visibility`

## How to Verify (Pre-Merge)

- `python3 -m pytest -q tests/heimdal/test_entity_review_operation_journal.py tests/heimdal/test_entity_register.py tests/heimdal/test_entity_confirm.py`
- `python3 -m pytest -q -m "not pg" tests/heimdal`
- `ruff check app tests`
- `mypy app`
- Run mutation tests over merge→merge, merge→split, missing-link, fork, and cycle fixtures.
- Full Tier-3 independent review and current-SHA CI; post exact results and owner-doc writeback to the
  parent before EROJ-03 is made ready.

## Out of Scope

- Globally unique complement ids and repeated split checkpoint recovery (EROJ-03).
- A general lineage graph, graph database, event replay engine, temporal query API, or historical
  reconstruction of unrelated register notes.
- Changing the original decision or emitting a replacement event for an evolved target.
- Automatically choosing a successor when a split lineage is ambiguous.

## Restart / Durability Posture

Recovery always starts from the committed EROJ-01 operation. Explicit note lineage may advance the
proof from the original target to a current successor, but it never advances the operation's semantic
pair. A crash during lineage-bearing note writes resumes through the same operation and governed note
write checks. An incomplete or contradictory chain is non-terminal and leaves `pending` intact.

## TCD Capability Guidance

Use Codex Sol / high-to-xhigh reasoning. This is identity-lineage and data-correctness work on an
explicit state machine, with high defect blast radius and a prior adjacent protected failure. Start
with a mechanism review of the merge→merge and merge→split proofs before broad tests. Use xhigh if
legacy compatibility or split ambiguity requires non-local changes. Do not fan out implementation.

## Related Docs

- `docs/ENTITY_REVIEW_OPERATION_JOURNAL/README.md`
- `docs/adr/ADR-0049-heimdall-ingestion-organ-and-v1-uiux-enactment.md`
- `docs/HEIMDAL/FABLE_COMPANION.md`
- `docs/HEIMDAL/ENTITY_IDENTIFICATION_RESEARCH.md`
- `docs/EVENTS.md`
- `docs/CONCURRENCY.md`

## Related GitHub Issues

Filed as [#4351](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4351), the second serial child of
parent validation hub [#4349](https://github.com/RasmusTho/agentic-pkm-mvp/issues/4349). It remains
`agent:blocked` pending an accepted EROJ-01/#4350 parent receipt.
