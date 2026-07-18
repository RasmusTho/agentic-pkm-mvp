State: Specification directory (design + bounded slice breakdown). Advisory until the child issues are delivered; the prod migration slice is operator-gated and lands staged, not implicitly. Owner-authorized direction (2026-07-05): make the judgment/decision log a human-readable, backup-bearing durable record with Postgres as a rebuildable projection.
Doc role: Specification (feature design + decomposition)
Authority: Design proposal grounded in current code (`app/services/decisions.py`, the two writer paths, four reader paths) and the owner contract `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md`. Subordinate to that contract and the doctrine; where it changes a claim, it updates the owning doc in the same slice.

# Decision Receipt Log — durable judgment log on the readable surface, Postgres as projection

## Why (owner ask + contract grounding)

The judgment log (`decisions`: the `review` / `evaluate` / `classification` verdicts the governance
pipeline records per object) lives **only in Postgres** today. It is one of three canonical,
non-rebuildable stores (`formal-model.md :: 5`, with `audit` and `outbox`) — losing the DB loses it,
and it is not backed up by the vault's iCloud/git durability like everything human-meaningful is.

The owner asked (2026-07-05) to make it human-readable and naturally backed up. The design that
follows is not an invention — it *closes a stated contract violation*:

- `MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md :: Leakage prevention rule 4`: "No code path may make
  the DB the de facto source of truth by writing values that exist nowhere on the durable surface. If
  a value must be durable, it belongs in the vault/companion/**receipt** set, mirrored *from* there."
  `decisions` is exactly such a DB-only durable value today.
- `MIRROR_RECEIPT_DECISION.md` defines a **receipt** as a human-legible accountability record
  (action, authority, basis, outcome). A judgment row (`allow`/`score`/`reasons`/`agent`) is
  receipt-shaped by that definition — it is a *receipt*, not a machine *mirror*.

So: **decisions are receipts; put them where receipts belong (the durable readable surface), and make
Postgres the rebuildable query index over them.** This mirrors KERNEL-05 (retrieval reads a durable
index; the in-memory store is a cache-through), applied to the judgment log.

## Current reality (verified, file:line)

- **Writers (two paths, to converge):** `app/services/decisions.py::insert_decision` (keys `review`
  via `app/agents/reviewer/agent.py`, `evaluate` via `app/agents/set_evaluator/agent.py`; fail-loud
  post-#2788) and the deprecated `app/stores/decisions.py::put_decision` (key `classification` via
  `app/agents/classifier/agent.py` and `app/agents/classify.py` — the latter still `except: pass`, a
  third silent-swallow site not previously catalogued).
- **Readers (all latest-wins per `(object_id, key)`):** `latest_decision()` consumed by
  set_evaluator (`review`), citation_checker (`classification`), projector (`evaluate`); plus the SQL
  function `public.latest_decision` behind `view_objects_ready_for_projection`; plus
  `app/jobs/backfill.py` existence-checks (`NOT EXISTS … FROM decisions`). Two of these are scans, not
  point lookups — so a **DB index/projection must remain** for them; text-only would be slow. This is
  why the design keeps Postgres as a projection rather than deleting it.
- **Identity coupling (shipped contract):** `decisions.object_id` is a canonical FK to
  `store_objects.object_id` (revision `7e4f2a1c9d30`), not to the retained `objects` compatibility
  table. Receipt writes still preserve continuity where that retained table has useful history:
  `resolve_vault_uuid()` uses the matching `objects.uuid` for a canonical object id when present,
  while fresh canonical-only objects carry `vault_uuid: null` because no frontmatter continuity
  identity has been proven. Rebuild first keeps a receipt's `object_id` when it is an existing canonical id; only
  otherwise does it attempt to re-link through the receipt's `vault_uuid` using the same retained
  UUID/canonical-id mapping. Historical receipts that already contain the former canonical-id
  fallback remain accepted by that same replay path. A receipt is an unresolved orphan only when
  neither route resolves.
  This keeps the compatibility mapping available for continuity without making `objects` the FK
  parent or claiming that every historical compatibility surface has been removed.
- **Volume:** low — one row per governance action, event-driven (not per-turn). JSONL-append is
  comfortably within budget.
- **Precedent to extend:** `app/services/companion_note.py` (WriteGuard-gated atomic markdown at
  `vault/<system_dir>/…`) and its `heal_log.jsonl` append sink are the "system-written durable
  artifact near the vault" pattern. The receipt log adopts the pattern **and** closes heal_log's gap
  (WriteGuard-gated from day one).

## Design

### Canonical store: a WriteGuard-gated, append-only decision-receipt log under the vault system dir

- Location: `vault/<system_dir>/receipts/decisions/` — dated JSONL shards
  (e.g. `decisions-YYYYMM.jsonl`) to bound file size and keep diffs small; append-only.
- One JSON object per decision, `schema_version`-stamped, carrying: `object_id` (runtime),
  `vault_uuid` (resolved at write time when the object has one; `null` for machine-only objects),
  `key`, `value` (the `allow`/`score`/`reasons`/`agent` envelope, `trace_id` folded in as today),
  `created_at`. Content is structured accountability, not prose — JSONL is the honest, greppable,
  diff-able, iCloud/git-backed fit (markdown was considered and rejected: decisions are structured
  verdicts, not narrative; see Rejected below).
- **WriteGuard-gated at the seam** (C-6): the log write asserts `assert_writes_allowed("decision.receipt")`.
  A blocked guard (safe_mode/unhealthy) **defers or fails the governance action loudly** — it never
  silently proceeds DB-only (C-8). This is the receipt half of "governed effect + receipt".
- **Receipt-before-ack (C-5/P-5):** the durable log append is the commit point; the DB projection is
  written *after* and is derived. If the projection write fails, the decision is still durable and
  the projection is rebuildable — so the log append is what the caller's success depends on.

### Postgres becomes a rebuildable projection

- The `decisions` table stays, serving `latest_decision()`, the SQL view, and backfill scans as the
  fast index — but it is now **derived**: `rebuild_decisions_projection()` replays the JSONL log into
  the table. Replay accepts an existing `store_objects.object_id` directly; when that id no longer
  exists, it re-links via the receipt's `vault_uuid` against retained `objects.uuid` continuity,
  including historical receipts that already carry the former canonical-id fallback. New
  canonical-only receipts carry `vault_uuid: null` and therefore depend on their canonical
  `object_id` remaining present. A doctor check asserts the projection matches the log
  (verify-the-verifier).
- This flips `runtime-semantics.md` row 12 canonicality: canonical = the vault receipt log; DB =
  projection. That doc update *resolves* the rule-4 tension the recon found (it aligns the advisory
  doc with the owner contract), and is bundled into the read-cutover slice.

### Backup consequence (closes the loop with the owner's original point)

Once decisions live in the vault, they ride iCloud/git backup automatically. The prod DB backup
(`local.prod-pgdump` → external SSD, hardened 2026-07-05) then only needs `outbox` + `audit` as
genuinely DB-only content — shrinking what the off-machine cold-storage work (#2965) must protect.

## Slice breakdown (bounded; only Slice 1 is buildable-now, nothing prod-touching until Slice 4)

1. **Durable receipt-log writer (additive, no prod change).** Introduce the WriteGuard-gated JSONL
   receipt log + `schema_version`; `insert_decision` writes the log first, then the DB (dual-write
   behind a default-on flag). DB stays canonical for now. Converge the deprecated `put_decision` /
   `classify.py` silent-swallow path onto the one guarded writer. `Verify:` writer + guard-blocked +
   receipt-before-ack tests. TCD: Sonnet/high.
2. **Projection rebuild + doctor.** `rebuild_decisions_projection()` replays the log into `decisions`;
   doctor check asserts DB == log; identity carries `vault_uuid` for rebuild re-linking. `Verify:`
   rebuild-equivalence test on a fixture log. TCD: Sonnet/high.
3. **Read cutover + doc truth.** Declare the log canonical, DB derived; update
   `runtime-semantics.md` row 12 and reconcile `MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md` (owner
   doc — bundled here, not a follow-up). Readers unchanged (still hit the fast projection). `Verify:`
   doc writeback + a rebuild-from-log-only integration test. TCD: Opus/high (owner-doc + authority).
4. **Prod backfill + backup-scope reduction (operator-gated, staged).** One-time export of existing
   prod `decisions` rows → the log; verify row counts; flip canonical; confirm the projection rebuilds
   identically; update the DB-backup scope note (#2965 / `reference_prod_db_backup`). I-C2 evolution
   protocol (backfill + dual-read window + doctor). **Not executed without operator ack.** TCD:
   Opus/xhigh (prod data migration).

   **Build-only portion delivered (issue #2973):** `export_decisions_to_receipt_log()`
   (`app/jobs/decisions_export.py`) — the DB→log export function itself — is built, tested
   (`tests/jobs/test_decisions_export.py`), and wired into a CLI group (`python -m app.cli decisions
   export|doctor|rebuild`). It is read-only over the DB, idempotent (safe to re-run), and fails loud
   rather than silently dropping a row it cannot faithfully place in the log. **Running it against
   prod, and the remaining flip-canonical / backup-scope-note steps, stay operator-gated** — the
   function existing does not execute the migration.

## SBS reconciliation (binding)

- **Conforms:** decisions are GOV receipts; putting the canonical copy on the durable readable surface
  with PDM as the projection is exactly `MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md` rule 4 +
  the receipt-authority definition. WriteGuard-at-seam conforms to the governed-write protocol.
- **Extends:** a new durable receipt-log surface under the vault system dir (OEF/GOV-adjacent),
  extending the companion-note/heal-log precedent with WriteGuard gating. Routes to CES with the
  runtime-semantics row-12 + contract update in Slice 3.
- **No reshape:** no boundary ownership moves; this realigns code + advisory doc to the existing owner
  contract.

## Rejected alternatives

- **Markdown instead of JSONL:** decisions are structured verdicts (`allow`/`score`/`reasons`), not
  prose; markdown would be prettier but lossy/awkward to append and machine-read. JSONL is greppable,
  diff-able, backed-up, and matches the `heal_log.jsonl` precedent. (Reversible if the owner prefers a
  rendered markdown *view* later — that would be a projection, not the canonical store.)
- **Delete Postgres for decisions (text-only):** two readers scan (`view_objects_ready_for_projection`,
  backfill existence-checks); text-only would force full-log scans. Keep the DB as the index.
- **Keep DB canonical, add a text mirror:** leaves the contract rule-4 violation in place and the
  non-rebuildable-backup gap open. The point is to make the readable surface canonical.

## Related

- `app/services/decisions.py`, `app/stores/decisions.py` (writers); `app/jobs/backfill.py`, the SQL
  `latest_decision` view (readers)
- `docs/CONCEPTS/MACHINE_MIRROR_AND_DB_AUTHORITY_CONTRACT.md` (rule 4 — the grounding), `MIRROR_RECEIPT_DECISION.md`
- `docs/architecture/runtime-semantics.md` row 12 + `:: 5` coupling caveat; `docs/architecture/formal-model.md :: 5`
- `docs/foundation/ARCHITECTURAL_CONSTITUTION.md` C-4 (one truth + rebuildable projection), C-5/C-6/C-8
- `reference_prod_db_backup` / #2965 (the backup-scope reduction this unlocks)
