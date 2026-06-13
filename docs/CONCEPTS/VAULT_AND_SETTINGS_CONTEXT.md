State: Target architecture plus first implementation contract for the vault selector and scoped Markdown settings foundation. Current code implements the foundation only; follow-up issues own full Companion UI editing, complete settings extraction, and multi-vault runtime mounting.
Doc role: Concept contract / architecture
Authority: Governs the vault-context and settings-scope model introduced for Design Handoff and Companion UI startup. Current runtime truth remains with `docs/ARCHITECTURE.md` and implementation evidence.
Owner: Runtime / Companion UI / configuration
Temporal class: strategic
Review cadence: event-driven
Source of truth: mixed
Last reviewed: 2026-06-12

# Vault and Settings Context

## Purpose

The runtime must not assume a vault exists at startup. The app shell, Companion UI, help surfaces, built-in defaults, app-local preferences, and vault picker can start with no active vault. Vault-scoped operations must ask whether the specific operation requires a vault.

Core rule:

> Do not ask "does the app have a vault?" Ask "does this operation require a vault?"

## VaultStatus

`VaultStatus` represents the active vault state:

- `none`: no vault is selected.
- `selected`: a valid active vault is selected and initialized.
- `missing`: a stored path no longer exists.
- `invalid`: the folder exists, but required settings are corrupt, conflicted, or incompatible.
- `uninitialized`: the folder exists, but Design Handoff settings are missing.

Vault-dependent services must not start in `none`, `missing`, `invalid`, or `uninitialized`.

## VaultContext

Vault state is represented centrally:

```ts
interface VaultContext {
  status: VaultStatus;
  activeVaultId?: string;
  activeVaultName?: string;
  activeVaultPath?: string;
  settingsPath?: string;
  localInstanceId?: string;
  machineRole?: MachineRole;
}
```

The initial implementation may support one active vault, but callers should depend on a manager/service interface rather than hardcoded globals so future `settingsService.forVault(vaultId)` and `pathResolver.forVault(vaultId)` forms remain possible.

## MachineRole

The local clone role is structurally represented in vault-local settings:

- `primary`: can edit shared and local settings; can run watchers, indexers, and writers.
- `satellite`: can use shared content; local settings may disable shared edits, watchers, or indexing.
- `readOnlySatellite`: can view settings and content, but must not write vault project files.
- `automationNode`: may run without active UI and can run background services when configured.
- `testNode`: test or temporary vault role.

The first implementation gates obvious writes/background services by `allowWritesToVault`, `enableVaultWatcher`, and `enableAutoIndexing`. `readOnlySatellite` is a hard ceiling for vault project writes, watcher, indexing, and shared settings edits even if local settings try to enable them. Local settings edits are governed separately by `allowLocalSettingsEdits`, so a machine can be configured to adjust `settings/local.md` without gaining vault project write permission.

## Identity Model

Three identities are distinct:

- `appInstallId`: identifies the installed app instance on this machine. It is stored outside any vault in app-local settings and is used for recent vaults, last active vault, UI window state, ports, local cache paths, and credential references.
- `vaultId`: identifies the logical vault/project. It is stored in `<vault>/settings/vault.md` and may be committed to Git.
- `localInstanceId`: identifies one local clone/copy of a logical vault. It is stored in `<vault>/settings/local.md`, which is Git-ignored.

Known vaults must not be keyed only by `vaultId`; two local paths can point to clones of the same logical vault and still require separate `localInstanceId` values.

## Settings Scopes

Settings precedence is:

1. Built-in defaults.
2. App-local settings, only for app-local keys.
3. Vault-shared settings.
4. Vault-local settings.
5. Runtime/session overrides.

App-local settings must not override project behavior unless a setting definition explicitly marks the key as app-local.

Examples:

- `lastActiveVaultRef`: app-local.
- `windowSize`: app-local.
- `handoffFolder`: vault-shared.
- `workflowStatuses`: vault-shared.
- `machineRole`: vault-local.
- `enableVaultWatcher`: vault-local unless a setting definition explicitly makes it shared.
- `localExportPath`: vault-local.
- Secrets: never stored directly in vault settings; use references only.

