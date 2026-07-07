---
name: Rebind On Vault Selection
description: Selecting or switching a vault rebinds every vault-scoped settings consumer — watcher ingest binding included — via VaultChangedEvent
task_id: SETTINGS-05
source_anchor: docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F4
parent_capability: Settings Spine
prerequisites: [SETTINGS-01]
depends_on: [WIRE_SETTINGS_INGESTION.md]
can_parallelize_with: [Canonicalize Settings Location, Receipt Every Settings Write]
---

# Rebind On Vault Selection

## Purpose

Close audit finding F4 (SET-7): `WATCHER_VAULT_PATH` is read once at watcher boot and never
rebinds when a vault is selected through the Companion UI, so a capture can succeed while
remaining invisible to ingest (`docs/ENVIRONMENTS.md:94-108`). More generally, vault-scoped
settings consumers must follow the selection, not a frozen env snapshot.

**Owner ruling (2026-07-07) supersedes prior posture.** Issue #2476 ("document the split, do not
converge") and #3119's closing fix (PR #3126, visible-warning-only, not self-healing) both
deliberately chose *not* to make the watcher follow live selection, treating watcher/API
convergence as an architectural line not to cross. The owner has now explicitly ruled the
opposite: the watcher must be flexible about what it watches — there is no value in a watcher
pointed at the wrong vault — and the mechanism should support redirecting a running watcher, not
just detecting divergence. This task implements that ruling and supersedes #2476's verdict; update
the module docstring in `app/watcher/config.py` (the "document the split, do not converge"
rationale) to record the supersession rather than leaving it as if still current.

## What This Task Does

- Subscribes the watcher's ingest binding to `VaultChangedEvent` (emitted by
  `VaultManager._emit_changed`, `app/vault/manager.py`) so selection/switch rebinding happens in
  the running process: re-resolve vault root → reload vault-scoped settings via the SETTINGS-01
  reload path (one loader, not a second one — see capability Cross-Task Invariants) → resume
  ingest against the new root.
- Upgrades the advisory `ingest_binding` status (`bound`/`diverged`/`unbound`/`unknown`) so
  `diverged` becomes a transient state that self-heals on rebind, and a rebind failure is loud.
- Retires the second, unsynchronized "current vault" notion in
  `runtime/settings/instance.yaml` (`vault.name`/`vault.purpose` display metadata): display
  derives from the live selection, or the field is explicitly marked display-only and excluded
  from any binding decision.

## Concretely

```
# watcher running, no vault selected → idle (unchanged)
$ curl -s localhost:8000/api/companion/vault/select -d '{"ref":"path:/vaults/Niflheim"}'
$ curl -s localhost:8000/api/health | jq .watcher.ingest_binding   # "bound", path = Niflheim
# capture a note → it reaches ingest without any container restart
```

## Why This Matters

Selection being the source of truth (Option 2, #2325) is only true if consumers follow it. Today
the UI says one vault and ingest watches another — captures silently vanish from retrieval.

## Acceptance Criteria

- [ ] Selecting a vault via the production selection path rebinds the watcher ingest root in the
      running process; a file created in the newly selected vault is picked up by the next tick.
  - Verify: `tests/watcher/test_ingest_binding_follows_selection.py::test_selection_rebinds_ingest`
    (enforcement AC — drives `VaultManager.select_vault` and asserts the watcher subscriber fires
    from the production event, not a direct call to the rebind helper)
- [ ] Switching vaults mid-run rebinds cleanly: in-flight tick completes against the old root, next
      tick runs against the new root, `ingest_binding` reflects each state truthfully.
  - Verify: `tests/watcher/test_ingest_binding_follows_selection.py::test_switch_is_clean_and_truthful`
- [ ] Rebind triggers the SETTINGS-01 settings reload for the new vault (vault-scoped settings
      follow the vault; one bundle swap).
  - Verify: `tests/watcher/test_ingest_binding_follows_selection.py::test_rebind_reloads_settings`
- [ ] No-vault → selected transition and selected → no-vault (vault removed) both land in truthful
      idle/bound states, never a crash or a stale binding reported healthy.
  - Verify: `tests/watcher/test_ingest_binding_follows_selection.py::test_novault_transitions_truthful`
- [ ] SET-7 registered in the invariant registry with enforcement `runtime_test`; `app/watcher/config.py`'s
      "document the split, do not converge" docstring is updated to record that #2476's verdict is
      superseded by this task (owner ruling 2026-07-07), not silently left to read as current.
  - Verify: doc writeback at `docs/testing/invariant-tests.md :: vault_selection_rebinds_consumers`
    + doc writeback at `app/watcher/config.py` module docstring

## How to Verify (Pre-Merge)

- `pytest -q tests/watcher/test_ingest_binding_follows_selection.py`
- `pytest -q -m "not pg"` and `RUN_INTEGRATED_RUNTIME_UAT=1 pytest -q tests/integration -k "watcher or settings"`
  (vault/watcher hot path)

## Out of Scope

- Running more than one watcher at a time, or spinning up temporary/time-limited watchers on
  demand — the owner has flagged this as a wanted future capability (see the Settings Spine
  README follow-up note), but it is a distinct, larger capability (multi-watcher lifecycle
  management) than "the one watcher follows the one active selection." This task's rebind
  mechanism (subscribe-to-`VaultChangedEvent`, re-resolve, resume) is the building block a future
  multi-watcher task would reuse per-instance, but instantiating multiple watchers is not this
  task's scope.
- Multi-active-vault epic #2143 in the sense of concurrently serving more than one selected vault
  to the API/retrieval layer — still exactly one active vault at a time, as today. (This task is
  about the watcher *following* that one selection, not about serving several at once.)
- Location migration (SETTINGS-03).
- `WATCHER_VAULT_PATH` env removal — it remains the deploy bootstrap for headless channels; this
  task makes live selection override it, with the override visible in `ingest_binding`.

## Restart / Durability Posture

The binding is in-memory; on restart the watcher rebinds from the durable selection
(`AppLocalSettingsStore.last_active_vault_ref`) rather than from env-only state, so a restart
lands on the same vault the human last selected. If no durable selection exists, env bootstrap
applies and the binding status says so.

## Related Docs

- `docs/audits/SETTINGS_ARCHITECTURE_2026-07-07.md :: F4`
- `docs/ENVIRONMENTS.md :: ingest binding` · Issue #2476 (superseded by this task's owner ruling)
  · Issue #3119 (closed; this task supersedes its visible-warning-only resolution with a real
  rebind)

## Related GitHub Issues

One implementation issue. Does not close #3119 (already closed) or #2476 (already closed); the PR
should link both and state explicitly that this supersedes their prior "do not converge" posture.
TCD hint: opus / high — concurrency-sensitive rebind on the ingest hot path; reverses a prior
architectural decision, so the PR needs explicit owner-visible framing, not just code review.
