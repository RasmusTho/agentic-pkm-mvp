State: Advisory research artifact (RESEARCH-01, issue #2779, epic #2778; 2026-07-02). Subordinate to `docs/DOCS_INDEX.md` and owner contracts. Describes **current reality** with target semantics explicitly marked; ratification/promotion into owner contracts is a separate owner decision.
Doc role: Reference (architecture analysis)
Authority: Evidence-based; every claim carries a file:line anchor against `main` at `b8ec22f4`. Where this artifact and an owner doc disagree, the disagreement is listed in `Divergences` — the owner doc remains authoritative until the divergence is resolved.

# Runtime Semantics — Identity, Mutation, Canonicality, Replay, GC

Every correctness argument in this system implicitly answers five questions per persisted artifact
class. This artifact makes the answers explicit, so the formal model (RESEARCH-02, #2780) has
defined terms and the Runtime Correctness Kernel (#2762) has a semantic baseline.

## Definitions

- **Identity** — the value that makes two observations "the same artifact", and who assigns it.
- **Mutation** — the legal write operations, their guards, and what is immutable from when.
- **Canonicality** — exactly one of:
  - **canonical**: the artifact is a source of truth; losing it loses information.
  - **derived**: fully recomputable from named canonical inputs; losing it loses only time.
  - **advisory**: informative record; neither truth nor required for reconstruction.
- **Replayability** — the named inputs from which the artifact can be reconstructed after loss
  ("none — it IS the source" is a legal answer for canonical classes).
- **GC** — the conditions under which the artifact may be deleted, by whom, with what receipt.
  "No path exists" is a finding, not a default.

## Classification table

| # | Class | Identity (assigner) | Mutation + guard | Canonicality | Replayable from | GC path |
|---|---|---|---|---|---|---|
| 1 | Vault note | frontmatter `uuid` (healed by worker if absent; advisory, never a gate) + path | human edits; agent writes via WriteGuard only | **canonical** | none — primary source | human deletion; `vault_sync.delete_note()` propagates |
| 2 | Companion note | `uuid` of its vault note | system-only, WriteGuard-gated atomic write (`companion_note.py:141-149`) | **canonical** (continuity set with the note) | partially from DB/events, but defined as primary | none automated |
| 3 | Commitment artifact | `commitment_id` frontmatter (`commitment_persistence.py:96`) | WriteGuard-gated atomic full-file write (`:137-140`); `commitment_state` transitions in frontmatter | **canonical** | none — primary source | **none exists** (manual vault deletion only) |
| 4 | `store_objects` row | `object_id` UUID (runtime-assigned; ≠ frontmatter uuid in general) | upsert `ON CONFLICT (object_id)` (`stores/pg.py:263-278`); legacy path via `vault_sync` | **derived** by contract (MACHINE_MIRROR), semi-canonical in practice — see D-2 | vault rescan + re-ingest | **none** — on note delete, `path=NULL` only (`vault_sync.py:224-234`); rows persist indefinitely |
| 5 | `file_state` row | `path` PK, `uuid` secondary (`migrations_obsidian.sql:5-13`) | upsert per sync; explicit DELETE on delete/rename (`vault_sync.py:166-168,203-206,221`) | derived (sync bookkeeping) | full vault rescan | delete/rename only; stale rows persist if watcher misses an event |
| 6 | `store_vector_index` row | `object_id` (one row per object; whole-note serving) | identity-guarded upsert (`stores/pg.py:361-438`, CTI-1); `purge_vectors()` (`:510-522`) | derived | re-embed from source text (incremental only after KERNEL-06 provenance stamp) | `purge_vectors` on `INGEST_OBJECT_DELETED` (`indexer/consumer.py:65`) |
| 7 | Chunk | deterministic `chunk_id` = sha256(source, index, offsets) (`chunk_policy.py:184-192`) | none — computed on demand, never persisted | derived (pure function) | source text + `chunk_policy` version | n/a (not stored) |
| 8 | Outbox event row | row `id` = optional idempotency key (`outbox.py:206`; mandatory after KERNEL-02) | append; `delivered_at` ack; `attempts` bump — never edited (`outbox.py:314-382`) | **canonical** (the event log) | none — it IS the replay source | **none exists** — delivered rows persist forever; unbounded growth |
| 9 | JSONL index-outbox / receipt files | none (append order) | append-only (`outbox.py:166-174`) | advisory (audit trail; explicitly NOT truth per CW-1) | from DB outbox | **none** — never rotated |
| 10 | Promotion receipt | outbox row id, `event=promotion.transition.applied` (`receipts/promotion_receipts.py:92-99`) | append-only (projection over outbox) | **canonical** (proof of transition) | from outbox | inherits outbox (none) |
| 11 | `SettingsWriteReceipt` | none durable | in-memory dataclass only (`vault/settings_service.py:43-60`) | **advisory today; contract says canonical** — see D-1 | **not reconstructible** — lost on restart | n/a (ephemeral) |
| 12 | Decision row | `id` UUID auto (`202510241200_sot41_amg_core.py:85-94`); lookup `(object_id, key)` latest-wins | append-only INSERT (`services/decisions.py:30-42`); silent memory fallback on DB failure (`:43-45`) | **canonical** (judgment log) | not reconstructible | `ON DELETE CASCADE` from objects — see D-5; no direct path |
| 13 | Memory: review decision | `(vault_id, channel, candidate_id)` (`review_decision_store.py:212`) | SQLite upsert (`:79-102`); terminal flag after materialization (`:176-193`) | **canonical** (promotion precondition) | none — primary record | **none exists** |
| 14 | Memory: materialized artifact | `artifact_uuid` (`agent_memory/materialization.py:67`) | WriteGuard-gated vault write | derived (from decision + candidate) | decision store + re-materialization | none |
| 15 | Memory: `agent_memories` (short-term) | `id` UUID (`migrations_obsidian.sql:15-22`) | append + timestamp decay (`memory_kv/store.py:164-191`) | derived (working memory) | lossy — decay is the design | timestamp decay only |
| 16 | Audit row | `id` UUID; `object_id` FK `ON DELETE SET NULL` (`202510241200_sot41_amg_core.py:102-112`) | append-only, best-effort writer (`services/audit.py:33-77`) | **canonical** (trace) | not reconstructible | **none** — unbounded |
| 17 | Eval golden data (`data/golden/*`, `docs/eval/*.yaml`) | file path + committed content | PR-only mutation | **canonical** (eval ground truth) | git history | git |
| 18 | Eval scorecard (`runtime/eval/scorecard.json`) | file path (overwritten per run) | overwrite per run; gitignored | derived | re-run `app.eval.run` | overwrite; no history kept |
| 19 | Session / chat history | — | — | **not persisted at all** (no table, no file) — see D-4 | **nothing** — lost on restart | n/a |
| 20 | BuilderOps record | record id in BuilderOps Vault (outside this repo/runtime) | builder-plane rules (`AGENTS.md :: BuilderOps Vault workflow boundary`) | canonical for builder ops; **never product/runtime truth** | BuilderOps Vault | builder-plane discard receipts |

## Per-class notes

- **1–3 (vault plane).** The portable continuity set is note + companion (contract:
  `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`). All writes funnel through
  `WriteGuard.assert_writes_allowed()` (`app/write_guard.py:22-27`). Commitment artifacts carry
  `commitment_state`, not `review_state`/`maturity` (STATE_AXES contract).
- **4 (objects) is the semantically fuzziest class in the system.** Contractually derived
  (`docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`), but: decisions FK-cascade off it,
  vectors key off its `object_id`, and deletion never removes it (`path=NULL` tombstone-by-accident).
  Its identity is runtime-assigned and only loosely coupled to the vault uuid. RESEARCH-02 should
  model it as *derived-with-dependents*, which is exactly the configuration that makes "rebuild the
  DB from the vault" non-trivial today: rebuilding assigns new `object_id`s, orphaning decisions and
  audit references.
- **6–7 (index plane).** Whole-note serving; chunks are computed. Replayability of vectors is
  *total* (re-embed everything) but not *incremental* until the KERNEL-06 provenance stamp
  (`content_hash`, `chunk_policy_version`) lands.
- **8–11 (event/receipt plane).** The outbox is the only replay substrate the runtime has; its
  soundness is exactly what KERNEL-01/02 (atomicity, mandatory idempotency) fix. Note the
  asymmetric worker behavior: `handle_ingest_object_deleted` is an explicit no-op in the worker
  (`outbox_worker.py` ~505-513) while vector purge for the same topic lives in the indexer consumer
  path (`indexer/consumer.py:65`) — deletion semantics are split across two consumers.
- **12–15 (judgment/memory plane).** Review decisions are the promotion precondition and genuinely
  canonical; the silent in-memory fallback in `services/decisions.py:43-45` is the same
  false-healthy pattern as the legacy store fallback (kernel I-S4 class, though a different module).
- **19 (session history).** Nothing persists. The settled storage-substrate posture (persist by
  who-needs-it + lifetime; session history belongs with companion-note-class artifacts) names this
  as a gap to fill, not a design.

## Divergences

Each divergence is classified **fix-code**, **fix-doc**, or **needs-owner-decision**.

- **D-1 · SettingsWriteReceipt is ephemeral — contradicts the receipt contract.** The control-action
  boundary (#2475, `docs/INTERACTION_SURFACES_AND_AUTHORITY/DEFINE_RUNTIME_CONTROL_ACTION_BOUNDARY.md`)
  makes the receipt the accountability half of "proportional guard + receipt", but
  `SettingsWriteReceipt` is an in-memory dataclass (`app/vault/settings_service.py:43-60`) lost on
  restart. A receipt that cannot be produced later is not a receipt. **fix-code** (bounded: emit as
  an outbox event like promotion receipts). Follow-up filed — see below.
- **D-2 · Object deletion is a `path=NULL` accident, not a semantic.** `vault_sync.delete_note()`
  nulls the path (`vault_sync.py:224-234`); `handle_ingest_object_deleted` is a no-op
  (`outbox_worker.py` ~505-513); objects rows live forever while their decisions would CASCADE if
  the row were ever deleted. Retain-as-tombstone (lineage) and delete-with-cleanup are both
  defensible; today's behavior is neither, by omission. **needs-owner-decision** (tombstone
  contract vs. cleanup), surfaced on epic #2778.
- **D-3 · The June observability audit's "dead audit writer" claim is no longer true.** The writer
  is alive, best-effort, with FK-failure fallback (`app/services/audit.py:33-163`). The claim in the
  2026-06-27 observability audit doc is stale. **fix-doc** (mark the finding resolved/dated).
  Follow-up filed — see below.
- **D-4 · Session/chat history is not persisted anywhere** — no table, no vault artifact. Diverges
  from the settled storage-substrate posture (session history as a companion-note-class,
  human-readable artifact). Known gap, feature-sized. **needs-owner-decision** (priority call, then
  feature-breakdown), surfaced on epic #2778.
- **D-5 · Decisions cascade-delete with their object.** `decisions.object_id` is
  `ON DELETE CASCADE` (`202510241200_sot41_amg_core.py:87`) while `audit.object_id` is
  `ON DELETE SET NULL` (`:104`). Two canonical append-only logs, opposite loss semantics; if object
  cleanup (D-2) ever lands, judgment history silently vanishes. **fix-code** (align decisions to
  `SET NULL`; one forward-only migration). Follow-up filed — see below.
- **D-6 · Nothing in the system is garbage-collected.** Outbox delivered rows, audit rows, JSONL
  files, review decisions, commitments: no retention policy exists anywhere, and no doc states this
  as a decision. Unbounded growth is currently the *implicit* durability contract.
  **needs-owner-decision** (a retention/rotation policy per class — cheap for JSONL/outbox, subtle
  for audit/decisions), surfaced on epic #2778.
- **D-7 · Silent memory fallback in decisions writer** (`services/decisions.py:43-45`) — same
  failure class as kernel I-S4 (CW-5) but a callsite the kernel specs do not cover. **fix-code**
  (fail-loud or explicit opt-in, mirroring KERNEL-03's provider rule). Folded into the follow-up
  for D-5's module — see below.

## Target semantics (explicitly not current reality)

The Runtime Correctness Kernel (#2762) changes rows 4, 6, 8 as follows: outbox insert atomic with
state mutation and mandatorily idempotent (KERNEL-01/02); one store generation with fail-loud
resolution (KERNEL-03/04); vectors carry transform provenance enabling incremental replay
(KERNEL-06); retrieval reads only row 6, never a volatile mirror (KERNEL-05). This artifact should
be re-baselined after Phase 0 lands.

## Follow-ups filed

- fix-code: persist SettingsWriteReceipt durably via outbox (D-1) — issue linked on #2779.
- fix-code: decisions FK `CASCADE`→`SET NULL` + fail-loud decisions writer (D-5, D-7) — issue
  linked on #2779.
- fix-doc: retire the stale "dead audit writer" claim in the 2026-06 observability audit (D-3) —
  issue linked on #2779.
- needs-owner-decision (D-2 object deletion semantics, D-4 session-history persistence, D-6
  retention policy): surfaced as an owner-decision comment on epic #2778 — deliberately NOT filed
  as ready issues.

## Related docs

- `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md` (authority boundary this artifact refines)
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`, `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md` (CW-1/CW-3/CW-5 context)
- `docs/RUNTIME_CORRECTNESS_KERNEL/README.md` (target-semantics owner)
- RESEARCH-02 consumer: `docs/architecture/formal-model.md` (to be authored under #2780)