## Markdown Settings Format

Vault settings are Markdown files with YAML frontmatter. They are human-readable, editable in Obsidian, and writable by the Companion UI through the same files.

Rules:

- Each file declares `schema` and `scope`.
- Machine-readable keys live in YAML frontmatter.
- The Markdown body explains the file.
- Shared paths should be vault-relative.
- Absolute paths are local-only.
- Writers preserve the Markdown body where feasible.
- Writers keep stable key order.
- Conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) make the file invalid; conflicted settings are not applied.
- Invalid settings degrade safely; they are reported rather than silently applied.

## Initial Vault Files

Vault initialization creates missing files only:

```text
<vault>/settings/
  vault.md
  paths.md
  workflow.md
  design-handoff.md
  companion-ui.md
  local.md
  .gitignore
```

`settings/.gitignore` ignores local-only settings:

```gitignore
local.md
*.local.md
local/
runtime/
cache/
```

It must not ignore the whole settings folder.

## Service Gating

Vault-dependent services require `VaultStatus.selected` plus permission settings.

Examples:

- Watchers require a selected vault, `enableVaultWatcher: true`, and a role that allows background work.
- Indexers require a selected vault and `enableAutoIndexing: true`.
- Writers and handoff generators require a selected vault and `allowWritesToVault: true`.
- Shared settings edits require project write permission plus `allowSharedSettingsEdits: true`.
- Local settings edits require `allowLocalSettingsEdits: true` and do not grant project write permission.
- Path resolution for vault-relative files must fail with an actionable unavailable state when no selected vault exists.

On vault switch, services should stop old watchers/jobs, clear cached vault paths, reload settings, emit or handle `vault.changed`, and restart only when the next context is selected and permissions allow it.

Suggested event payload:

```json
{
  "previousVaultId": "old-id",
  "previousVaultPath": "/old/path",
  "nextVaultId": "new-id",
  "nextVaultPath": "/new/path",
  "status": "selected"
}
```

## Scenario Matrix

| Scenario | Status | Allowed | Disabled |
| --- | --- | --- | --- |
| No vault selected | `none` | App shell, Companion UI, vault picker, built-in defaults, app-local prefs, docs/help | Watcher, indexer, handoff writer, vault-relative resolver, sync |
| First-time local vault | `selected` after init | Create settings folder/files, write local settings, start allowed services | Unsafe overwrite of existing files |
| Existing Obsidian vault without Design Handoff settings | `uninitialized` | Show initialize action, choose another vault | Watcher, indexer, writers |
| Missing moved vault | `missing` | Locate, choose another, remove recent, create new | Vault-scoped work |
| Invalid settings or Git conflict | `invalid` | Show validation error, open/reload settings | Applying invalid settings |
| Same logical vault cloned twice | `selected` per path | Separate known-vault records by path/local instance | Collapsing records by `vaultId` |
| Satellite/read-only | `selected` | Read and local settings according to permissions | Shared writes when role/settings disallow |

## Companion UI Behavior

Companion UI is a structured editor and selector surface; it is not the owner of settings.

No-vault state should show:

- No vault selected.
- Open existing vault.
- Create new vault.
- Open recent vault.

Selected state should show:

- Vault name and path.
- Machine role and permissions.
- Settings folder.
- Change vault.
- Open/reload settings.

Uninitialized, missing, and invalid states must show the relevant path/status and an action that can recover safely without silently overwriting user files.

## External Obsidian Editing

Obsidian remains a valid settings editor. The settings service should reload on demand and, when watcher infrastructure supports it, react to settings file changes. Companion UI writes should avoid noisy rewrites and preserve body text where feasible.

## Future Multi-Vault

The first foundation keeps one active vault. Future multi-active-vault work must preserve:

- path/local-instance identity separate from logical `vaultId`,
- per-vault settings service instances,
- per-vault path resolvers,
- explicit service lifecycle per mounted vault.
