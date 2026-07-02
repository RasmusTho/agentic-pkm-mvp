State: **Specification directory (pre-filing draft).** Parent feature issue and child issues not yet filed; this line is updated in the same PR once they exist.

# Runtime Correctness Kernel — Single Truth, Replay-Sound Events, Typed LLM Boundaries

Specification directory converting the structural audit
`docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md` (§7 backlog T1–T15) into bounded,
independently mergeable implementation tasks. The audit is the analysis; **this directory is the
specification**; GitHub issues created from it are the execution contracts.

## Capability boundary

Make the live runtime uphold the nine-invariant correctness kernel from the audit (§2):

- **Single truth per concept** — one store generation, retrieval serves from the durable index,
  schema DDL has one authority (I-S1, I-D3, I-S3, I-S4).
- **Replay-sound events** — state mutation + outbox event commit atomically; idempotency keys are
  mandatory and deterministic; handlers are provably idempotent; dead-letters are loud
  (I-S2, I-E1, I-E2, I-E3, I-E4).
- **Typed LLM boundaries** — LLM output that code branches on is schema-constrained and validated;
  classification failure yields explicit `UNKNOWN`, never a silent action-capable default; event
  topics and plans validate against registered schemas (I-A1, I-A2, I-E5, I-C1).
- **Evaluations that gate the above** — structural validation, an intent-classification golden set,
  scorecard comparison for model/prompt changes, and a failure-to-eval capture loop.

