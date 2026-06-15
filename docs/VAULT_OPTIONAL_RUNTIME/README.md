# Vault Optional at Runtime

State: Specification filed. Parent feature issue **#2003** (validation hub); children #2004–#2007. See `PARENT_FEATURE_ISSUE.md`.
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
| 2 | [BOOT_RUNTIME_WITHOUT_VAULT](BOOT_RUNTIME_WITHOUT_VAULT.md) | #2005 | watcher idles instead of fail-exiting; `start_full_system.sh` boots with no vault; #1991 flip + F4 producer/preflight updates | Blocked on 1 |
| 3 | [COMPANION_NO_VAULT_ROUTING](COMPANION_NO_VAULT_ROUTING.md) | #2006 | companion `vault_selection_required` covers the *unset* case; open/switch/register verified end-to-end | Delivered (`/api/companion/vault/context` returns `reason="no_vault_bound"` with `recent_vaults`; verified by `tests/api/test_companion_vault_routing.py`) |
| later | [PIN_VAULT_DEFINITION](PIN_VAULT_DEFINITION.md) | #2007 | pin the overloaded "vault" term across docs | Deferred (needs-human) |

## Execution order

`RESOLVE_NO_VAULT_STATE` → ( `BOOT_RUNTIME_WITHOUT_VAULT` ∥ `COMPANION_NO_VAULT_ROUTING` ) → `PIN_VAULT_DEFINITION` (any time; gated as a human decision).

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
