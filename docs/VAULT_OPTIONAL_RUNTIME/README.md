# Vault Optional at Runtime

State: Specification filed. Parent feature issue **#2003** (validation hub); children #2004-#2007. Follow-up eager resolver migration hub **#2311** is split into Slices 05A-05D. See `PARENT_FEATURE_ISSUE.md`.
Doc role: Capability specification / source of truth for the breakdown.
Owner decision: 2026-06-14 — a vault is **not required at initiation**; the runtime boots
with no vault bound and idles until one is opened; vaults can be opened, switched, and
registered (multiple). Scope **includes the runtime `VAULT_ROOT` binding**, not only the
companion UI.

---

## Capability boundary

Today the product assumes a vault is bound before it can run:

- `resolve_vault_root` (`app/config/paths.py`) falls back to a **relative `./vault`** when
  `VAULT_ROOT` is unset (CWD-dependent footgun) and **raises** `VaultRootMisconfiguredError`
  when it is set-but-missing.
- the watcher **fail-exits** on an `uninitialized` vault (`app/watcher/config.py:61`,
  `app/watcher/registry.py:692`) — the #1991 hard precondition — and raises `FileNotFoundError`
  when the vault root is absent (`registry.py:59`, `registry.py:1099`).
- `scripts/start_full_system.sh` **requires** `VAULT_ROOT` and exits 2 when it is unset
  (unless `ALLOW_LEGACY_VAULT=1` re-introduces the `./vault` default).

The owner decision makes the vault **optional at initiation**. With no vault bound the
runtime must boot into a **no-vault idle** state (status `none`, already modelled by
`app/vault/manager.py :: no_vault_context`) and surface the **open-vault picker**; opening,
switching, and registering vaults happen at runtime and re-resolve in-process.

