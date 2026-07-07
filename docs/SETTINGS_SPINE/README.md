State: Specification directory for the Settings Spine capability (owner-ruled Option B, 2026-07-07). Executable form of `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md` §5-§6 (audit PR #3153). Parent feature issue FILED: #3156 (validation hub); children #3159-#3166 (see `PARENT_FEATURE_ISSUE.md` for the live map).
Doc role: Specification (system-level source of truth for what needs to be built)
Authority: Owns the task decomposition, acceptance criteria, and cross-task invariants for the settings-architecture consolidation. Subordinate to owner docs for shipped behavior; the audit remains advisory evidence. Where a task here conflicts with a Product owner doc, the owner doc wins and the conflict is raised as an issue.

# Settings Spine

One settings model for all of Yggdrasil: **two scopes** (instance settings in an app-local
markdown file that exists before any vault; vault settings as human-editable markdown at one
canonical, visible `<vault>/settings/` folder) resolved through **one spine** (a single
`SettingsService` resolution order with a single default registry), with **watcher-fed ingestion**
(edit markdown → validated → applied live → durable receipt; invalid input degrades loudly to
last-valid, never silently to code defaults).

Why: the audit found five coexisting settings substrates, an md→runtime pipeline no running
service ever invokes (vault-authored settings silently replaced by code defaults), four competing
vault settings locations, ~50 user-meaningful hardcoded values, and receipts on only one of four
writers. Findings F1-F7 and invariants SET-1..SET-7:
`docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md`.

## Implementation tasks (execution order)

| # | Task file | Delivers | Invariant | Depends on |
|---|---|---|---|---|
| 1 | [WIRE_SETTINGS_INGESTION.md](WIRE_SETTINGS_INGESTION.md) | Vault-authored settings take effect in running services; watcher-fed reload; loud degradation | SET-1 | — |
| 2 | [SINGLE_DEFAULT_REGISTRY.md](SINGLE_DEFAULT_REGISTRY.md) | Every behavior-shaping default declared once; duplicated env-default literals collapsed | SET-4 | — (parallel with 1) |
| 3 | [CANONICALIZE_SETTINGS_LOCATION.md](CANONICALIZE_SETTINGS_LOCATION.md) | One vault settings root `<vault>/settings/`; legacy paths compat-read with loud deprecation | SET-2 | 1 |
| 4 | [RECEIPT_EVERY_SETTINGS_WRITE.md](RECEIPT_EVERY_SETTINGS_WRITE.md) | Every settings writer (API, watcher delta, auto-heal, agent) emits a durable actor-tagged receipt | SET-3 | 1 |
| 5 | [REBIND_ON_VAULT_SELECTION.md](REBIND_ON_VAULT_SELECTION.md) | Vault selection rebinds every vault-scoped settings consumer, watcher included | SET-7 | 1 |
| 6 | [PROMPTS_AS_SETTINGS.md](PROMPTS_AS_SETTINGS.md) | `settings/prompts/*.md` become the runtime prompt SoT; validation loader migrated, stale mirrors retired once superseded | SET-6 | 3 |
| 7 | [DEHARDCODE_WAVE_ONE.md](DEHARDCODE_WAVE_ONE.md) | Highest-value hardcoded values (models/voices/rerank/thresholds/watcher tunables) migrate into the registry, tier-gated | SET-4/SET-1 | 2, 3 |
| 8 | [CONSOLIDATE_SETTINGS_OWNER_DOCS.md](CONSOLIDATE_SETTINGS_OWNER_DOCS.md) | One settings owner doc; orphan schema deleted; location wording reconciled; parent-closure handoff | SET-6 | 1-7 (all — its closure handoff verifies the full capability checklist) |

Tasks 1 and 2 can run in parallel (disjoint surfaces: ingestion wiring vs default declarations).
Everything else lands on the spine they define.

## Capability acceptance criteria

- [ ] A setting edited as vault markdown takes effect in every consuming service without a manual
      CLI step or restart, or the service visibly reports degraded-settings state.
      Verify: `tests/settings/test_ingestion_startup.py` (task 1) + integrated-runtime UAT receipt on the parent issue.
- [ ] Exactly one canonical vault settings location exists; a CI gate blocks new locations.
      Verify: `tests/architecture/test_settings_single_location.py` (task 3).
- [ ] Every mutation of a settings file, by any writer, has a durable actor-tagged receipt.
      Verify: `tests/vault/test_settings_receipt_durable.py` extended per task 4.
- [ ] Pre-vault boot consumes only instance-scope settings; `no_vault` behavior unchanged (#2005).
      Verify: `tests/settings/test_health_settings_no_vault.py`, `tests/settings/test_watcher_settings_no_vault.py` stay green through every task.
- [ ] Vault selection through the UI rebinds the watcher ingest path (the real rebind #3119's
      closing fix deliberately deferred; supersedes #2476's "do not converge" per owner ruling).
      Verify: `tests/watcher/test_ingest_binding_follows_selection.py` (task 5).
- [ ] `settings explain` names the origin (registry default / instance / vault-shared / vault-local
      / runtime override) of every effective key migrated in tasks 6-7.
      Verify: `tests/cli/test_settings_explain_cli.py` extended per tasks 6-7.
- [ ] One owner doc owns settings; no doc names a retired location as canonical.
      Verify: doc writeback at `docs/SETTINGS.md :: Authority` + `docs/DOCS_INDEX.md` row (task 8).

## Cross-Task Invariants / Interaction Safety

Tasks 1, 3, 4, 5 and 7 all touch the settings read/write path. The seams:

- **No dual truth during migration (tasks 1↔3).** While legacy locations are compat-read, a key
  present in both a legacy and the canonical location must resolve from the canonical one and log
  the shadowed legacy value loudly — never merge, never resolve differently per consumer. If task 3
  lands while task 1's reload loop is live, the reload must pick up the location change atomically
  (one bundle swap, not per-file).
- **A write is terminal only with its receipt (tasks 3↔4).** Migration writes performed by task 3
  (moving files into `<vault>/settings/`) are settings writes: if task 4 has landed they must be
  receipted; if task 4 has not landed, task 3 records the migration in its PR receipt and task 4's
  backfill scope explicitly includes migration-era writes. A migrated file with no receipt anywhere
  is a defect, not an acceptable interim state.
- **Rebind implies reload (tasks 1↔5).** Vault selection rebinding (task 5) must trigger the same
  reload path task 1 builds — not a second loader. If task 5 merges first, its rebind may
  temporarily rebind only the per-request readers (stack B) and must state in its PR that bundle
  consumers rebind when task 1 lands; the parent issue tracks that residue.
- **Prompt SoT moves exactly once (tasks 3→6).** Task 6 places prompt files only under the
  canonical location. If task 6 were cut before task 3 merges, it would move the prompt SoT twice;
  the dependency is therefore hard, not advisory.
- **Fail-loud beats availability for settings (all tasks).** On any partial failure (unreadable
  file, invalid schema, mid-migration state), the resolved posture is last-valid + visible degraded
  state. No task may introduce a silent fallback to code defaults — that is the F1 failure mode
  this capability exists to remove.
- **No-vault boot is a standing regression gate (all tasks).** Every task's validation includes
  the no-vault tests; a task that makes boot require a vault is rejected regardless of its other
  merits (#2005).

## Verification path

Per-task `Verify:` targets are named inline in each task file (behavioral ACs name tests;
enforcement ACs assert the production call site; non-behavioral ACs name doc/receipt targets).
Shared/hot-path tasks (1, 3, 5, 7) run the full `not pg` suite plus
`RUN_INTEGRATED_RUNTIME_UAT=1` where the task touches the vault/watcher hot path.

## Validation / acceptance path

The parent feature issue is the live validation hub: each merged child posts a validation receipt
there before the next dependent child is picked up. Capability acceptance = all checklist items
above verified + one integrated-runtime receipt (edit a setting in Obsidian on the dev channel,
observe live effect + receipt). Owner-doc promotion (task 8 rewrites `docs/SETTINGS.md` as the
single owner) is the final child and carries the parent-closure handoff.

## Relationship to GitHub issues

Parent feature issue #3156; children #3159 (01), #3160 (02), #3161 (03), #3162 (04), #3163 (05),
#3164 (06), #3165 (07), #3166 (08) — live map and lifecycle rules in `PARENT_FEATURE_ISSUE.md`.
Reconciliation (do not duplicate): task 5 builds the live rebind that #3119's closing fix
(PR #3126, visible-warning only) deliberately deferred, superseding #2476's "do not converge"
verdict per the owner's 2026-07-07 ruling — it closes no open issue, both are already closed;
the R5 scaffolding question is already resolved and shipped (#2312 closed 2026-06-24, Option A at
`docs/ENVIRONMENTS.md :: Scaffolding placement decision`) — task 3 conforms to it;
`docs/implementation/vault-settings-roadmap.md` items "external Obsidian edits", "extract
configurable hardcoded values", and "central service" are superseded by tasks 1, 7, and the spine
respectively — task 8 marks them so.

## Follow-up capability flagged, not in this spec

While ruling on SETTINGS-05 (rebind on vault selection), the owner flagged a larger wanted
capability: spinning up additional, time-limited watchers on demand (not just one watcher
following one active selection). SETTINGS-05's rebind mechanism (subscribe to
`VaultChangedEvent`, re-resolve, resume) is the reusable building block a future multi-watcher
task would instantiate per watcher, but running more than one watcher concurrently is a distinct
capability (watcher lifecycle management: spin up, tear down, scope, resource limits) and is
explicitly out of scope here. Worth its own bounded issue once SETTINGS-05 ships and the
single-watcher-follows-selection mechanism is proven.

## Related docs

- `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md` — evidence and design rationale (advisory)
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md` — concept contract (scopes, VaultStatus, precedence)
- `docs/CONCEPTS/CONFIG_AS_PRODUCT_CONTRACT.md` — config-as-product principle
- `docs/testing/invariant-tests.md` — SET-1..SET-7 registration target (task-level)
- `docs/SETTINGS.md` — owner doc, rewritten by task 8
