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
| 19 | Chat-session artifact | `session_id` UUID + durable `note_uuid` (`docs/CANVAS_CHAT_SURFACE/DEFINE_CHAT_ARTIFACT_DURABILITY.md`, spec pending #2806/#2807) | today: raw file write, no WriteGuard (`session_log.py`); target: WriteGuard-gated via KnowledgePort | **canonical** for its own intent-trail content; not note content | none — primary source for its own content | D-6 posture (cold storage, not deletion) once implemented |
| 20 | BuilderOps record | record id in BuilderOps Vault (outside this repo/runtime) | builder-plane rules (`AGENTS.md :: BuilderOps Vault workflow boundary`) | canonical for builder ops; **never product/runtime truth** | BuilderOps Vault | builder-plane discard receipts |

## SBS boundary mapping

Each class is owned by exactly one SBS L2 boundary (`docs/SYSTEM_BREAKDOWN_STRUCTURE.md`); the
semantics above are that boundary's contract to state. This mapping **conforms to** the current SBS
— no reshape is proposed by this artifact:

- **HKA** (Human Knowledge & Artifact): 1 vault note, 3 commitment artifact, 17 eval golden data,
  19 chat-session artifact (target owner per ratified D-4; spec
  `docs/CANVAS_CHAT_SURFACE/DEFINE_CHAT_ARTIFACT_DURABILITY.md`, not yet landed — tracked by issues
  #2806/#2807).
- **SIP** (Semantic Identity & Provenance): 2 companion note (identity/continuity half), uuid
  lineage semantics across classes, 19's note relationship (target `chat_for`/`has_chats` relation
  type, not yet registered in `RELATION_TAXONOMY.md` — tracked by issue #2806).
- **PDM** (Persistence & Data Management): 4 objects, 5 file_state, 8 outbox, 12 decisions.
- **DRI** (Derived Representation & Indexing): 6 vectors, 7 chunks, 18 scorecard (derived half).
- **GOV** (Governance/Receipts): 10 promotion receipt, 11 settings receipt, 16 audit.
- **MEM** (Machine Memory & Learning): 13–15 memory classes.
- **OEF** (Observability, Evaluation & Fitness): 9 JSONL audit trail, 17–18 eval surfaces.
- **Builder System (outside Product SBS)**: 20 BuilderOps records.

Class 19 moved out of the HIX/WSP "unresolved home" bucket above: D-4 ratified its target as HKA
(the artifact, alongside classes 1/3) with the note-relationship in SIP — see the HKA/SIP bullets
above. The move is a doc consequence of the D-4 ratification, not a new SBS decision; the actual
`RELATION_TAXONOMY.md`/`SBS_CURRENT_TO_TARGET_MAPPING.md` table edits remain pending on #2806.

Two observations for the SBS stewardship channel (CES), flagged not enacted: (a) class 4
(`store_objects`) currently carries PDM persistence duties *and* SIP-grade identity duties
(runtime `object_id` as the FK anchor for decisions/audit) — **ratified as tombstone (D-2): the
dual role stands, unsplit**, pending the later event-triggered-decay lifecycle design; (b) class
11's ephemeral receipts sit in GOV by contract but exist only in HIX process memory today (D-1,
#2787). Any reshape that follows from these goes through the SBS operationalization plan / ADR
route, not through this artifact.

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
- **19 (chat-session artifact).** Corrected from the original RESEARCH-01 finding: the canvas
  chat-session artifact (`vault/.chats/<note-slug>/*.md`, `type: chat-session`) already persists —
  it is not "nothing on restart." What was actually missing, and what D-4 ratified: formal
  identity/canonicality/GC classification, WriteGuard gating (today's writes bypass it entirely),
  and a registered SIP relation to its note. See
  `docs/CANVAS_CHAT_SURFACE/DEFINE_CHAT_ARTIFACT_DURABILITY.md` for the closing classification and
  `PERSIST_CHAT_ARTIFACT_THROUGH_WRITEGUARD.md` for the durability implementation (issues
  #2806/#2807, not yet merged as of this row).

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
  the row were ever deleted. **RATIFIED (2026-07-02, epic #2778): tombstone.** Object rows are
  retained as permanent lineage anchors after note deletion — today's accidental behavior becomes
  the intentional contract; no code change required. Named explicitly as a floor, not a ceiling: a
  future lifecycle model (active → archived → forgotten) driven by **event-triggered relevance
  decay** — value lost at a triggering event, not on a fixed schedule (e.g. a grocery list is
  worthless the moment the shopping trip happens, independent of age) — is a deliberate later
  direction, input to RESEARCH-02's GC dimension and RESEARCH-04's evolution graph, not scoped here.
- **D-3 · The June observability audit's "dead audit writer" claim is no longer true.** The writer
  is alive, best-effort, with FK-failure fallback (`app/services/audit.py:33-163`). The claim in the
  2026-06-27 observability audit doc is stale. **fix-doc** (mark the finding resolved/dated).
  Follow-up filed — see below.
- **D-4 · Chat-session artifact had no identity/canonicality/GC classification or WriteGuard
  gating** — corrected from the original finding, which said "not persisted anywhere, no table, no
  vault artifact": the canvas chat-session artifact already persists (`vault/.chats/<note-slug>/*.md`),
  it was simply never given the classification, WriteGuard gating, or registered note-relation every
  other durable HKA artifact in this system has. Diverges from the settled storage-substrate posture
  (session history as a companion-note-class, human-readable artifact) on those specifics.
  **RATIFIED (2026-07-02, epic #2778): Option B — chat becomes its own artifact class.** Not
  session-history-as-a-blob: a chat is a first-class artifact carrying a relationship to the note it
  belongs to, and one note may have several chats attached to it (note : chat is 1:N). Feature-sized;
  scoped in `docs/CANVAS_CHAT_SURFACE/DEFINE_CHAT_ARTIFACT_DURABILITY.md` +
  `PERSIST_CHAT_ARTIFACT_THROUGH_WRITEGUARD.md` (issues #2806/#2807) as a separate feature-breakdown
  pass (not invented in this artifact).
- **D-5 · Decisions cascade-delete with their object.** `decisions.object_id` is
  `ON DELETE CASCADE` (`202510241200_sot41_amg_core.py:87`) while `audit.object_id` is
  `ON DELETE SET NULL` (`:104`). Two canonical append-only logs, opposite loss semantics; if object
  cleanup (D-2) ever lands, judgment history silently vanishes. **fix-code** (align decisions to
  `SET NULL`; one forward-only migration). Follow-up filed — see below.
- **D-6 · Nothing in the system is garbage-collected.** Outbox delivered rows, audit rows, JSONL
  files, review decisions, commitments: no retention policy exists anywhere, and no doc states this
  as a decision. Unbounded growth is currently the *implicit* durability contract.
  **RATIFIED (2026-07-02, epic #2778): Option B, non-aggressive — cold storage, not deletion.** Old
  records are not deleted; as they age past active relevance they move to cheaper/cold storage,
  staying inspectable and recoverable rather than being destroyed. A tiering decision, not a
  retention-policy decision. KERNEL-12's dead-letter health signal remains the correct near-term
  watch mechanism; the cold-storage tier itself is a later per-class design, not scoped here.
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
- D-2, D-4, D-6 were **needs-owner-decision**; all three ratified 2026-07-02 on epic #2778 (see
  updated entries above). Resulting work:
  - D-2 (tombstone): no code change; ratification is the deliverable. Future event-triggered-decay
    lifecycle design is out of scope, tracked as input to RESEARCH-02/RESEARCH-04.
  - D-4 (chat-as-artifact, note 1:N chat): feature-sized — spawned as a separate `feature-breakdown`
    session rather than scoped inline here.
  - D-6 (cold storage, non-aggressive): no code change now; KERNEL-12 remains the near-term watch
    mechanism, cold-storage tiering is a later per-class design.

## Related docs

- `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md` (authority boundary this artifact refines)
- `docs/CONCEPTS/COMPANION_NOTE_CONTRACT.md`, `docs/CONCEPTS/STATE_AXES_CONTRACT.md`
- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md` (CW-1/CW-3/CW-5 context)
- `docs/RUNTIME_CORRECTNESS_KERNEL/README.md` (target-semantics owner)
- RESEARCH-02 consumer: `docs/architecture/formal-model.md` (to be authored under #2780)
