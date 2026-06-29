---
name: Surface-agnostic runtime control-action boundary
description: >
  Enumerates the control actions any interaction surface may legitimately initiate,
  classifies each as authority-bearing or not, and defines the GOV/EXE routing each requires.
  Settles the authority classification of runtime-gating settings writes (enableVaultWatcher /
  enableAutoIndexing) as authority-bearing (proportional tier) with governed seam + actor receipt.
task_id: ISA-RUNTIME-CTRL
parent_capability: interaction-surfaces-and-authority
governs: #2475
decision_date: 2026-06-24
decision_author: RasmusTho (owner)
status: active
---

State: Active decision record. Canonical authority for the runtime control-action register.

# Surface-Agnostic Runtime Control-Action Boundary

## Framing

The human is the authority. Every interaction surface (UI, CLI, file edit, MCP, API) is a
**transport** of human intent — not itself a decision-maker. The same intent arriving on different
surfaces must produce the same governance outcome. The server-side governed seam is the single
classification and enforcement point.

This document is surface-agnostic. It governs the register, not the UI specifically.

## Two-tier classification

### Tier 1 — Vault binding (pre-init)

Vault select, initialize, and reload actions happen before a vault is initialized. They route
through app-local / WSP binding. No vault-scoped governance applies (the vault does not yet exist).
The UI is typically the human's only surface at this stage.

**Applies to:** `POST /api/companion/vault/select`, `POST /api/companion/vault/initialize`,
`POST /api/companion/vault/reload`.

**Receipt:** Binding and init events are logged. No `SettingsWriteReceipt` is emitted (not a
settings write).

### Tier 2 — Runtime gating (post-init, authority-bearing)

`enableVaultWatcher` and `enableAutoIndexing` gate whether the watcher/indexing runtime runs:
- `app/watcher/registry.py:734` — watcher registry refuses to start when `enable_vault_watcher`
  is false.
- `app/watcher/config.py:92` — watcher config refuses to start when `enable_vault_watcher` is
  false.
- Both settings are `editable_in_companion=True` (`app/vault/settings_service.py:152-153`).

**Classification:** authority-bearing (proportional tier). A write reconfigures runtime
behaviour, so it must route through the single governed seam.

**Proportionality rationale (#1881):** The action is reversible and local (no external boundary).
A human may already flip the same flag by hand-editing `settings/local.md` — a legitimate
interaction with their own vault that has no approval gate. Forcing an approval loop on the
UI/API write but not the file edit would be inconsistent and would push users to bypass the
governed path. Therefore: **no human/agent approval loop**. The seam applies the deterministic
WriteGuard health-gate and emits an actor-tagged receipt.

**Governed seam** (`app/vault/settings_service.py :: SettingsService.update_setting`):
1. `RUNTIME_GATING_SETTINGS: frozenset` classifies the key.
2. `DEFAULT_WRITE_GUARD.assert_writes_allowed()` is called; blocks if `state in
   WRITE_BLOCKED_STATES` (i.e. `safe_mode` or `unhealthy`).
3. The markdown write is applied to `settings/local.md`.
4. `SettingsWriteReceipt(key, value, surface, actor, timestamp, is_runtime_gating=True)` is
   emitted and logged at INFO.

**Valid origins of the same seam (no new surfaces here):**
- UI → `POST /api/companion/vault/settings` (surface=`'api'`) — **wired** (sole caller: `app/api/routes/companion.py:826`)
- CLI → existing `app.cli vault` commands (surface=`'cli'`) — **NOT yet wired** (the `app.cli vault` group does init/preflight only; no command toggles runtime-gating settings through the seam; addable when a consumer exists)
- File edit → watcher-detected `settings/local.md` delta (surface=`'file'`) — **wired** for
  runtime-gating key deltas by #2512
- Future MCP/API → addable when there is a consumer (out of scope here)

### Tier 3 — External-boundary enable

TTS provider enable crosses an external boundary. EBF applies. Not re-decided here; governed by
`#2086` / `#1699`.

## Audit blind-spot — closed for runtime-gating settings

A direct hand-edit of `settings/local.md` previously produced no receipt — only the watcher
picking it up at next start. The API door is wired, and #2512 wires the file-originated door for
runtime-gating deltas (`enableVaultWatcher` / `enableAutoIndexing`) through
`SettingsService.update_setting(..., surface='file', actor='human')`. The CLI `app.cli vault`
group is init/preflight only and still has no runtime-gating toggle command to wire.

## Server-authoritative classification rule

The server classifies every write. Classification lives server-side in `RUNTIME_GATING_SETTINGS`
(settings_service.py). The UI never re-derives authority from the server response.

## Acceptance record (from #2475)

- AC1: this document, `docs/COMPANION_UI_PRODUCT_SPEC.md :: Runtime control actions`, and
  `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md :: Control-action register` enumerate the
  control-action register and routing.
- AC2: `tests/companion_ui/test_runtime_control_settings_authority.py` exercises the production
  write path and asserts the governed seam is applied.

## Related

- `docs/COMPANION_UI_PRODUCT_SPEC.md :: Runtime control actions`
- `companion-ui/docs/UI_RUNTIME_BOUNDARIES.md :: Control-action register`
- `app/vault/settings_service.py` — `RUNTIME_GATING_SETTINGS`, `SettingsService.update_setting`,
  `SettingsWriteReceipt`
- `app/write_guard.py` — `WriteGuard`, `DEFAULT_WRITE_GUARD`
- `app/watcher/registry.py:734`, `app/watcher/config.py:92` — runtime gate that respects the flag
- `docs/SYSTEM_BREAKDOWN_STRUCTURE.md :: UI state becomes authoritative` (source rule)
- `docs/INTERACTION_SURFACES_AND_AUTHORITY/NAME_THE_THREE_INTERACTION_SURFACES.md`
