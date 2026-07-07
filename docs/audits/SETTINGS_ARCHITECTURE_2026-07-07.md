State: Advisory audit snapshot, 2026-07-07. Anchors reflect `origin/main` (8d871f9c) at the audit date. Subordinate to `docs/DOCS_INDEX.md` and owner contracts; owner docs win on disagreement. Owner ruled Option B (§5) the same day; executable form is `docs/SETTINGS_SPINE/` (parent feature issue #3156, children #3159-#3166).
Doc role: Reference (audit snapshot)
Authority: Evidence-based structural analysis of the settings architecture across Yggdrasil (core runtime, Companion UI, Heimdal, Mimer client contract, app-local/instance layer). Every claim carries a `file:line` or doc anchor. Advisory only.

# Settings Architecture Audit — 2026-07-07

Charter: inventory every settings surface (actual vs documented source of truth), find where the
"human-friendly md files, ingested into runtime" design holds and where it breaks, resolve the
pre-vault sequencing question, and propose a target design covering both current state and the
future wanted state.

## 1. What exists today — the substrate inventory

Five (plus two auxiliary) settings substrates coexist with **no shared abstraction** — they are
connected only by the low-level `WriteGuard` write primitive, not by a settings model:

| # | Substrate | Source of truth | Read cadence | Writable? | Receipted? |
|---|---|---|---|---|---|
| A | System settings YAML | `vault/_system/settings/system-settings.yaml` (`app/config/paths.py:193-216`) | per-call, mtime-cached (`app/services/settings.py:33-48`) | read-only | — |
| B | Vault-scoped md settings | `<vault>/settings/*.md` (`app/vault/settings_service.py:26-33`) | per-request, uncached (`settings_service.py:395-427`) | yes (`update_setting`, `:288-393`) | **yes** — only receipted writer (`SETTINGS_WRITE_RECEIPT`, `:372-379`) |
| C | Compiled runtime bundle | `vault/@Settings/*.md` → `runtime/settings/*.yaml` (`app/settings/compiler.py:35,310-444`) | memoized singleton (`app/settings/runtime.py:115-120`) | auto-heal writeback only (`writeback.py:36-57`) | in-process bus event only, not durable |
| D | Env pydantic `Settings` | env / `.env` (`app/settings/__init__.py:25,82`) | once at import; restart-required | no | — |
| E | Heimdal control notes | `<vault>/_heimdal/**` (`app/heimdal/settings_notes.py:481-495`) | on demand | yes, field-level authority (`:110-112,653-681`) | no |
| F | App-local instance store | `app-local.md` at XDG/AppSupport (`app/vault/app_local.py:61-86`) | on load | yes | no |
| G | Companion UI local prefs | browser `localStorage` (`settings_drawer.py:96-98`) | client-side | yes | — (declared non-vault by design) |

Two objects are both named "settings" with zero shared code (`app.settings.Settings` env singleton
vs `app.vault.settings_service.SettingsService`) — confirmed no cross-imports.

## 2. Ranked findings (systemic impact = blast radius × silence of failure)

### F1 — The md→runtime ingestion pipeline is never invoked by any running service (silent-default)

Stack C is the designed "human-friendly md, compiled into runtime" mechanism, and it is the SoT for
LLM routing, embeddings, the ask prompt, planner, ingest, outbox worker, and observability
(consumers: `app/components/llm/router.py:113`, `app/components/embeddings/legacy.py:192`,
`app/agents/ask/utils.py:14`, `app/planner/events.py:122`, `app/ingest/vault_alpha.py:58`,
`app/workers/outbox_worker.py:120`, `app/observability/status_service.py:810`). But
`compile_all()` is invoked only by the manual CLI (`app/cli/__init__.py:1524-1556`) and CI
(`.github/workflows/settings-ci.yaml:36`). No service startup path, compose service, or lifespan
hook calls it; `runtime/settings/` is gitignored (`.gitignore:51`). **In any container that never
had `settings compile` run, every vault-authored `@Settings/*.md` value is silently replaced by
pydantic code defaults.** The documented promise (`docs/SETTINGS.md:21-34`) is machinery-complete
and wire-cut. This is the same false-green class the correctness-kernel audit targeted.

### F2 — Four documented/actual vault-settings locations

- `<vault>/settings/` — stack B and the documented scaffold (`docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md:123-138`)
- `<vault>/_system/settings/` — stack A default (`app/config/paths.py:215-216`) and `docs/ENVIRONMENTS.md:30`
- `<vault>/@Settings/` — stack C source (`docs/SETTINGS.md:26`, `compiler.py:35`)
- `<vault>/_system/Settings/health.md` — health settings, fourth spelling (`app/settings/health_settings.py`)

Three owner-adjacent docs each present a different location as canonical without reconciling
(`VAULT_AND_SETTINGS_CONTEXT.md:123-138` vs `ENVIRONMENTS.md:30` vs `SETTINGS.md:26`).

### F3 — ~50 user-meaningful values are env-only or hardcoded constants, outside every settings surface

Highest-signal groups (full table in explorer evidence, §8):
- **Prompts:** ask system prompt SoT is the Python constant `DEFAULT_ASK_SYSTEM_PROMPT`
  (`app/settings/models.py:285-296`); the compiler key is registered but no `vault/@Settings/agents/ask.md`
  exists; `docs/settings/prompts/*.v1.md` are self-declared descriptive mirrors. The loader
  (`app/components/settings/prompts_loader.py:53-103`) is **not** dead — `app/settings/validate.py:238`
  calls it inside `validate_settings()`, which is wired to the live `GET /api/settings/validate`
  route (`app/api/routes/settings_validate.py`) and CI. But that call path only validates the
  registry/mirror files' shape; the answer path (`app/agents/ask/utils.py`) never reads them — so
  the mirror-vs-source gap is real (the files are validated, never consulted at answer time), even
  though the loader itself is live code, not dead code.
- **Models/voices:** `REASONING_MODEL`/`MERGE_LLM_MODEL` env defaults `llama3.1:8b`
  (`app/reasoning/provider.py:101`, `app/components/llm/router.py:76`); all TTS voices/toggles env-only
  (`app/tts/config.py:39-73`), no pydantic settings class at all.
- **Ranking/thresholds:** entire rerank surface env-only (`app/retrieval/rerank/provider.py:58,122-126,188`);
  curation/expansion floors are module constants — and are read from the **constant, not the instance
  field** (`app/curation/contradiction.py:108,336`; `app/expansion/connect.py:112,212`), so even a
  future wiring of the field would be ignored.
- **Inconsistent duplicated defaults:** `LLM_TIMEOUT` defaults 12/60/120 across call sites
  (`app/services/llm.py:376`, `app/llm/adapter.py:56,74,88`); `WATCHER_ENABLE` defaults `"0"` vs `"1"`
  in two implementations (`app/watcher/config.py:147` vs `app/watcher/registry.py:472`).
- **Watcher performance tunables:** all env-only, absent from `@Settings/watchers.md`
  (`app/watcher/config.py:170-204`).

### F4 — Split truth about "which vault", and vault selection does not rebind settings consumers

`runtime/settings/instance.yaml` carries `vault.name`/`vault.purpose` display metadata independent
of actual selection; nothing reconciles it with `AppLocalSettingsStore.last_active_vault_ref` and
the live `VaultManager` context. `WATCHER_VAULT_PATH` is read once at watcher boot and never
rebinds on UI vault selection — a capture can succeed while invisible to ingest (named gap,
`docs/ENVIRONMENTS.md:94-108`). #3119 (which named this gap) closed 2026-07-07 via PR #3126, but
that fix only adds a visible `ingest_binding` warning surface (`diverged`/`unbound`/`unknown`) —
it does not rebind. The live rebind was deliberately deferred: #2476 ("document the split, do not
converge") ruled that the watcher's independence from the HTTP process's `VaultManager` singleton
should be preserved, not converged, and #3119's resolution and `docs/ENVIRONMENTS.md:94-108`
explicitly point full live propagation at the future #2143 epic rather than building it now.
**Owner ruling (2026-07-07, this audit) reverses that posture**: the watcher must be flexible
about what it watches, with no value in a watcher bound to the wrong vault, and the design should
support redirecting a running watcher rather than only detecting divergence. SETTINGS-05
implements this and explicitly supersedes #2476's verdict.

### F5 — Receipts are inconsistent across writers

Only `SettingsService.update_setting` emits a durable `SettingsWriteReceipt` (dual JSONL+DB outbox,
`settings_service.py:66-119`). The compiler's auto-heal **writes into vault markdown** with only an
in-process bus event (`compiler.py:440-443`); Heimdal note writes and app-local writes emit no
receipt. Given the product's moat is write-gating + receipts, a machine mutation of a
human-editable settings file without a durable receipt is a posture violation.

### F6 — Two `system-settings.schema.json`, one orphaned and diverged

`schemas/system-settings.schema.json` is the wired one (`app/services/settings.py:12`, `SCHEMA_PATH`).
`docs/schema/system-settings.schema.json` has zero code references, a looser shape, and a
different field name (`active_edit_grace_s` vs the canonical `inactive_grace_s`,
`app/services/settings.py:58`).

### F7 — No single settings owner doc; docs contradict on authority direction

`docs/DOCS_INDEX.md`'s `docs/SETTINGS.md` row ("with known debt, forward-looking areas") and its
`docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md` row own two disjoint halves (row anchors by path —
line numbers in that index shift with every added row, including this audit's own);
`vault-settings-roadmap.md` records the central service as simultaneously delivered-foundation
and unmet-DoD (`:110-123` vs `:42-57`).

### What is healthy (keep)

- **Pre-vault behavior is sound**: no-vault boot returns typed defaults, never raises, never falls
  back to `./vault` (`health_settings.py:143-168`, `watcher_settings.py:31-60`; tests
  `tests/settings/test_*_no_vault.py`). The app-local store (`app/vault/app_local.py`) is exactly
  the right shape: md+frontmatter on host filesystem, XDG/AppSupport resolution, corruption
  backup+reset (`:177-196`).
- **Stack B's write path** is the model to generalize: scoped precedence, WriteGuard-gated
  runtime-gating keys, actor-tagged durable receipts, UI as transport-of-intent
  (`tests/companion_ui/test_runtime_control_settings_authority.py`).
- **Heimdal's per-field human/agent authority split** (`settings_notes.py:109-163,653-681`) is the
  best authority pattern in the codebase — an agent can never silently clobber a human field.

## 3. Research-question resolutions

- **RQ1 (actual vs documented SoT):** §1 table. Documented SoT ("vault markdown") holds for stack B
  and Heimdal; is false at runtime for stack C (F1); stacks A/D are undocumented-as-settings.
- **RQ2 (mirror-vs-source gaps):** Confirmed. `docs/settings/prompts/*` are mirrors, validated but
  never consulted at answer time (F3). Same pattern: `docs/schema/system-settings.schema.json` (F6)
  and `runtime/settings/*.yaml` in an uncompiled container (F1) — three surfaces that look
  authoritative and are not.
- **RQ3 (documented design vs implementation):** Design exists across three docs with three
  locations (F2); the ingestion promise is implemented but unwired (F1); the "settings tiering"
  operator/lab profile exists (`app/settings/tiering.py:8-10`) but most tunables never reach any
  tier because they never reach a settings surface (F3).
- **RQ4 (pre-vault sequencing):** A designed and shipped split exists — app-local instance scope
  (identity, vault registry, last-active) vs vault scopes (shared/local), precedence
  built-in → app-local → vault-shared → vault-local → runtime
  (`VAULT_AND_SETTINGS_CONTEXT.md:80-104`). Gaps: env vars act as de-facto pre-vault settings
  outside this model (D); instance.yaml duplicates vault identity (F4). R5 (#2312) is **not**
  open — it closed 2026-06-24 with Option A shipped and documented
  (`docs/ENVIRONMENTS.md:56`, "Scaffolding placement decision"): scaffold only on explicit
  `initialize`, never on `select`/open. The target design in §5 conforms to this existing
  decision rather than proposing a new one.
- **RQ5 (prior decisions status):** Persistence-≠-read-only (#2590/#2629) partially enacted —
  stack B writable+receipted, but most md surfaces still read-only (§2 read-only list in explorer
  evidence). Storage-substrate framework conformed to by app-local/vault split. ADR-0056/Mimer
  contract excludes settings writes for app agents; Bifrost writes `_heimdal/**` against an
  unpublished in-process schema (named drift risk F7 in that contract).

## 4. Invariants (extend `docs/testing/invariant-tests.md`; do not fork)

Minimal kernel = SET-1 + SET-2 + SET-3; the rest is defense in depth.

- **SET-1 `settings_take_effect_or_fail_loud` (MUST)** — a vault-authored setting either takes
  effect in the running service within bounded staleness or the service surfaces that it is running
  on defaults. Never a silent code-default substitution. *Violated today* (F1).
- **SET-2 `one_vault_settings_location` (GATE)** — exactly one canonical vault settings root; CI
  blocks introduction of a new settings path. *Violated today* (F2).
- **SET-3 `every_settings_write_receipted` (MUST)** — any writer mutating a settings file (API,
  watcher delta, compiler auto-heal, agent) emits a durable actor-tagged receipt. *Partially
  enforced* (stack B only, F5).
- **SET-4 `single_default_registry` (GATE)** — a behavior-shaping default is declared once; no
  duplicated env-default literals at call sites. *Violated today* (F3 timeout/enable divergences).
- **SET-5 `no_vault_boot_reads_instance_scope_only` (MUST)** — pre-vault boot consumes only
  instance-scope settings; vault-scope reads in `no_vault` return typed defaults. *Exists — keep*
  (`tests/settings/test_health_settings_no_vault.py`, `test_watcher_settings_no_vault.py`).
- **SET-6 `mirrors_declare_and_check_drift` (DOCTOR)** — any descriptive mirror of a runtime value
  either is deleted, becomes the source, or is generated as a projection; a reconciliation check
  detects divergence. *Violated today* (F3, F6).
- **SET-7 `vault_selection_rebinds_consumers` (MUST)** — vault selection/switch rebinds every
  vault-scoped settings consumer (watcher included). *Violated today* (F4). This invariant
  supersedes the deliberate "do not converge" posture of #2476 per the owner's 2026-07-07 ruling.

## 5. Target design (proposal — advisory until owner ruling)

**Two scopes, one spine, watcher-fed ingestion.**

1. **Two scopes only.**
   - **Instance settings** (pre-vault, per install): the existing app-local md store grows into the
     single instance surface — identity, known vaults, last-active, machine role, host paths,
     TTS engine/host bindings. Env vars shrink to an enumerated deploy-time bootstrap set
     (channel, DB DSN, ports, container topology) — bootstrap gets the process to the point where
     md can be read, and nothing more.
   - **Vault settings** (everything user-meaningful about behavior): **one** canonical, visible,
     human-named folder — `<vault>/settings/` (conforms to the documented scaffold and the
     human-first-naming stance; not hidden under `_system/`, not sigil-named `@Settings`).
     Absorbs stacks A and C sources and `health.md`. Format stays md with per-section declared
     authority (human / agent / mixed), adopting Heimdal's per-field authority split as the
     general pattern. `_heimdal/**` stays where it is (contracted Bifrost surface; publishing its
     schema is already F7 of the Mimer client contract) but conforms to the same invariants.
2. **One spine.** Stacks A/B/C merge into `SettingsService`: one resolution order
   (single default registry → instance md → vault-shared md → vault-local md → runtime override),
   one write path (WriteGuard-gated where authority-bearing), one receipt stream, one
   `settings explain` that names the origin of every effective key. The compile-to-YAML
   intermediate and the dead prompt loader are deleted; pydantic models remain as the validation
   layer, not a parallel truth.
3. **Ingestion.** The watcher already polls and already routes `local.md` deltas
   (`app/watcher/settings_delta.py:26-102`); extend that to the whole settings folder →
   validate → apply → durable receipt → hot-reload event. Edit in Obsidian, takes effect, leaves
   a receipt. Fail-loud on invalid: degrade to last-valid with a visible health signal, never
   silent defaults (SET-1).
4. **Sequencing (boot → vault).** env bootstrap → instance md → `no_vault` idle (unchanged,
   #2005) → vault selected → vault settings load + **rebind subscribers via `VaultChangedEvent`**,
   watcher included (owner-ruled 2026-07-07, superseding #2476's "do not converge" and #3119's
   visible-signal-only fix) → watcher ingests subsequent edits. Settings that exist
   pre-vault stay instance-scoped; nothing vault-scoped is needed to boot (SET-5 already
   guarantees this). Vault init scaffolds `settings/` per the already-shipped R5/#2312 decision
   (Option A, `docs/ENVIRONMENTS.md:56`) — explicit init only, never on open; no new ruling needed.
5. **De-hardcoding.** Migrate the F3 inventory into the registry incrementally, operator/lab
   tier-gated, highest user-meaning first: prompts (md in `settings/prompts/` becomes the SoT,
   code constant becomes the seeded default), model/voice routing, rerank/thresholds, watcher
   tunables. Delete `docs/settings/prompts/*` mirrors or regenerate them as marked projections.
6. **Governance.** One owner doc: rewrite `docs/SETTINGS.md` as the settings owner (current +
   target clearly separated); `VAULT_AND_SETTINGS_CONTEXT.md` stays the concept contract;
   delete `docs/schema/system-settings.schema.json`.

## 6. Dependency-ordered backlog (reconcile, don't duplicate)

| # | Task | Verify | Reconciliation |
|---|---|---|---|
| S1 | Wire ingestion: services load vault settings at startup + watcher-fed reload; kill silent-default (SET-1) | integrated-runtime UAT: edit `settings/` md → running service reflects it without restart; degraded state visible in `/api/health` | Repairs F1; extends `vault-settings-roadmap.md :: external edits` item |
| S2 | Canonicalize one settings location; migrate A/C/health sources; compat-read old paths one release with loud deprecation (SET-2) | CI gate test `tests/architecture/test_settings_single_location.py`; grep gate on new paths | Resolves F2 doc contradiction across SETTINGS/ENVIRONMENTS/VAULT_AND_SETTINGS_CONTEXT |
| S3 | Unify receipts: compiler/auto-heal, watcher delta, agent writes all emit `SettingsWriteReceipt` (SET-3) | `tests/vault/test_settings_receipt_durable.py` extended to every writer | Extends #2475 UI-boundary receipt work |
| S4 | Single default registry; collapse duplicated env defaults (SET-4) | one declaration site per key; divergence test | New; fixes LLM_TIMEOUT/WATCHER_ENABLE splits |
| S5 | Vault-selection rebind for watcher + all vault-scoped consumers (SET-7) | test: select vault via API → watcher ingest binding follows | Supersedes #2476's "do not converge" verdict per owner ruling; #3119 already closed with a partial visible-signal fix (PR #3126), superseded here with a real rebind. Not a duplicate of #2143 (that epic is about serving multiple vaults concurrently; this is one watcher following one active selection). |
| S6 | Prompts-as-settings: `settings/prompts/*.md` become runtime SoT; migrate the validation loader's target to the canonical location, then retire loader + mirrors once genuinely unreferenced (the loader is live code — see F3) (SET-6) | ask prompt edited in vault md changes `/api/ask` behavior; drift check for remaining mirrors | Enacts prompt-contract-mirror memory; supersedes `docs/settings/prompts/` |
| S7 | De-hardcode wave 1 (models/voices/rerank/thresholds/watcher tunables), tier-gated | each migrated key visible in `settings explain` with origin | Extends `vault-settings-roadmap.md :: extract configurable hardcoded values`; TTS voice decision (#1702) becomes a setting |
| S8 | Owner-doc consolidation + schema cleanup (F6, F7) | DOCS_INDEX single owner row; orphan schema deleted | docs-authoring lane |

S1 and S2 are ordered first because everything else lands on the spine they define. Handoff to
`feature-breakdown` after the owner rules on §5 (a spec directory before the ruling would encode
an undecided design).

## 7. SBS reconciliation (binding)

- Settings-as-md-in-vault **conforms** to HKA (vault filesystem as human-legible substrate) and to
  the storage-substrate framework (human-editable, long-lived → notes).
- WriteGuard-gated authority-bearing settings writes with receipts **conform** to GOV /
  GovernedWriteProtocol (ADR-0019 direction); non-gating keys as mechanical writes conform.
- One resolution spine with instance/vault scopes **conforms** to WSP (ActiveContextSet — settings
  resolution is scope-bound, not a scalar global).
- Watcher-fed ingestion **conforms** to the existing ingest/derived posture: `runtime` effective
  state is a rebuildable projection of md sources (DRI-classified), never the only copy of meaning.
- **No reshape proposed.** Consolidating four stacks into one service is implementation
  convergence inside existing boundaries, not a boundary change.
- **Residual boundary question (flagged, not resolved here).** `docs/SYSTEM_BREAKDOWN_STRUCTURE.md`
  assigns "which vault is bound" and device/context posture to WSP's `ActiveContextSet` as a
  governed set of bindings — explicitly replacing a free-standing `activeVault` scalar — and
  treats a vault re-point as a GOV-governed decision when authority-bearing. Folding
  `lastActiveVaultRef`/machine-role into the generic instance-settings surface (§5 point 1) must
  not silently regress that into an ordinary WriteGuard-gated settings-field write; the
  implementation should keep the WSP-governed re-point path distinct even where it is stored
  alongside instance settings. Similarly, the compiler's auto-heal writing back into vault
  markdown (a DRI-classified derived layer mutating HKA-owned source content, F5) is folded into
  "one write path, gated where authority-bearing" without an explicit ruling on whether
  derived-writes-into-source should continue under the merged spine — implementers should treat
  this as an open sub-question for SETTINGS-04/SETTINGS-08, not an already-settled convergence
  detail.

## 8. Evidence provenance

Five parallel read-only explorer passes (runtime code, documented design, pre-vault sequencing,
hardcoded sweep, constituents) against `origin/main` 8d871f9c on 2026-07-07. Full anchored
evidence retained in the audit session; every claim above carries its inherited anchor.