Out of capability scope: lexical mirror + hybrid fusion (stays with #2314 W4-RET-01's other half),
memory ledger/review UI (W7/W8), sync/federation, UI work.

## SBS classification

**Product / Runtime System.** Primary subsystems: PDM (KERNEL-01..04), DRI (05, 06), RCA (05, 10),
CAO (07, 09), GOV/EXE (07, 12), OEF (11, 13, 14, 15). No Builder System authority is created;
eval/fitness tasks touch OEF product surfaces (`app/eval`, `config/eval_thresholds.yaml`), not
BuilderOps records.

## Implementation tasks (dependency order)

| Task | task_id | Phase | Depends on | TCD hint (cheapest acceptable) |
| --- | --- | --- | --- | --- |
| [TRANSACTIONAL_VAULT_SYNC](TRANSACTIONAL_VAULT_SYNC.md) | KERNEL-01 | 0 | — | Sonnet / high |
| [MANDATORY_OUTBOX_IDEMPOTENCY](MANDATORY_OUTBOX_IDEMPOTENCY.md) | KERNEL-02 | 0 | KERNEL-01 | Sonnet / medium |
| [SINGLE_STORE_GENERATION](SINGLE_STORE_GENERATION.md) | KERNEL-03 | 0 | — | Sonnet / high |
| [STORE_SCHEMA_IN_MIGRATIONS](STORE_SCHEMA_IN_MIGRATIONS.md) | KERNEL-04 | 0 | — | Opus / high (migration surface) |
| [RETRIEVAL_READS_DURABLE_INDEX](RETRIEVAL_READS_DURABLE_INDEX.md) | KERNEL-05 | 1 | KERNEL-03, KERNEL-04 | Opus / high (hot path) |
| [TRANSFORM_PROVENANCE_STAMP](TRANSFORM_PROVENANCE_STAMP.md) | KERNEL-06 | 1 | KERNEL-04 | Sonnet / high |
| [STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN](STRUCTURED_INTENT_OUTPUT_WITH_UNKNOWN.md) | KERNEL-07 | 2 | — | Sonnet / high |
| [EVENT_TOPIC_SCHEMA_REGISTRY](EVENT_TOPIC_SCHEMA_REGISTRY.md) | KERNEL-08 | 2 | KERNEL-02 | Sonnet / medium |
| [PLAN_ADMISSION_VALIDATION](PLAN_ADMISSION_VALIDATION.md) | KERNEL-09 | 2 | KERNEL-07 | Sonnet / high |
| [RUNTIME_SCOPE_PREFILTER_AND_ENVELOPE](RUNTIME_SCOPE_PREFILTER_AND_ENVELOPE.md) | KERNEL-10 | 3 | KERNEL-05 | Opus / xhigh (architecture) |
| [HANDLER_IDEMPOTENCY_HARNESS](HANDLER_IDEMPOTENCY_HARNESS.md) | KERNEL-11 | 3 | KERNEL-02, KERNEL-08 | Sonnet / medium |
| [DEAD_LETTER_HEALTH_SIGNAL](DEAD_LETTER_HEALTH_SIGNAL.md) | KERNEL-12 | 3 | — | Sonnet / medium |
| [INTENT_CLASSIFICATION_GOLDEN_SET](INTENT_CLASSIFICATION_GOLDEN_SET.md) | KERNEL-13 | 4 | KERNEL-07 | Sonnet / medium |
| [EVAL_SCORECARD_COMPARE](EVAL_SCORECARD_COMPARE.md) | KERNEL-14 | 4 | KERNEL-13 | Sonnet / medium |
| [FAILURE_TO_EVAL_CAPTURE_LOOP](FAILURE_TO_EVAL_CAPTURE_LOOP.md) | KERNEL-15 | 4 | KERNEL-12, KERNEL-13 | Sonnet / high |

TCD hints follow `AGENTS.md :: Total Cost of Development` and are **non-binding**: `issue-to-code`
re-derives capability from the issue's risk and artifact class. Escalate on the standard triggers
(two failed attempts, hidden invariants, migration/concurrency surfaces).

Parallelization: within Phase 0, KERNEL-01 ∥ KERNEL-03 ∥ KERNEL-04 (disjoint files);
KERNEL-02 serializes after KERNEL-01 (same producer seam in `app/services/vault_sync.py`).
KERNEL-07 and KERNEL-12 have no Phase-0 dependency and may be picked up in parallel with Phase 0 by
a second agent. Everything else follows the table.

## Execution order (flat)

KERNEL-01 → KERNEL-02, with KERNEL-03, KERNEL-04, KERNEL-07, KERNEL-12 in parallel lanes →
KERNEL-05, KERNEL-06, KERNEL-08 → KERNEL-09, KERNEL-11 → KERNEL-10 → KERNEL-13 → KERNEL-14 →
KERNEL-15.

## Cross-Task Invariants / Interaction Safety

Several tasks read or write the same state (outbox, store tables, eval scorecards). The invariants
that must hold *across* tasks, and the partial-failure seams:

1. **Every phase leaves the runtime consistent.** No task may land in a state where the outbox
   contains events its consumer cannot dispatch. KERNEL-08 (schema validation at dispatch) must
   therefore grandfather pre-existing rows: rows written before the registry exists are validated
   at dispatch with `schema_version` absence treated as `v0` (log-only), never dead-lettered
   retroactively.
2. **Signature changes propagate with their producers.** KERNEL-02 changes
   `write_outbox_event` to require an idempotency key; per the AGENTS.md invariant→producers rule,
   *every* producer (vault_sync, indexer events, panel, promotion) migrates in the same PR — a
   required-key landing without migrated producers is a runtime outage, not a partial delivery.
3. **Removal follows rewiring.** KERNEL-03 removes the legacy `app/store/*` writers only after (or
   in the same change as) migrating their callers to `app/stores` providers. If KERNEL-05 has not
   yet landed, retrieval's existing read path must keep functioning against the durable index —
   KERNEL-03 must not orphan any read path.
4. **A provenance stamp is valid only if written transactionally with its vector.** KERNEL-06's
   `{content_hash, chunk_policy_version, pipeline_version}` ride the same `upsert` payload as the
   embedding (single statement); a separate "stamp later" write is forbidden — it recreates the
   divergence class this capability removes.
5. **Doctor detects, Executor repairs, nothing auto-mutates.** KERNEL-06 staleness detection and
   KERNEL-12 health signals are read-only; repair remains an explicit operator/agent action
   (`index reconcile`), matching the existing index-doctor posture.
6. **Eval gates activate only after their dataset exists.** KERNEL-13's blocking gate
   (mutation-side confusion = regression) is wired into CI in the same PR that lands the golden
   set, never before; a gate with an empty dataset is a false-green.
7. **UNKNOWN must have a landing surface before the default is removed.** KERNEL-07 removes the
   CO_AUTHORING fallback only together with the read-only degrade + re-ask surface; removing the
   default without the surface converts silent misrouting into hard failure for the user.

If an implementing agent cannot satisfy one of these seams inside its bounded issue, the correct
move is to stop and flag the issue contract, not to widen scope silently.

## Capability acceptance criteria

- [ ] Phase 0 delivered: crash-injection atomicity proven, idempotency keys mandatory, exactly one
      store generation, store DDL in Alembic with schema parity.
      Verify: child-issue `Verify:` targets green on `main`; parent-issue receipt per phase.
- [ ] Retrieval truth is single: kill-and-restart retrieval equivalence test green; index doctor
      reports zero retrieval-vs-index divergence.
      Verify: `tests/retrieval/test_retrieval_durable_equivalence.py`
- [ ] No silent LLM defaults remain on control paths: intent classifier emits `UNKNOWN`; topics and
      plans schema-validated.
      Verify: `tests/chat/test_intent_unknown_route.py`, `tests/events/test_topic_schema_registry.py`
- [ ] Eval gates live: classification confusion gate + scorecard compare wired; failure-to-eval
      capture loop produces draft cases.
      Verify: `tests/eval/test_classification_golden.py`, CI workflow diff
- [ ] Owner docs promoted once acceptance holds (`docs/EVENTS.md`, `docs/DB_SCHEMA.md`,
      `docs/EMBEDDINGS.md`, `docs/ARCHITECTURE.md` reflect shipped reality).
      Verify: doc writeback anchors listed in the final child issue

## Relationship to GitHub issues

- Parent feature issue: **not yet filed** (see `PARENT_FEATURE_ISSUE.md`; updated when filed).
- One issue per task file at filing time; a task file may later split into more issues if
  implementation reveals size (spec stays the source of truth).
- KERNEL-05 **extends #2314 W4-RET-01** (the in-memory/durable reconciliation half). The #2314 epic
  is notified by comment; no parallel hub is created (epic stop-condition honored).
- KERNEL-10 supersedes the stale "Slice #2025" pointer in
  `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md` (#2022/#2025 delivered the activation gate;
  the remaining gap is `app/` retrieval prefilter + envelope semantics).

## Related docs

- Audit source: `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md`
- Owner docs touched at promotion: `docs/EVENTS.md`, `docs/DB_SCHEMA.md`, `docs/DATA_MODEL.md`,
  `docs/EMBEDDINGS.md`, `docs/HEALTH.md`, `docs/ARCHITECTURE.md`
- Contracts: `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`,
  `docs/CONCEPTS/CONTEXT_ADMISSIBILITY_CONTRACT.md`, `docs/CAPABILITY_CONTRACT_MODEL.md`
- Invariant registry: `docs/testing/invariant-tests.md`
