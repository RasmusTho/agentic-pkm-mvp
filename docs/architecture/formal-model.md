State: Advisory research artifact (RESEARCH-02, issue #2780, epic #2778; 2026-07-02). Subordinate to `docs/DOCS_INDEX.md` and owner contracts. Models **current reality** on `main` at `e8cbc615`+; target-state deltas are explicitly marked. Ratification into owner contracts is a separate owner decision.
Doc role: Reference (architecture analysis)
Authority: Evidence-based; anchors verified against live code by two dedicated mutation-surface sweeps (API routes; CLI/worker/agent initiators) plus the RESEARCH-01 semantics baseline. Where this model and an owner doc disagree, the divergence is listed — the owner doc wins until resolved.

# Yggdrasil Formal Model — State, Transitions, Invariants, Consistency, Failure Domains

The smallest complete formal model of the running system. Types and semantics come from
`docs/architecture/runtime-semantics.md` (RESEARCH-01, including the ratified D-2/D-4/D-6
decisions); transitions were enumerated by walking every mutation initiator: the outbox dispatch
table, every API route, every CLI command, every worker/watcher-initiated write, and every
agent-cognition→write seam. Notation is deliberately lightweight: typed sets and pre/post
conditions, readable by the owner and consumable by Sonnet-tier implementers.

## 1. State

The system state is the tuple **Σ = (V, P, S, J, L)** plus volatile process memory **M** (explicitly
*not* state — invariant M1 below).

```
V  (vault, canonical plane — FD-V)
   V.notes        human notes (uuid advisory, path identity)
   V.companions   companion notes (continuity set with V.notes)
   V.commitments  commitment artifacts (commitment_id)
   V.settings     settings/*.md incl. vault.md, local.md, @Settings/* compiled blocks
   V.memories     materialized semantic-memory artifacts
   V.chats        .chats/<note>/*.md session logs   [D-4: future first-class artifact, note 1:N chat]

P  (Postgres, derived-plus-canonical-logs plane — FD-P)
   P.objects      object rows (object_id; tombstone semantics ratified, D-2)
   P.file_state   path → hash/mtime sync bookkeeping
   P.vectors      store_vector_index (+ vector_index_meta identity singleton)
   P.relations    store_relations, store_relation_memberships
   P.outbox       the event log (topic, payload, delivered_at, attempts)
   P.decisions    judgment log (canonical, append-only)
   P.audit        trace log (canonical, append-only)
   P.memkv        agent_memories (short-term, decay-by-timestamp)

S  (SQLite files, one failure domain per file — FD-S)
   S.proposals    panel proposal + confirm-idempotency store (panel_confirmation.sqlite3)
   S.reviews      memory review decisions (review_decisions.sqlite3)
   S.leavepoint   leave-point cursor trace
   S.builderops   BuilderOps records (builder plane; outside product authority)

J  (append-only JSONL sinks — FD-J)
   J.indexlog     INDEX_OUTBOX_PATH mirror of outbox events (advisory audit, never truth)
   J.recall       recall-activation receipts        (runtime/agent_memory/recall_receipts.jsonl)
   J.synthesis    ask-synthesis activation receipts (runtime/activation/ask_synthesis_receipts.jsonl)
   J.reachout     proactive reach-out/suppression receipts
   J.material     memory materialization receipts

L  (app-local machine state)
   L.vaults       known-vaults registry (AppLocalSettingsStore)

M  (volatile — cache only, loses nothing on restart EXCEPT known gaps)
   retrieval hybrid store (KERNEL-05 makes it a cache of P.vectors)
   review-queue candidates · canvas session edit history · bundle registry
   SettingsWriteReceipt (D-1 gap, #2787) · chat turns beyond session log (D-4 gap)
```

## 2. Transitions

Notation: `T‹name› [initiator] : pre ⟹ post ; guard ; event`. `WG(a)` =
`WriteGuard.assert_writes_allowed(a)`. `⊕` = append. `evt(t)` = row appended to `P.outbox` with
topic `t` (and best-effort mirror to `J.indexlog`). Anchors are representative, not exhaustive.

**The reference shape.** `T-capture` is the strongest transition in the system and the shape every
mutating transition should converge to (target-state, KERNEL-01/02):

```
T-capture [human, POST /api/companion/capture]  (app/api/routes/capture.py:234-304)
  pre:  vault selected ∧ WG(capture.append) ∧ decision-token issued (GovernedWriteAdapter)
  post: V.notes.inbox ⊕ text ∧ evt(capture.inbox.appended) DURABLE
  ack:  ONLY after the event row is persisted — else 500 authority_receipt_persistence_failed
  note: the vault append precedes event persistence and is not rolled back on the 500 —
        receipt-before-ACK, not receipt-before-write (the honest I-E3 reading)
```

### 2.1 Human/API-initiated

```
T-edit-body [human/agent, canvas edits · workspace update/body · note/save]
  pre:  session/scope checks ∧ WG(action) ∧ optional content_hash match ∧ body frontmatter-free
  post: V.notes[n].body ← b′ ; NO event (watcher observes later — eventual, seam C1)
  anchors: app/chat/canvas_writer.py:96-126, app/api/routes/companion.py:4209-4310, 4354-4411
  ⚠ note/save's WG deliberately FAILS OPEN on evaluation error (app/api/routes/companion.py:4365-4369)

T-propose-governance [human/agent, canvas governance/coauthor · vault-browser queue-review]
  pre:  WG(canvas.governance_action) ∧ valid GovernanceActionType ∧ artifact identity resolvable
  post: S.proposals ⊕ proposal ; V untouched (proposal-only by design, governance_router.py:70-145)

T-panel-confirm [human, POST /api/panel/confirm]  (app/panel/confirmation.py:713-731; the write seam it invokes lives in a DIFFERENT package: app/agents/panel_agent/runtime.py)
  pre:  proposal ∈ S.proposals ∧ idempotency_key fresh ∧ WG(panel.confirm) ∧ ¬same-turn
  post: execute_panel_intent: V.notes[n] ← writeback ∧ P.objects mirror (emit_outbox=False)
        ∧ evt(panel.action.logged | panel.action.blocked) ∧ S.proposals idempotency recorded
  ⚠ the write seam itself (app/agents/panel_agent/runtime.py:601 raw write_text;
    app/agents/panel/writeback.py:196) has NO WG — the guard is caller-side convention
    (API callers pre-guard; CLI `panel run` and the worker PANEL_SCAN_REQUESTED path do NOT).
    The checkbox path additionally performs an UNGUARDED compensating vault write from an
    exception handler (rollback, app/panel/checkbox_projection.py:495-496) — see Divergence F-A

T-settings-update [human, POST /api/companion/vault/settings]  (app/vault/settings_service.py:229-330)
  pre:  vault selected ∧ key known ∧ ¬blocked ∧ WG(settings.write)
  post: V.settings ← value ∧ M.SettingsWriteReceipt (volatile — D-1, #2787) ; NO event

T-vault-select/init/reload [human]  (app/api/routes/companion.py:812-1132, app/vault/manager.py:300-434)
  pre:  loopback/API-key ; init: confirm-flag when target non-empty
  post: V.settings scaffold/heal (vaultId/localInstanceId) ∧ L.vaults (if remember) ; NO WG, NO event
  note: select/init/reload — and lazy load_last_active from GET routes — may WRITE: the heal
        happens in validate_vault → _ensure_frontmatter_id (app/vault/manager.py:588-607) via
        markdown_store.write_frontmatter, gated by role-based persist flags, NOT by WriteGuard

T-review-decide [human, POST memory/review-queue/{id}/decision]  (app/api/routes/companion.py:4685-4789)
  pre:  candidate PENDING ∧ (accept ⇒ promotion gate passes)
  post: S.reviews ⊕ decision ; accept ⇒ V.memories ⊕ artifact (WG-gated, materialization.py:42)
        ∧ S.reviews.terminal←1 AFTER vault write ∧ J.material ⊕ receipt
  two-phase: decision durable first, terminal flag only after materialization (blocked ⇒ re-pending)

T-ingest-api [any caller, POST /ingest]  (app/api/routes/ingest.py:22)
  pre:  well-formed payload — NOTHING ELSE (no WG, no vault check, no auth beyond app-level)
  post: evt(ingest.object.created) ONLY — despite its name, insert_object_and_outbox
        (app/services/outbox.py:247-264) writes no object row; P.objects materializes
        asynchronously via T-materialize below            — see Divergence F-D

T-materialize [worker → INGEST_OBJECT_CREATED]  (app/services/indexer.py:93)
  pre:  event delivered (at-least-once)
  post: P.objects ⊕ row via save_object(emit_outbox=False) — the event that CAUSED this row is
        its own record; reading P.objects immediately after T-ingest-api is NOT legal

T-session [human, canvas open/close]  : V.chats ⊕ log ∧ S.leavepoint ← cursor ; no WG ; no event
T-ask [human, POST /api/ask]          : reads Σ ; J.recall ⊕ receipts ∧ J.synthesis ⊕ receipt
                                        (durable appends from a "read" — bypass P.outbox entirely)
T-uuid-heal [system, many entry points incl. GET /companion/workspace]
  pre:  note lacks uuid ∧ WG(ensure uuid)
  post: V.notes[n].frontmatter.uuid ← fresh  (a WRITE reachable from GET — see invariant Q4)
```

### 2.2 Event-loop transitions (worker consumes `P.outbox`; at-least-once)

```
T-sync [watcher → INGEST_VAULT_CHANGED]  (app/services/vault_sync.py:334-512)
  pre:  note readable ∧ hash changed vs P.file_state
  post: P.objects upsert ∧ P.file_state upsert ∧ evt(ingest.object.*)
  ⚠ NOT atomic today (three statements, five commits) — KERNEL-01 (#2763) makes this one tx

T-embed [worker → INDEX_EMBEDDING_REQUESTED]  (app/indexer/consumer.py:85-179)
  pre:  object exists ∧ identity gate (dim match; fallback reconcilable)
        — text field is read but NOT guarded: an empty text embeds (consumer.py:116-125)
  post: P.vectors upsert (identity-stamped) ∧ evt(index.embedding.created | .failed)

T-delete [human deletes note → watcher → delete_note → INGEST_OBJECT_DELETED]
  post: P.file_state rows deleted ∧ P.objects.path←NULL (TOMBSTONE — ratified D-2)
        ∧ purge_vectors(P.vectors) [indexer path] ; worker handler itself is a no-op
  future (owner note, not scoped): event-triggered relevance decay lifecycle
        active → archived → forgotten (value lost at a triggering event, not TTL)

T-promote [worker/CLI → PROMOTE_INTENT_CREATED]  (app/promotion/consumer.py:262)
  pre:  intent event ∧ WG(promotion frontmatter)
  post: V.notes[n].frontmatter ← promotion ∧ P.objects mirror (emit_outbox=False)
        ∧ evt(promote.done, promotion.transition.applied)

T-retry / T-deadletter [worker]  (app/workers/outbox_worker.py:581-728)
  transient failure < budget ⇒ re-enqueue with count ; budget exhausted ⇒
  evt(outbox.event.dead_lettered) ∧ ack original      [KERNEL-12 makes this loud]

T-companion-sync, T-move-workbench, T-moment, T-reachout — all WG-gated at their seams
  (companion_note.py:141 · vault/actions.py:299 · relevance/materialization.py:65 ·
   attention_loop.py:115, blocked ⇒ forced defer with writes_blocked=true)
```

### 2.3 Operator/CLI-initiated

```
T-rebuild / T-reconcile [operator]  (app/cli/index_rebuild.py:198-579)
  post: P.vectors rewritten/re-embedded ; direct writes, NO event ; doctor verifies after
T-scaffold [operator/human: vault init, yggdrasil-init, layout-ensure]
  pre-vault-selection bootstrap: idempotent file scaffold. yggdrasil-init now CONSULTS WG at the
  scaffolder seam (app/settings/yggdrasil_scaffolder.py::scaffold, action "yggdrasil.scaffold",
  asserted before the first mkdir ⇒ blocked path is atomic: zero dirs/files, non-zero CLI exit).
  A NAMED bootstrap escape (DEFAULT_BOOTSTRAP_ACTIONS in app/write_guard.py) lets a genuine
  pre-selection provision through under safe_mode/unhealthy — a denying guard still blocks it, so
  this is a consulted seam, not "outside WG" (#2877). The knowledge write port itself now also
  asserts WG unconditionally (app/knowledge/write_ops.py::write_note_from_absolute, default action
  "knowledge.write_note") — the scaffolder's own nested writes thread the "yggdrasil.scaffold"
  escape action through to the port so provisioning still survives safe_mode/unhealthy end-to-end
  (#2910). Layout-ensure provisioning (app/vault/layout.py's two create-if-missing writes, reached
  by vault-layout-ensure CLI, uat seed, and ingest-time ensure_vault_layout) carries its own
  registered escape "vault.layout_ensure" ∈ DEFAULT_BOOTSTRAP_ACTIONS: creating the FIRST
  vault.layout.md is the write the guard's own health evaluation depends on
  (load_health_settings → load_layout raises until the note exists), so the escape is checked
  BEFORE snapshot evaluation — a registered bootstrap action survives an UNEVALUABLE guard, while
  every non-registered action still fails closed on evaluation error (P-4). The watcher tick
  additionally degrades any WritesBlockedError from inside ingest to its skipped_writes_blocked
  accounting instead of crashing (#2910, defense-in-depth).
T-settings-compile [operator: settings compile/watch]  (app/settings/writeback.py:23-42)
  post: V.settings @Settings/*.md ← compiled blocks ; ⚠ NO WG, NO event — Divergence F-B
T-bootstrap-ddl [worker boot]  (app/services/outbox.py:68-73, called from outbox_worker.py:1027)
  post: outbox schema DDL at worker start, with a nested `except Exception: pass` — the same
        create-on-boot class KERNEL-04 (#2766) converts to assert-only for store tables; the
        outbox bootstrap should ride that change (comment posted on #2766)
Heartbeat/telemetry writers (runtime/*.json liveness files, sync-latency appends to the J audit
path) are background-loop writes to NON-DOMAIN observability state — declared outside Σ.
Failure receipts appended from exception handlers (memory/moment materialization failure
receipts, audit FK-fallback insert) are LEGITIMATE Q3 transitions: receipt-on-failure is the
pattern working as designed, not a violation.
Dev/CI harness writers (smoke, alpha flows, uat seed) are structurally identical writes and are
EXCLUDED from this model by declaration; they must never run against a real vault.
```

### 2.4 Agent plane

LLM cognition reaches durable state only through the seams above. Gate placement today:

| Agent output → write | Seam | Gate at the seam |
|---|---|---|
| Canvas co-author edit | `CanvasWriter.apply_edit` | WG + structural (body-only, in-vault) ✓ |
| Governance intent | `GovernanceRouter` → S.proposals | WG + proposal-only ✓ |
| Memory materialization | `materialize_promoted_memory` | WG + human decision precedes ✓ |
| Commitment persist | `commitment_persistence` | WG, atomic-or-absent ✓ |
| **Panel writeback** | `app/agents/panel_agent/runtime.py::execute_panel_intent` → raw `write_text` (confirm/idempotency live separately in `app/panel/confirmation.py`) | **none at the seam** (F-A) ✗ |
| Metadata mirrors (classifier/planner/etc.) | `save_object(emit_outbox=False)` | Pydantic only; no event (F-E) |
| Note-hygiene (dormant, no callers) | `_write` | none — latent (F-F) |

## 3. Invariants

Model invariants, mapped to the registry (`docs/testing/invariant-tests.md`, 28 named; 29 rows in its coverage map) and the
audit kernel (`docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md` §2). ✓ = holds today;
✗ = violated today (anchor given); ◊ = target-state (kernel task named).

**Q — conserved quantities** (never destroyed except at named boundaries):
- **Q1 Human content.** Only a human deletes `V.notes`; machine writes are additive or scoped
  (body-edit, frontmatter keys); deletion leaves a P.objects tombstone (D-2 ratified). ✓
- **Q2 Lineage.** `derived_from`/provenance chains and idempotency identities are never truncated;
  tombstones preserve FK anchors. ✓ structurally; ✗ decisions FK CASCADE would break it (#2788).
- **Q3 Authority receipts.** decisions/audit/receipt events are append-only, never edited. ✓ —
  but receipt *durability* is violated for settings (D-1/#2787) and receipt *emission* precedes
  ack only in T-capture (◊ generalize: I-E3).
- **Q4 Read purity.** A read transition mutates nothing durable. ✗ three ways: uuid-heal from GET
  (workspace), identity-heal from lazy vault load, ASK's receipt appends. Model verdict: these are
  legal only if reclassified as explicit system transitions (heal-on-read is T-uuid-heal, a write
  transition triggered by a read) — the *undocumented* ones are the defect, not healing itself.

**C — consistency (per seam, §4).** C1–C9 with reconciliation mechanism or explicit UNRECONCILED.

**Kernel mapping (bidirectional):**

| Model element | Kernel | Registry | Status |
|---|---|---|---|
| T-sync atomicity | I-S2 | — | ◊ KERNEL-01 #2763 |
| evt() idempotency keys mandatory | I-E1 | — | ◊ KERNEL-02 #2764 |
| handler idempotency (at-least-once) | I-E2 | — | ◊ KERNEL-11 #2773 |
| ack-after-effect (T-capture shape) | I-E3 | — | ✓ capture; ◊ everywhere else |
| dead-letter loud | I-E4 | — | ◊ KERNEL-12 #2774 |
| typed topics | I-E5, I-C1 | — | ◊ KERNEL-08 #2770 |
| single truth: M = cache(P.vectors) | I-D3 | #3 store_no_naked_vectors (partial) | ◊ KERNEL-05 #2767 |
| transform provenance on P.vectors | I-D1 | #4 provenance_survives_derivation | ◊ KERNEL-06 #2768 |
| identity gate on P.vectors | I-D2 | — | ✓ CTI-1 |
| no silent fallback (stores, decisions writer) | I-S4 | — | ✗ decisions.py:43-45 → #2788 |
| UNKNOWN route, no default action class | I-A2 | — | ◊ KERNEL-07 #2769 |
| envelope/scope prefilter on app retrieval | I-A5 | #5-#9, #18-#21, #26 | ◊ KERNEL-10 #2772 |
| WG at every V-write seam | I-A3 | #13 authority_transition… (spirit) | ✓ #2910 (P-1 static gate + runtime property; F-C exempted, named) |
| memory non-canonical / promotion governed | — | #10, #11, #22-#25 | ✓ (review→materialize chain) |
| projection ≠ evidence, observability ≠ policy | — | #12, #17 | ✓ doc/xfail as registered |

**Gaps, model → registry (new invariant candidates — input to RESEARCH-03/#2781):**
1. **Guard-at-seam:** WG must be asserted at the write seam itself, not by caller convention
   (violations F-A, F-B; latent F-F). Root cause is one level deeper: the knowledge write port
   `app/knowledge/write_ops.py::write_note_from_absolute` is itself unguarded, and five sites
   reach the vault through it with no WG (settings writeback, note_hygiene, vault-layout
   scaffold, manager identity-heal via write_frontmatter, checkbox rollback). The deep fix
   candidate is asserting WG inside the port with a named bootstrap escape for pre-selection
   scaffolding (T-scaffold) — recorded for RESEARCH-03 as the strongest form of this invariant.
   The bounded seam-local form landed for the vault-layout scaffold site: `yggdrasil-init`'s
   scaffolder now asserts WG at its own seam with the named bootstrap escape
   (`"yggdrasil.scaffold"` ∈ `DEFAULT_BOOTSTRAP_ACTIONS`), so a genuine new-vault provision
   survives `safe_mode`/`unhealthy` while a denying guard blocks it atomically (#2877). **#2910
   closed the deep fix and the remaining three named sites**: the knowledge write port itself
   (`write_note_from_absolute`) now asserts WG unconditionally before any I/O (default action
   `"knowledge.write_note"`; callers needing the bootstrap escape pass their own action through);
   identity-heal (`VaultManager._ensure_frontmatter_id`, action `"vault.identity_heal"`) is WG-gated
   and `validate_vault` converts a denying/raising guard into the same loud `invalid` VaultContext
   an `OSError` persist failure already reached; checkbox-rollback
   (`app/panel/checkbox_projection.py`'s exception-handler compensating write) is covered
   automatically now that the port itself is guarded. `tests/properties/test_guard_at_seam.py`
   pins the class with a static gate (every `write_frontmatter` call site classified
   guarded/out-of-scope; the port needs no per-site census anymore) plus P-1/P-4 runtime properties
   sampling the three registered seams. Settings writeback stays gated by #2809; note_hygiene by
   #2810.
2. **Event-completeness:** every `P.objects`/`P.vectors` mutation has a corresponding event, or is
   declared a *mirror* in a registered list — today `emit_outbox=False` writes are invisible to
   replay (F-E; eight call sites named in §4/C8).
3. **Read purity (Q4):** no durable write on a GET/read path except registered heal transitions.
4. **Fail-closed guards:** a WG evaluation error blocks the write. #2910 pins this for the three
   named write seams above (`test_raising_guard_blocks_write`); `note/save` deliberately fails open
   today — divergence F-C, named exemption, owner decision pending on epic #2778.
5. **Receipt-before-ack (T-capture shape)** as the general mutating-transition contract.

**Gaps, registry → model:** none structural — the cross-scope/envelope invariants (#5–#9, #16,
#19–#21, #26–#28) live in the semantic overlay (`yggdrasil_runtime`) that KERNEL-10 promotes into
`app/` retrieval; the model treats them as the admissibility precondition of T-ask/T-retrieve once
promoted.

## 4. Consistency model — every dual-store seam

| # | Seam | Reconciler | Assumption made |
|---|---|---|---|
| C1 | V.notes ↔ P.objects/file_state | watcher tick → T-sync (hash-based) | eventual, tick-latency; edits between ticks invisible |
| C2 | P.objects ↔ P.vectors | embed events; doctor detects; `reconcile` repairs | eventual; incremental only after KERNEL-06 |
| C3 | P.outbox ↔ J.indexlog | none — dual best-effort write | **UNRECONCILED** (CW-1; J is advisory by declaration) |
| C4 | M.retrieval ↔ P.vectors | none today | **UNRECONCILED** → KERNEL-05 makes M a rebuildable cache |
| C5 | V.companions ↔ V.notes | worker companion-sync | eventual; heal-after-crash converges |
| C6 | S.proposals ↔ V outcome | panel confirm + idempotency store | exactly-once effect per key; proposal may outlive note change |
| C7 | S.reviews ↔ V.memories | two-phase terminal flag | decision-first; blocked materialization re-pends |
| C8 | P.objects mirrors (emit_outbox=False) ↔ event log | none | **UNRECONCILED** — replay from P.outbox alone under-produces P.objects; 11 production sites: app/services/indexer.py:93 (the T-materialize sink itself), app/promotion/consumer.py:66-97, app/agents/panel_agent/execution.py:38-62, app/watcher/vault_watcher.py:124-136, app/agents/panel_agent/runtime.py:88-98, app/agents/panel/writeback.py:171-197, app/agents/planner/agent.py:116-118, app/agents/planner/graph.py:237, app/agents/normalizer/agent.py:161, app/ingest/api.py:120, app/ingest/vault_alpha.py:527 (+3 in cli/smoke.py, harness-excluded) |
| C9 | V.settings/local.md ↔ runtime settings | watcher settings-delta re-persist | eventual; re-persist is WG-gated; loop terminates on hash equality |

Stated plainly: **replay(P.outbox, V) reconstructs P only up to C3/C4/C8** — the event log is not
yet a complete transition journal. KERNEL-01/02/05 close most of it; C8 needs the
event-completeness invariant (gap 2) to close fully.

## 5. Failure domains

| Domain | Fails together | Rebuildable from | Non-rebuildable content (blast radius) |
|---|---|---|---|
| FD-V (vault, iCloud fs) | notes, companions, commitments, settings, memories, chats | — (canonical; iCloud sync is the only replica) | everything human-authored |
| FD-P (Postgres) | objects, file_state, vectors, relations, outbox, decisions, audit, memkv | objects/file_state/vectors/relations: V + re-ingest (with new object_ids — see caveat) | **outbox history, decisions, audit** — canonical logs with NO backup (observability audit: no DB backup) |
| FD-S (per file) | each sqlite independent | proposals: re-propose; reviews: NOT rebuildable | review decisions (promotion preconditions) |
| FD-J | each JSONL independent | advisory — losable by declaration | activation/recall audit trail |
| FD-M | process | restart | session context (D-4 until chat-as-artifact), settings receipts (D-1) |

**Coupling caveat (the model's sharpest finding):** rebuilding FD-P from FD-V mints new
`object_id`s (runtime-assigned identity, RESEARCH-01 class 4), which orphans every
`decisions`/`audit` row that survived — so FD-P's canonical logs are only meaningful *together
with* the objects rows they reference. Tombstone ratification (D-2) makes those rows stable
anchors; a vault-uuid-keyed identity (or persisted object_id↔uuid map) would decouple the
domains. Flagged to CES as an extend-candidate, not enacted here.

## 6. SBS reconciliation (binding, per `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`)

- **Conforms:** the state tuple maps 1:1 onto L2 boundaries as established in
  `runtime-semantics.md :: SBS boundary mapping` (V→HKA/SIP, P→PDM/DRI, receipts/audit→GOV,
  memory→MEM, J→OEF, agents→CAO, execution seams→EXE). The transition catalog conforms: proposals
  (CAO) are separated from execution (EXE) which is separated from governance gating (GOV).
- **Code-vs-SBS violations (not reshapes — fix toward the SBS):** F-A/F-B/F-F are EXE performing
  governed effects without the GOV gate at the seam; C8's mirrors blur PDM (event-logged state)
  with ad-hoc cache writes. The SBS is right; the code diverges.
- **Extend-candidates flagged to CES (not enacted):** (a) J receipt sinks as a named OEF audit
  substrate distinct from PDM's outbox (today they are unnamed side files); (b) decoupling FD-P
  identity from runtime object_id (§5 caveat); both route via SBS operationalization plan / ADR.
- **No reshape proposed.**

## 7. Divergences found by this pass (beyond RESEARCH-01's D-1…D-7)

- **F-A · Panel writeback seam unguarded.** `execute_panel_intent` writes vault markdown via raw
  `write_text` (`app/agents/panel_agent/runtime.py:601`) with no WriteGuard at the seam; two API
  callers compensate caller-side, CLI `panel run` and the worker `PANEL_SCAN_REQUESTED` path do
  not. **fix-code** — enforce WG inside the seam. Follow-up filed.
- **F-B · Settings compile writeback unguarded.** `app/settings/writeback.py` (+ compiler call
  sites) writes `V.settings @Settings/*.md` with no WG and no event. **fix-code.** Follow-up filed.
- **F-C · note/save WriteGuard fails open** (`app/api/routes/companion.py:4365-4369`, deliberate per comment).
  Human-edit availability vs. gate integrity. **needs-owner-decision** — surfaced on epic #2778.
- **F-D · `POST /ingest` is guardless** (`app/api/routes/ingest.py:22`): no WG, no vault/selection check; any
  well-formed payload becomes a P.objects row + event. Acceptable for a trusted-LAN dev seam,
  undocumented as such. **needs-owner-decision** (document trust posture vs. add gate) — surfaced
  on epic #2778.
- **F-E · Mirror-write class (`emit_outbox=False`, no WG)** — eight call sites (C8) make the event
  log an incomplete journal. **fix-code as a class** via the event-completeness invariant
  (registered-mirror list or emitted events); reconciled with KERNEL-02/#2764 scope rather than a
  parallel fix. Recorded for RESEARCH-03 property synthesis; no separate issue filed.
- **F-F · `note_hygiene` agent writes unguarded and is orphaned** (`app/agents/note_hygiene/
  agent.py:57`, no non-test callers). **fix-code (cheap):** guard-or-remove. Follow-up filed.

## 8. Adversarial review record

Per the issue's validation contract, an independent adversarial pass attempted to construct
(a) transitions legal per this model but illegal in observed code, and (b) observed behavior this
model forbids. Findings and dispositions are recorded in this section by the pass itself.

An independent Opus-tier pass (2026-07-02) attacked the draft in both directions and spot-checked
anchors. **Corrections applied to this published version** (all verified against code):

1. *breaks-model:* T-ingest-api's post-condition wrongly claimed a synchronous `P.objects` row;
   `insert_object_and_outbox` writes only the event — split into T-ingest-api + T-materialize.
2. *weakens-model:* the C8 mirror census was incomplete (7 listed, 11 real — including the
   T-materialize sink `app/services/indexer.py:93`); census corrected.
3. Registry count corrected (28 named, not 36). 4. Route-file anchors prefixed to real paths.
5. Confirm-store vs write-seam package split disambiguated. 6. T-embed's non-existent
   "text extractable" guard removed (empty text embeds unguarded).

**Attacks that failed (the model held), abridged:** T-panel-confirm without a prior proposal is
impossible (`UnknownProposalError`, app/panel/confirmation.py:718-720); no machine path truncates
or deletes vault note bodies (Q1 holds); no UPDATE/DELETE exists against decisions/audit rows —
the one UPDATE is S.reviews' modeled two-phase terminal flag (Q3 holds); no hidden boot-time
mutation initiator (API lifespan runs a read-only preflight only); all nine KERNEL-nn↔issue
mappings match the spec directory; F-A/F-C/F-D/F-F, the decisions silent-fallback, the FK
asymmetry, and the live audit writer were all re-confirmed against code. Net verdict: behaviorally
sound; every §7 divergence is real; no new forbidden behavior found beyond §7.

## Related docs

- `docs/architecture/runtime-semantics.md` (types/semantics baseline; ratified D-2/D-4/D-6)
- `docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md` (kernel this model grounds)
- `docs/RUNTIME_CORRECTNESS_KERNEL/README.md` (target-state owner for ◊ items)
- `docs/testing/invariant-tests.md` (registry; RESEARCH-03/#2781 consumes §3's gap list)
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md` (+ `docs/architecture/SBS_*`) — §6 reconciliation