Much of the *companion* surface already exists from the merged vault-selector foundation
(`b65b2d3b`, #1757, #1867, last-active #1895): `/api/companion/vault/{context,select,initialize}`,
the `vault_selection_required` state, `known_vaults`, and `load_last_active`. This capability
adds the **runtime** half (config resolver + watcher boot + bring-up) and **closes the unset /
no-vault gap** the existing seam left open (#1757 covered *set-but-missing* only).

In scope:
- runtime boots and idles with no vault bound; no crash, no CWD-relative default;
- the #1991 watcher precondition flips from fail-exit to idle-until-opened, with **all
  producers + preflights updated symmetrically** (the #1997 F4 invariant→producers rule, in
  reverse — relaxing an invariant);
- the companion no-vault routing extends to the *unset* case, not just set-but-missing;
- open / switch / register multiple vaults is verified end-to-end against the existing
  `VaultManager` registry primitives (gaps closed, not rebuilt).

Out of scope (this capability):
- the picker **UI rendering** (owned by #1867 / companion-ui);
- pinning the overloaded **definition of "vault"** — deferred to `PIN_VAULT_DEFINITION` per
  owner ("2 now, 3 later");
- the **test/promotion channel**, which deterministically *provisions* one vault via the
  #1997 bootstrap and is intentionally **not** vault-optional (deterministic UAT needs a known
  vault). The #1997 harness is unaffected.

## Implementation tasks

| Order | Task | Issue | Adds | Status |
| --- | --- | --- | --- | --- |
| 1 | [RESOLVE_NO_VAULT_STATE](RESOLVE_NO_VAULT_STATE.md) | #2004 | config resolver returns a no-vault state when `VAULT_ROOT` is unset (stop defaulting to `./vault`) | Delivered (`resolve_optional_vault_root` in `app/config/paths.py`) |
| 2 | [BOOT_RUNTIME_WITHOUT_VAULT](BOOT_RUNTIME_WITHOUT_VAULT.md) | #2005 | watcher idles instead of fail-exiting; `start_full_system.sh` boots with no vault; #1991 flip + F4 producer/preflight updates | Delivered (#2005 closed 2026-06-15; prerequisite #2004 delivered) |
| 3 | [COMPANION_NO_VAULT_ROUTING](COMPANION_NO_VAULT_ROUTING.md) | #2006 | companion `vault_selection_required` covers the *unset* case; open/switch/register verified end-to-end | Delivered (`/api/companion/vault/context` returns `reason="no_vault_bound"` with `recent_vaults`; verified by `tests/api/test_companion_vault_routing.py`) |
| later | [PIN_VAULT_DEFINITION](PIN_VAULT_DEFINITION.md) | #2007 | pin the overloaded "vault" term across docs | Deferred (needs-human) |

## Follow-up eager resolver migration (#2311)

The foundation above introduced the optional resolver and shipped the startup/picker behavior.
#2311 is the cleanup hub for remaining eager `resolve_vault_root()` consumers. It is not a
single ready implementation slice; it is split into bounded children so request paths,
background producers, shared path helpers, import-time/CLI/agent/MCP/knowledge consumers,
and final runtime mount cleanup can be verified independently.

| Order | Task | Issue | Adds | Status |
| --- | --- | --- | --- | --- |
| 05A | [API_ENDPOINT_OPTIONAL_VAULT_BOUNDARIES](API_ENDPOINT_OPTIONAL_VAULT_BOUNDARIES.md) | #2383 | capture/artifacts/canvas/debug and companion request helpers return picker/empty no-vault responses instead of `./vault` fallback | First pickup target; deliver before 05B/05C/05D unless explicitly parallelized |
| 05B | [BACKGROUND_OPTIONAL_VAULT_IDLE](BACKGROUND_OPTIONAL_VAULT_IDLE.md) | #2384 | outbox worker, watcher/health settings, inbox appenders, and vault path helpers idle or report no-vault when no vault is selected | Delivered (`outbox_worker.run_once` idles `no_vault`; watcher settings empty source; health reports `vault.status` none/not_selected; inbox appenders skip; vault path helpers raise `NoVaultSelectedError`; CWD `./vault` fallback removed; guarded by `tests/api/test_no_silent_cwd_vault_fallback.py::test_background_resolvers_do_not_fallback_to_cwd_vault`) |
| 05C | [PROMOTION_CLI_AGENT_OPTIONAL_VAULT_RESOLUTION](PROMOTION_CLI_AGENT_OPTIONAL_VAULT_RESOLUTION.md) | #2385 | promotion queue import becomes lazy; CLI/agent/helper/MCP/knowledge callers make vault requirements explicit or optional | Blocked/backlog until 05A/05B sequencing is clear |
| 05D | [LEGACY_VAULT_MOUNT_REMOVAL](LEGACY_VAULT_MOUNT_REMOVAL.md) | #2386 | legacy `/app/vault` compose/runtime-env fallback is removed or re-baselined after resolver consumers no longer require it | Blocked/backlog until 05A-05C land |

## Cross-Task Invariants / Interaction Safety

- No runtime code path may silently resolve to CWD-relative `./vault` when no vault is
  selected and `VAULT_ROOT` is unset.
- This covers direct `Path("vault")` helper fallbacks, not only call sites that import
  `app.config.paths.resolve_vault_root()`.
- Request-path endpoints return the picker/no-vault contract or an explicitly empty read
  result; they do not 500 or serve an empty fallback vault.
- Background producers idle/no-op when no vault is selected.
- Import-time modules do not resolve a vault as a side effect of import.
- CLI commands either accept an explicit vault or fail with an explicit operator-facing
  vault requirement.
- Selected-vault behavior remains unchanged.
- Changes that touch vault resolution, active-vault boundaries, or companion hot paths must
  run the opt-in IR-v1 UAT: `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/uat/`.
- Partial delivery is explicitly a mixed-migration state: after 05A lands, request-path
  endpoints may be safe while background/helper/CLI/MCP/knowledge and mount/runtime-env
  fallbacks remain tracked in 05B-05D. Do not claim the global no-fallback invariant until
  all four slices have posted evidence.
- 05B, 05C, and 05D stay Backlog/blocked unless the coordinator updates the issue contract
  and Project state; they must not become `agent:ready` just because 05A is in flight.
- If implementation discovers another runtime `./vault` fallback outside 05A-05D, stop,
  update #2311, and create or route a bounded child slice before claiming closure.
- Each delivered child posts evidence to #2311. Posting the same evidence to #2003 is
  traceability for the original capability, not automatic closure authority for #2003.

## Execution order

`RESOLVE_NO_VAULT_STATE` → ( `BOOT_RUNTIME_WITHOUT_VAULT` ∥ `COMPANION_NO_VAULT_ROUTING` ) → `PIN_VAULT_DEFINITION` (any time; gated as a human decision).

Follow-up #2311 sequencing: `API_ENDPOINT_OPTIONAL_VAULT_BOUNDARIES` first, then
`BACKGROUND_OPTIONAL_VAULT_IDLE`, then `PROMOTION_CLI_AGENT_OPTIONAL_VAULT_RESOLUTION`,
then `LEGACY_VAULT_MOUNT_REMOVAL` unless the coordinator confirms non-overlapping pickup.

## Capability acceptance

- [ ] The runtime stack boots with `VAULT_ROOT` unset and the watcher idles (no fail-exit, no crash). Verify: `tests/runtime/` boot/idle test named in `BOOT_RUNTIME_WITHOUT_VAULT`.
- [x] With no vault bound, the companion boundary returns `vault_selection_required` (not 500 / not a `./vault` default). Verify: `tests/api/test_companion_vault_routing.py::test_no_vault_returns_selection_required` (and `::test_selection_required_lists_known_vaults` for the `known_vaults` recent list).
- [x] Opening a vault re-resolves in-process; switching between ≥2 registered vaults persists last-active. Verify: `tests/api/test_companion_vault_routing.py::{test_select_vault_reresolves_in_process,test_switch_between_known_vaults_persists_last_active}`.
- [ ] No producer of the vault-required invariant still assumes a vault is mandatory (the #1991 flip is complete and symmetric). Verify: `BOOT_RUNTIME_WITHOUT_VAULT` AC + the #1997 channel preflight still requires a vault for the *test* channel only.
- [ ] The "vault" definition is pinned in docs. Verify: `PIN_VAULT_DEFINITION` doc anchor (deferred).

## Relationship to GitHub issues

The specification is the source of truth; the GitHub issues track pickup. The parent feature
issue is the live validation hub (`agent:blocked` while children are outstanding). Each child
implements one task file and posts a validation receipt to the parent before the next is
picked up. See `PARENT_FEATURE_ISSUE.md` for the live issue number once filed.

## Related docs

- `docs/ENVIRONMENTS.md` — environment / vault binding model
- `app/config/paths.py`, `app/vault/manager.py`, `app/watcher/{config,registry}.py`, `app/api/routes/companion.py`
- #1757 (set-but-missing seam, closed), #1867 (picker UI), #1895 (last-active), #1991 (vault-init precondition), #1997 (F4 invariant→producers rule)
