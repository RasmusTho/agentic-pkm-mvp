# Environments

State: SoT v5.5 baseline with explicit `dev` / `test` / `prod` environment model, control surfaces, and artifact separation (Issues #263, #266), with the local `test` environment documented as the canonical bootstrap and verification posture. Channel-level identity, per-channel DB isolation, promotion, and rollback are specified by the v6.0 release-channels capability at `docs/RELEASE_CHANNELS/README.md`; this document continues to own environment selection and path scoping only.
Doc role: Core SoT
Authority: Canonical environment contract for the current baseline and forward-line work; defines what `dev`, `test`, and `prod` mean, what must remain invariant, and what may vary. Architecture, operations, testing, status, and component docs should reference this document instead of restating environment policy. Release-channel semantics (channel identity, DB-per-channel, promotion, rollback) are owned by `docs/RELEASE_CHANNELS/README.md`.
Temporal class: operational
Review cadence: as environment/channel posture changes
Last reviewed: 2026-06-16
Last verified against: docs/RELEASE_CHANNELS/README.md, docs/STATUS.md (§Cognitive Expansion — activation status), ops/promotions/2026-06-13-cc3ce65d.md

## Overview

This document defines the active environment model for the repo, specifies the control surfaces for runtime environment selection and artifact path scoping, and documents the cross-environment invariants that must hold.

The purpose of this document is to make environment boundaries explicit and ensure that supported environments maintain clear vault, store, and runtime boundaries when isolation is required.

Reading rule:
- Use this document when a change touches environment-specific behavior, storage boundaries, runtime topology, write safety, rollout posture, or local bootstrap expectations.
- Use `docs/ARCHITECTURE.md` for system structure, `docs/OPERATIONS.md` for operator procedure, `docs/TESTING.md` for verification layers, and `docs/STATUS.md` for current rollout posture.

## Vault terminology

"Vault" is overloaded. The word names four distinct things in this system, each carrying its own invariants. Pinning them keeps statements like "no vault at initiation" unambiguous and prevents work from relaxing the wrong invariant (for example, accidentally making the *test* vault optional and breaking deterministic UAT). This section is the canonical definition; other docs should reference it instead of redefining "vault" locally. It pins the term per `docs/VAULT_OPTIONAL_RUNTIME/PIN_VAULT_DEFINITION.md`.

The four senses:

- **Content vault** — the directory of Markdown notes the user authors and owns (the Obsidian-style sense: the folder a human opens).
  - *Invariants*: this is the human-first surface; writes to its tracked notes remain deterministic and guarded by write-safety and idempotency rules (see §Cross-Environment Invariants). `prod` operates on the operator's real content vault; `dev` and `test` use intentionally separate non-production content vaults (see §Vaults and Human-Facing Files). The continuity set that recovery must preserve is the content vault's notes plus their companion notes.

- **Vault-settings** — the per-vault settings/config surface that lives *inside* a content vault (resolved relative to the vault root, e.g. `<vault>/_system/settings/` or `<vault>/@Settings/`; see `app/config/paths.py` and `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`).
  - *Invariants*: settings and policy remain the control surface for runtime behavior; environment selection must not bypass policy, allowlists, or write guards. Vault-settings are scoped to a specific content vault, not global, and a content vault whose required settings are corrupt or missing is `invalid`/`uninitialized` rather than usable. Their presence/validity is what distinguishes a *selected and initialized* vault from a merely existing folder.

- **`VAULT_ROOT` runtime binding** — the env/runtime binding that points the running process at a content vault at boot (resolved by `resolve_vault_root` / `resolve_optional_vault_root` in `app/config/paths.py`).
  - *Invariants*: this binding is the boot-time *pointer*, not the data. **Neither resolver silently falls back to a CWD-relative `./vault` anymore** — the `_DEFAULT_VAULT` (`./vault`) fallback that caused the `provenance="fallback"` "notes won't render" footgun (#2476) is gone. The two resolvers differ only in **how they signal the no-vault state** on an **unset/unbound** `VAULT_ROOT`: `resolve_optional_vault_root()` returns `None` (an explicit no-vault state) — this is the resolver the no-vault-at-initiation path uses; `resolve_vault_root()` instead **raises `VaultRootNotBoundError`** (it requires a bound vault, so callers that cannot tolerate no-vault fail loud rather than guessing `./vault`). Both resolvers agree on the other cases: a **set-but-missing** `VAULT_ROOT` (path configured but absent) fails loud with `VaultRootMisconfiguredError` — missing data is an error, not a no-vault state — and a **bound, existing** root resolves to that path, environment-scoped when requested. Per-environment overrides (`VAULT_ROOT_DEV`, `VAULT_ROOT_TEST`) and a CLI override take precedence over the base binding.

- **Test vault** — the vault the local `test` bootstrap/UAT harness binds (set via `VAULT_ROOT_TEST` / `TEST_VAULT_ROOT`, else the repo-local `vault-test` scratch fallback; plain `VAULT_ROOT` is a runtime binding and is not used to select the test seed vault; see §Canonical Local Test Bootstrap).
  - *Invariants*: it is resettable and reproducible, not persistent — the `test` bootstrap resets and re-initializes it from a clean start, and repeatability matters more than durability. It must remain isolated from the `dev` and `prod` content vaults so deterministic UAT does not depend on live or leftover state. Making the *test* vault optional or non-deterministic would break the canonical verification path and is out of scope for any "vault optional" work.

**Which sense "no vault at initiation" refers to.** "No vault at initiation" refers specifically to the **`VAULT_ROOT` runtime-binding** sense: the process boots with `VAULT_ROOT` (and any env-scoped variant) **unset/unbound**, so `resolve_optional_vault_root` reports the explicit no-vault state. It does **not** mean the content vault was deleted, the vault-settings are absent, or the test vault is skipped:

- A **set-but-missing** content vault is a misconfiguration that fails loud (`VaultRootMisconfiguredError`), not a no-vault state.
- Vault-settings and the test vault are unaffected by the no-vault-at-initiation contract; only the runtime binding may legitimately be absent at boot.

<a id="vault-init"></a>

### Vault initialization and the personal-vault-write constraint

**Vault initialization** is the act of writing the Design Handoff settings scaffold (`settings/vault.md`, `settings/local.md`, and companion files) into a folder so it becomes a fully *selected* (initialized) vault. Once initialized, the vault context resolves to `selected` and both reads and writes are enabled.

**Two distinct flows from the picker** must be distinguished:

1. **"Open existing vault"** — the human selects a pre-existing folder via `POST /api/companion/vault/select`. This is a *read-only selection*: the manager validates the folder and sets the in-process context (`selected` if already initialized, `uninitialized` if the folder exists but has no Design Handoff settings). **No scaffolding is written**, and an `uninitialized` folder — the personal-vault / not-yet-adopted case — is left entirely untouched: `validate_vault` returns before any write. (An *already-initialized* vault may have an absent `vaultId`/`localInstanceId` back-filled into its existing `settings/` during validation; that is identifier repair on a vault we already own — never new scaffolding, and never a write into an unadopted folder.) This preserves the contract: reads work on any existing folder (`uninitialized` is readable via `_READABLE_SELECTED_STATUSES`), but the human's personal vault files are never modified without an explicit, understood gesture.

2. **"Initialize new vault"** — the human explicitly chooses to create/init a folder via `POST /api/companion/vault/initialize`. This writes the Design Handoff settings scaffold into the chosen folder and then selects it. The choice is explicit and visible: the UI exposes the init form as a separate affordance (`data-intent="vault.initialize"`) distinct from the open/select affordance.

**Scaffolding placement decision (Option A, resolved #2312).** The settings scaffold is written *inside the vault folder* (`<vault>/settings/`), not in an app-local sidecar. Rationale: the Design Handoff settings are the vault's *identity manifest* — intended to be visible to the human, committable alongside vault notes, and shareable across machines via Git. They are not hidden system state. Writing them into the vault folder is the expected, correct behavior for a folder the human is deliberately initializing *as* a vault. Option B (app-local sidecar, vault folder untouched) was considered but rejected because it would decouple vault identity from the vault itself, breaking the committability/shareability requirement and creating split-brain risk if the sidecar is lost. Option C (hidden `.system/` dir) was considered but rejected: a hidden dir still writes into the human's folder and adds discovery friction without removing the write.

**Hard constraint preserved across both flows.** The hard constraint — "must not write into a human's personal vault without an explicit, understood choice" — is satisfied by flow separation, not by hiding files. The `select` endpoint writes no scaffolding and never writes into an `uninitialized` (unadopted) folder — at most it back-fills a missing identifier into an *already-initialized* vault's existing `settings/`; only the `initialize` endpoint writes the settings scaffold, and it is reached only through a deliberate human gesture ("Initialize"). The init form still lives in the vault-settings panel (`vault_settings_panel.py :: _action_forms`), which exposes it as `data-affordance-status="available"` only when the current status is `none`, `missing`, or `uninitialized`, making the affordance boundary visible. As of the recomposed no-vault front door (#2564, part of #2561), the **"Choose a vault" overlay no longer folds that init form (or any typed path field / machine-Role select) into the front door** — selection there is always a visual row click. The deliberate "Initialize here" gesture for an unadopted folder folds into the filesystem-browse confirm (Ask 3b / #2565); the typed-path init form is reached only through the vault-settings drawer (loaded-vault context), never the cold front-door picker.

**Non-empty target requires explicit confirmation (#2518).** "Deliberate" is hardened into "informed" when the chosen folder is **already populated**. An existing personal Obsidian vault (notes present, no `settings/`) resolves to `uninitialized`, so the picker offers Initialize for it too; initializing would add the scaffold *into the human's existing folder*. So `POST /api/companion/vault/initialize` refuses a non-empty target with **`409 vault_init_confirmation_required`** (and writes nothing) unless the request carries `confirm: true`. "Non-empty" means the folder holds any top-level entry other than ignorable OS noise (`.DS_Store`) — a brand-new/missing or empty folder initializes friction-free (preserves #2312 AC1). A `settings/` directory is **counted**, not assumed to be the Design Handoff scaffold: a human's own `settings/` folder must not be silently written into (so a `settings/`-only folder still requires confirm, and a fully-initialized vault avoids the gate by being `selected` rather than `uninitialized`). The Companion UI surfaces this as an **in-band confirm gesture** on the init form ("This folder already contains N item(s)…", then a "Confirm initialize" control that re-submits with `confirm: true`). This is a **single-actor, in-band proportional guard** — the human confirms their own write at the moment of an under-informed click — not a governance/agent approval loop (consistent with the UI control-action boundary, #2475). The guard sits at the picker-facing API boundary; manager-direct callers (`app/cli/vault.py`, `app/ops/test_channel_bootstrap.py`) are deliberate operator/automation actions and are not gated. `initialize_vault` itself stays idempotent (`write_missing` never overwrites), so a confirmed init into a populated folder adds `settings/` without touching existing notes.

**Read before write posture.** An `uninitialized` vault (existing folder with no Design Handoff settings) is readable but not writable. The `_active_companion_vault_root` gate uses `_READABLE_SELECTED_STATUSES = {"selected", "uninitialized"}` for read boundaries, so a human can browse notes before committing to initialization. Write boundaries pass `require_initialized=True`, which raises `VaultUninitializedError` and routes the write to the picker with reason `"uninitialized"` so the UI can surface the init affordance. This is the correct no-surprise behavior: reads always work on a selected folder; only writes require initialization.

<a id="nested-vault-boundary"></a>

### Nested vault boundary (a vault may contain privately-initiated sub-vaults)

With full-host filesystem access and in-process selection, a content vault may contain **other initialized vaults as subfolders** — a parent vault whose subtree includes child folders that are themselves vaults (their own `settings/vault.md`, possibly private). The boundary rule below keeps a parent's read surfaces from leaking a child vault's notes (#2313).

- **Vault-root marker.** A folder is a **vault root** iff `(<folder>/settings/vault.md)` exists — the same marker `validate_vault` keys on, building directly on the Option A scaffolding placement above. `app.vault.manager.is_vault_root(path)` is the cheap check: a single `stat`, no schema read, no healing.
- **Boundary rule.** Enumeration of a parent vault **stops at any nested vault root strictly below it**. The selected root is the floor and is never pruned; only deeper marked roots are boundaries. A pruned child subtree is treated as if it does not exist.
- **Child privacy (primary invariant).** A private child vault's contents must **never** surface through a parent vault's read surfaces. The parent acts as if the child subtree does not exist — this is a confidentiality boundary.
- **Owning-vault identity.** A note's owning vault is its **nearest enclosing vault root**, not the selected root if a deeper marker encloses it (`app.vault.manager.nearest_enclosing_vault_root`).
- **Navigation/UX.** Nested vault roots appear as **selectable boundaries (drill-in)** in the browser (`VaultBrowserStateResponse.nested_vault_roots`), never merged into the parent's note listing.
- **Cheap on large trees.** Detection prunes **during traversal** — the companion read surfaces enumerate via `os.walk` with in-place directory pruning (`_iter_vault_note_files`), so a nested child vault's subtree is never descended into (one `stat` per directory, no per-note ancestor rescan). This replaced the prior `rglob('*.md')` scans that ignored vault boundaries.
- **Scope.** The boundary is applied across the companion read/enumeration paths (`_select_vault_notes`, `_collect_vault_note_paths`, the vault browser, the vault-link-index, `/vault/notes`, the relation/Find surface, and the recents anchor). Indexing/watcher boundary enforcement (do not ingest a child's notes under the parent identity) and multi-vault binding (#2143) are tracked separately.

### Host mount source vs in-container binding (containerized runtime)

When the runtime runs in containers, the `VAULT_ROOT` runtime binding has **two process perspectives on the same content vault**. They must not be conflated (issue #2141); both still name one content vault, neither is a separate sense of "vault":

- **Host mount source** — the path on the Docker *host* that Compose bind-mounts in as the legacy `/app/vault` compatibility mount, sourced from `${VAULT_HOST_ROOT:?…}:/app/vault` in the explicit `docker-compose.legacy-vault.yml` overlay (#2386). It is carried by `VAULT_HOST_ROOT` (exported by `scripts/start_full_system.sh` and written into the generated `tmp/runtime.env` by `scripts/export_runtime_env.sh`) and must be a path that exists *on the host*. The required-variable form errors if `VAULT_HOST_ROOT` is unset — there is no `./vault` fallback.
- **In-container binding** — the path the running process reads via `resolve_vault_root()`. It is the fixed in-container mount target `/app/vault`, supplied to the container as `VAULT_ROOT` through the service `env_file:`. It must be a path that exists *inside the container*.

Writing the host path into the container's `VAULT_ROOT` is what made `resolve_vault_root()` raise `VaultRootMisconfiguredError` and the API 503 (#2141): the host path does not exist inside the container. The no-vault idle posture omits both `VAULT_HOST_ROOT` and the generated in-container `VAULT_ROOT`. `VAULT_HOST_ROOT` is a mount-machinery surface, not a vault-selection surface — it describes *where the one bound content vault is reached from* on the host, not *which* vault is active.

### Full-host access for in-process vault selection (#2310)

After Option-2 (#2309/#2325) the human selects any vault on any disk in-process, so the container must see the host filesystem. `api` / `worker` / `watcher` additionally bind-mount the host `/Users` and `/Volumes` at **identical container paths**, so a selected host-absolute vault path (internal SSD / iCloud Obsidian under `/Users/...`, or a `/Volumes/T7` external vault) resolves transparently in-container with **no path translation**. The mounts target the parents `/Users` / `/Volumes` (never a specific volume) so the stack boots when the T7 is unplugged. Activation requires Colima to share those host directories — see [`docs/ops/COLIMA_FULL_HOST_MOUNT.md`](ops/COLIMA_FULL_HOST_MOUNT.md).

**Write guardrail.** A broader mount widens what is *selectable / readable*, not what is *writable beyond the selected vault*. Vault writes go through `write_note_from_absolute`, which enforces `resolved_path.relative_to(vault_root)` (`app/knowledge/write_ops.py`), and `app/write_guard.py` gates vault writes; a write cannot escape the selected vault regardless of mount breadth.

**Legacy `/app/vault` mount (re-baselined, #2386).** The legacy `/app/vault` mount is **no longer in the base `docker-compose.yaml`**, and the base compose no longer carries the old `${VAULT_HOST_ROOT:-${VAULT_ROOT:-./vault}}` source — a no-vault idle startup (#2005) therefore cannot synthesize a repo-local `./vault` bind. The mount is retained only as an **explicit compatibility path** in the `docker-compose.legacy-vault.yml` overlay, which `scripts/start_full_system.sh` includes **only when a vault is explicitly bound** (`VAULT_HOST_ROOT` set). Its source uses the required-variable form `${VAULT_HOST_ROOT:?…}:/app/vault`, so Compose errors rather than falling back to `./vault` if no vault is configured. This compatibility mount exists for the remaining eager `resolve_vault_root()` consumers (Slices 05A–05C of #2311) that still read `/app/vault`; once those are fully migrated it can be dropped entirely. The additive `/Users` + `/Volumes` same-path mounts (#2310) are unaffected and stay in the base compose.

## Code vs Environment Separation

Two kinds of separation govern how `dev`, `test`, and `prod` stay isolated:

**Code separation** — which process runs which code:
- Each channel runs from a dedicated checkout or worktree (see `docs/RELEASE_CHANNELS/README.md §Channel model`).
- A `prod` process runs from a `stable`-pinned checkout; a `dev` process runs from a working branch. Separate worktrees prevent code churn in one checkout from affecting a running process in another.
- Code separation is the responsibility of the operator and the promotion workflow, not the runtime itself.

**Environment separation** — which data and config each process touches:
- The runtime resolves environment-specific vault roots, DB names, and runtime-artifact paths through `PKM_ENVIRONMENT` (see §Runtime Control Surface).
- `prod`: operator-configured prod vault, `app` DB, `tmp/` artifacts.
- `dev`: operator-configured dev vault, `app_dev` DB, `tmp-dev/` artifacts.
- `test`: operator-configured test vault, `app_test` DB, `tmp-test/` artifacts.
- Vault roots are operator-configured (`VAULT_ROOT` and the per-channel `VAULT_ROOT_DEV`/`VAULT_ROOT_TEST` overrides) — each channel binds one of the operator's own Obsidian vaults; the names are operator-owned, can change at any time, and are never hardcoded. The DB names and `tmp*` artifact dirs remain the fixed per-channel separators.
- Environment separation is enforced by configuration, not by code path differences.

**The two are orthogonal.** The environment selector controls *what data is touched*; the code ref controls *what code is running*. Both must be correct for a safe prod runtime.

**Current vs future invariants.** The separation requirements in §Separation Requirements describe the current baseline. Release-channel promotion contracts (how the `stable` ref moves, how migrations apply) are owned by `docs/RELEASE_CHANNELS/README.md` and are being hardened incrementally. The current priority is establishing a sound prod baseline; full promotion-workflow automation is a later hardening step.

## Minimal Environment Model

The repo uses a lightweight but explicit environment model:

- `dev` = flexible local development environment
- `test` = isolated, resettable, reproducible verification environment
- `prod` = the active operator-facing runtime channel (the real vault), with bounded hardening still in progress

Interpretation rule:
- environment names describe operational posture, not different product semantics
- `test` is the first concrete reference environment for the current stabilization wave
- `prod` is a live channel today: a `stable`-pinned build runs against the real vault and is advanced through recorded promotion receipts under `ops/promotions/` (see `docs/RELEASE_CHANNELS/README.md §Promotion contract`). It is not a finished end-state — promotion-workflow automation and other operational details are still being hardened incrementally.
- **"Promoted to prod" is not "running in prod."** A capability whose code is on the `stable` ref is shipped to the prod *channel*, but that does not mean it is wired into a running service. Some capabilities are deliberately promoted **dormant** (code present, no runtime invocation); the channel being live is distinct from which capabilities are active. The authoritative live/seam/dormant breakdown is `docs/STATUS.md §Cognitive Expansion — activation status`.

## Environment Definitions

### `dev`
- **Purpose**: development, experimentation, debugging, local validation, and bounded forward-line exploration.
- **Isolation level**: flexible. Separate vaults and stores are strongly preferred, but the posture is optimized for iteration rather than strict reproducibility.
- **Vault/state/runtime boundaries**: may use local fixtures, dev-specific vault roots, selective resets, mock providers, and extra diagnostics.
- **Implemented now**: explicit runtime selection exists today through `PKM_ENVIRONMENT=dev` or `PKM_SETTINGS_PROFILE=lab`.
- **Not implied**: `dev` is not the canonical proof path for release readiness.

### `test`
- **Purpose**: isolated, resettable, reproducible local verification and UAT against a clean vault.
- **Isolation level**: explicit and strong. `test` must not depend on a live dev vault, hidden folder hints, or leftover runtime state.
- **Vault/state/runtime boundaries**: separate clean vault, resettable runtime artifacts, and a scripted bootstrap/UAT path that can be rerun from a clean start.
- **Implemented now**: `test` is a first-class `PKM_ENVIRONMENT` selector value alongside `dev` and `prod` (Issue #848 / PR #940). The runtime accepts `PKM_ENVIRONMENT=test`, scopes the database name to `app_test` (overridable via `PKM_DB_NAME_TEST`), scopes the vault root to a `-test` suffix (overridable via `VAULT_ROOT_TEST`), and scopes runtime artifact paths under `tmp-test/`. The repo-supported bootstrap path (`make test-bootstrap`, `make test-vault-init`, `uat-*`, and `scripts/start_full_system.sh`) remains the canonical local verification workflow on top of the selector.
- **Target contract**: this is the repo-supported local verification environment that should become self-contained end to end.

### `prod`
- **Purpose**: the operator-facing runtime used against a real vault and its associated runtime surfaces.
- **Isolation level**: conservative and safety-first.
- **Vault/state/runtime boundaries**: the real vault and its continuity artifacts must remain clearly separated from development and test surfaces.
- **Active channel today**: `prod` is the live operator channel, not a forward-only aspiration. A `stable`-pinned build runs against the real Midgård vault (`make prod-start-full`, with `VAULT_ROOT` loaded from `.env.prod.local`), with the operator-safe default posture, health/status surfaces, write-safety enforcement, and recorded promotion receipts under `ops/promotions/`. Channel identity, per-channel DB isolation, promotion, and rollback are owned by `docs/RELEASE_CHANNELS/README.md`, which treats `stable`/prod as operational; this document continues to own only environment selection and path scoping.
- **Promoted ≠ running** (do not over-claim): the prod *channel* being live does not mean every capability shipped to it is active. Code is promoted by moving the `stable` ref, but some capabilities ride along **dormant** — present on `stable` with no runtime invocation — by deliberate sequencing (for example, Wave 1 promoted Contextual Relevance Engine and durable-recall code inert; "CRE in prod" was not "CRE running", per `ops/promotions/2026-06-13-cc3ce65d.md §5`). Treat "promoted to prod" as a channel/code fact and consult `docs/STATUS.md §Cognitive Expansion — activation status` for which capabilities are actually live, seam, or dormant.
- **Still hardening (not a finished end-state)**: an active channel is not a completed operational story. Promotion-workflow automation (`prepare → execute → verify → rollback`), automated migration-reversal classification, and operator acknowledgement receipts are being hardened as a separate governance layer on top of the live baseline (`docs/RELEASE_CHANNELS/README.md §Future promotion hardening`). The current priority remains a sound, safe prod baseline.

## Cross-Environment Invariants

The following are SoT invariants and MUST remain true in `dev`, `test`, and `prod`:
- The same architecture contracts apply: vault-first human surface, companion/system surface, and rebuildable runtime surface.
- The event envelope and outbox semantics remain stable; DB outbox is canonical runtime queue semantics.
- Writes to tracked notes remain deterministic and guarded by write-safety and idempotency rules.
- Artifact identity, provenance, and receipt semantics do not change by environment.
- Settings and policy remain the control surface for runtime behavior; environment selection must not bypass policy, allowlists, or write guards.
- A real environment split must not redefine the human-facing contract in `docs/HUMAN-FLOWS.md`.

Environment is therefore an operational/runtime distinction, not a different ontology of artifacts or a different semantic model of the product.

## Allowed Variation by Environment

The following may vary between `dev`, `test`, and `prod` without breaking SoT, as long as the invariants above remain intact:
- runtime scale, process topology, and startup wrappers
- provider choice and model profile
- diagnostic verbosity, mocks, and test fixtures
- watcher cadence, tuning, and other explicit lab-only controls
- local fixture vaults, test stores, reset/reseed workflows, and scripted bootstrap wrappers
- operator gating and rollout posture for mutation-capable automation

**Variation rule**: environment-specific defaults may vary; environment-specific contract semantics may not.

## Separation Requirements

Environment separation MUST be explicit across the following surfaces.

### Vaults and Human-Facing Files
- `prod` must operate on the operator's real vault and its associated continuity artifacts.
- `dev` should use a separate fixture, test, or otherwise intentionally non-production vault when environment-specific experimentation or validation is being performed.
- `test` must use a separate vault dedicated to the repo-supported bootstrap/UAT path, distinct from the prod vault. The operator configures it via `VAULT_ROOT`/`VAULT_ROOT_TEST` (e.g. a dedicated test Obsidian vault); `make test-bootstrap` fails loud if no test vault is configured rather than fabricating one.
- `dev`, `test`, and `prod` must not implicitly share the same writable vault surface when the purpose is environment isolation.

**Implementation Status (Issues #266, #848)**:
- Vault paths are now environment-scoped via `app.config.paths.resolve_vault_root()`.
- Vault roots are operator-configured per channel — there are no synthetic `vault/`, `vault-dev/`, `vault-test/` defaults baked into the channel identity; each channel binds the operator's configured vault and fails loud when unset.
- Per-environment overrides honour `VAULT_ROOT_DEV` and `VAULT_ROOT_TEST`; the local bootstrap path also continues to honour `TEST_VAULT_ROOT` as the documented operator surface.
- Custom overrides via CLI flags bypass environment scoping.

### Stores and Persistence
- `prod` runtime persistence must be treated as production data even when it is rebuildable from the file-based continuity set.
- `dev` stores, indexes, and outbox state may be reset, rebuilt, or replaced for testing.
- `test` runtime state may be reset and rebuilt as part of the supported bootstrap contract; repeatability is more important than persistence.
- Rebuildable does not mean disposable in `prod`; recovery and audit expectations still apply.

**Implementation Status (Issues #266, #594, #848)**:
- Index outbox and store paths are now environment-scoped via `app.config.paths.resolve_runtime_artifact_path()`.
- Default behavior: `prod` uses `tmp/` subdirectories, `dev` uses `tmp-dev/` subdirectories, `test` uses `tmp-test/` subdirectories.
- Watcher settings automatically apply environment scoping to all artifact paths via `load_watcher_settings(environment=...)`.
- PostgreSQL now follows per-environment database naming conventions for runtime stacks:
  - `prod`: `app` (override: `PKM_DB_NAME_PROD`)
  - `dev`: `app_dev` (override: `PKM_DB_NAME_DEV`)
  - `test`: `app_test` (override: `PKM_DB_NAME_TEST`)
- Explicit `DATABASE_URL` / `DB_DSN` still overrides environment-derived conventions.
- File-based audit logs respect environment separation.

### Runtime State and Process Surfaces
- Watcher state, heartbeats, tick logs, incident logs, and similar runtime artifacts must be interpreted as environment-scoped operational surfaces.
- `dev` may expose extra diagnostics and lab-only controls.
- `test` may reuse the standard local runtime topology, but the repo-supported bootstrap path must reset runtime state before verification and must not rely on leftover watcher pause/state files.
- `prod` must keep these surfaces stable enough to support operator verification and incident triage.

**Implementation Status (Issues #266, #848)**:
- Watcher heartbeat, state files, and event logs are now environment-scoped.
- Default behavior: `prod` uses base artifact paths (`tmp/watcher_state.json`), `dev` uses `-dev` subdirectories (`tmp-dev/watcher_state.json`), `test` uses `-test` subdirectories (`tmp-test/watcher_state.json`).
- The local `test` Compose/bootstrap lane uses `tmp-test/runtime.env` so regenerated service env does not leak into the default `prod` runtime env file.
- Incidents and audit surfaces respect environment separation to prevent cross-environment contamination.
- The `test` bootstrap path resets runtime state explicitly before startup and verification.

### Settings and Policy Surfaces
- Environment selection must resolve through explicit settings/runtime configuration, not through undocumented convention.
- Lab/dev-only tuning must remain excluded from normal production runtime unless explicitly enabled by the documented control surface.
- The local `test` path is now selectable via `PKM_ENVIRONMENT=test` and gets scoped vault, DB, and artifact paths; the supported bootstrap contract (`make test-bootstrap`) continues to own resettable verification on top of that selector.

## Production Safety Expectations

`prod` carries the following additional expectations:
- safety beats convenience when the two conflict
- bounded writes only; no silent broad note mutation
- degraded or blocked mode is preferable to unsafe mutation
- health, status, and operator verification surfaces must remain meaningful
- rollout of mutation-capable automation must remain explicitly gated
- recovery paths must preserve the continuity set: vault notes plus companion notes

**Operational consequence**: production incidents, unsafe drift, or blocked write conditions should route through health/write-guard/operator workflows rather than ad hoc override behavior.

## Runtime Control Surface

The runtime provides explicit environment selection through a documented control surface with a clear priority hierarchy for `dev`, `prod`, and `test`.
The local `test` bootstrap workflow runs on top of the `PKM_ENVIRONMENT=test` selector and remains the canonical resettable verification path.

### Environment Variables

| Variable | Values | Purpose | Default |
| --- | --- | --- | --- |
| `PKM_ENVIRONMENT` | `dev`, `prod`, `test` | **Explicit** first-class runtime environment selection. Takes priority over all other signals. | (not set) |
| `PKM_SETTINGS_PROFILE` | `operator`, `lab` | **Legacy** settings profile control. Maintained for backward compatibility. `lab` -> dev environment, `operator` -> prod environment. The legacy profile does not select `test`; use `PKM_ENVIRONMENT=test` for that. | `operator` |

### Resolution Hierarchy

Environment resolution follows this priority:

1. **Explicit environment selection via `PKM_ENVIRONMENT`** (if set to `dev`, `prod`, or `test`)
   - The canonical modern control surface for runtime environment selection
   - Takes priority over settings profile
   - Case-insensitive; whitespace is stripped

2. **Implicit environment from settings profile** (if `PKM_ENVIRONMENT` not set)
   - `PKM_SETTINGS_PROFILE=lab` -> `dev` environment
   - `PKM_SETTINGS_PROFILE=operator` -> `prod` environment (default)
   - This mapping allows existing operator/lab workflows to continue working without changes

3. **Default to prod** (if neither explicit nor implicit signals are present)
   - Preserves current production-facing baseline behavior
   - Ensures safe defaults when no environment configuration is present

### Backward Compatibility

The existing `PKM_SETTINGS_PROFILE` control mechanism continues to work without changes:

- Operator runbooks and scripts using `PKM_SETTINGS_PROFILE=operator` are mapped to the `prod` environment
- Dev/lab workflows using `PKM_SETTINGS_PROFILE=lab` are mapped to the `dev` environment
- **No existing behavior changes silently.** Operators see the same control semantics; they now route through the explicit environment model internally.

The settings profile is now understood as a **narrower control mechanism that lives beneath the environment model**, rather than the full environment specification. As the runtime evolves, new environment-specific behavior should be controlled via `PKM_ENVIRONMENT` rather than extending the settings profile approach. The legacy `PKM_SETTINGS_PROFILE` mechanism does not project to `test`; `test` is reachable only through the first-class `PKM_ENVIRONMENT=test` selector, which the local bootstrap workflow now uses.

## Canonical Local Test Bootstrap

The official local `test` golden path is:

```bash
make test-bootstrap
```

Default target vault:
- `TEST_VAULT_ROOT=$(pwd)/vault-test`

Expanded path:
1. reset runtime state
2. initialize a clean test vault
3. seed the UAT notes
4. start the local stack against that vault
5. verify health/status
6. run scripted UAT

Contract:
- resets runtime state
- bootstraps a clean test vault layout without undocumented folder env vars
- seeds the repo-supported UAT note pack
- starts the local stack against that vault
- verifies health/status
- runs the scripted UAT flow successfully

For detailed specification and step-by-step verification contract, see `docs/LOCAL_TEST_BOOTSTRAP/`.

Operator note:
- `make test-vault-init` is the narrow helper that prepares the clean test vault without starting the stack.
- `test` is the current golden path for local verification and stabilization work.
- `dev` remains the flexible development posture, and `prod` remains the conservative operator posture.

## Parallel Local Stacks

The repo supports parallel local Compose stacks for `dev`, `test`, and `prod` on one machine without host-port conflicts.

Commands:

```bash
make prod-up
make dev-up
make test-up
```

Port map:
- `prod`: Postgres `15432`, API `18000`
- `dev`: Postgres `15433`, API `18001`
- `test`: Postgres `15434`, API `18002`

Compose files:
- `docker-compose.yaml` (base + prod defaults)
- `docker-compose.dev.yml` (dev overrides)
- `docker-compose.test.yml` (test overrides)

Notes:
- `make start-test-system` and `make test-bootstrap` remain unchanged and are still the canonical local `test` verification workflow.
- The `test` compose override sets `PKM_ENVIRONMENT: test` (first-class as of Issue #848 / PR #940); test-channel isolation comes from the matching scoped DB (`app_test`), scoped vault (`vault-test/` or `VAULT_ROOT_TEST`), scoped artifact paths (`tmp-test/`), and port separation.
- Full parallel isolation still depends on DB separation work tracked by Issue #594.

## Relation to Current Health, Write Guard, and Settings Direction

### Health and Write Guard

The health contract and write guard remain independent of environment selection. All production safety invariants (deterministic health checks, write guard enforcement, event safety) apply in `dev`, `test`, and `prod`. Environment selection does not bypass safety constraints.

### Settings and Configuration

The environment model provides **one canonical control point for environment-specific behavior across the runtime**, replacing the earlier scattered approach where settings profiles and partial environment knobs controlled different aspects independently.

- **Before**: Operator/lab profiles controlled watcher tuning; other environment-specific features used ad-hoc env vars or configuration files.
- **After**: Environment selection (via `PKM_ENVIRONMENT`) is the canonical signal for `dev`, `prod`, and `test`. Settings profiles are mapped to it for compatibility (`lab` -> `dev`, `operator` -> `prod`); `test` is reachable only through the explicit selector. New environment-specific behavior should register against this model rather than add new scattered controls.

### Operability and Transparency

Operators can check the active environment and understand the configuration state:

- `python -m app.cli settings-explain` and `python -m app.cli status` surface the resolved runtime environment
- logs and diagnostics can report which runtime environment is active
- the test bootstrap path remains explicit in `make test-bootstrap`, `docs/OPERATIONS.md`, and `docs/TESTING.md`
- configuration compiler and settings validator understand environment-aware behavior

Delivery receipt:
- Issue #265 / PR #272 shipped environment-aware operator diagnostics across health, status, settings-explain, and incident-facing surfaces. Environment reporting is no longer pending future work in this document; remaining follow-through should focus on the bounded local `test` bootstrap contract and other explicit slices of the environment model.

## Implementation

### Runtime Contracts

Environment resolution is provided by `app.config.environment`:

```python
from app.config.environment import (
    active_environment,
    is_dev_environment,
    is_prod_environment,
    is_test_environment,
)

env = active_environment()

if is_dev_environment():
    pass
```

The resolution follows the documented hierarchy: explicit `PKM_ENVIRONMENT` (`dev`, `prod`, or `test`) > implicit from `PKM_SETTINGS_PROFILE` > default to `prod`.

### Integrations

Settings modules (watcher, agent, etc.) that need environment-specific behavior should:

1. Import and use `active_environment()` to check environment state.
2. Document which settings are dev-only or environment-specific.
3. Respect the same write-safety and health constraints in all environments.
4. Test behavior across all runtime-selected environments (`dev`, `prod`, `test`) and keep the bootstrap path explicit where it remains the canonical local verification flow.

The existing `app.settings.tiering` module continues to work and is now understood as implementing profile-based (operator/lab) access to the underlying environment model.

## Constraints and Out of Scope

- Environment selection does not redefine product semantics.
- Channel identity, promotion, rollback, and DB-per-channel semantics are owned by `docs/RELEASE_CHANNELS/README.md`, not this document. This document continues to own environment selection and path scoping only.
- Hosted deployment, secrets handling, and CI/CD-driven release remain out of scope. Local, single-user promotion between channels is owned by the release-channels capability.
- Health/status/operator diagnostics changes are independent of environment selection.
- Multi-user/multi-instance coordination remains orthogonal to environment selection.

## Suggested Validation

- confirm `python -m app.cli settings-explain` reports the resolved runtime environment coherently for `dev`, `prod`, and `test`
- confirm `make test-bootstrap` remains the documented local verification golden path for `test`
- confirm environment-specific runtime artifacts do not leak between `dev`, `test`, and `prod` postures
- confirm status/operations/testing docs all describe the same `dev` / `test` / `prod` model and the same bootstrap path
