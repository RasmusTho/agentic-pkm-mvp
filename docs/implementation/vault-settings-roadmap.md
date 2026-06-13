State: Implementation roadmap for the vault selector and Markdown settings foundation.
Doc role: Plan / roadmap
Authority: Tracks remaining work derived from `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md`. GitHub Issues are the executable task contracts when available.
Owner: Runtime / Companion UI / configuration
Last reviewed: 2026-06-12

# Vault Selector and Settings Roadmap

## Source Anchors

- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md :: Purpose`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md :: VaultStatus`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md :: VaultContext`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md :: Initial Vault Files`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md :: Service Gating`
- `docs/CONCEPTS/VAULT_AND_SETTINGS_CONTEXT.md :: Companion UI Behavior`

## Completed In This Foundation

- Added the architecture contract for no-vault startup, `VaultStatus`, `VaultContext`, scoped Markdown settings, identity separation, role structure, service gating, and Companion UI states.
- Added a roadmap that keeps remaining work out of chat-only memory.
- Added or planned code support for central vault context, vault initialization, app-local known-vault registry, Markdown settings parsing/writing, and basic service gating.
- Added the scoped `SettingsService` / `SettingsRegistry` foundation for built-in defaults, app-local keys, vault-shared settings, vault-local settings, runtime overrides, source reporting, and safe validation errors. Broader legacy-setting extraction remains a later slice.

## Migration Notes

- Existing environment-scoped defaults (`VAULT_ROOT`, `VAULT_ROOT_DEV`, `VAULT_ROOT_TEST`, `PKM_ENVIRONMENT`) remain compatibility inputs.
- A configured/default path that exists but lacks `settings/vault.md` is `uninitialized`, not a startup failure.
- A missing stored path is `missing`; app-local registry repair should update the path without deleting legacy config.
- Existing `_system/settings/system-settings.yaml` and `@Settings/system-settings.yaml` remain compatibility settings until extraction issues move project behavior into the new Markdown settings files.

## Test Strategy

- Unit tests for `VaultManager`: no-vault, missing path, uninitialized path, initialization, selected path, conflicted/invalid settings.
- Unit tests for Markdown settings: frontmatter parse, conflict marker detection, body preservation, stable output, `.gitignore` creation.
- Unit tests for app-local settings registry: app install ID, known vaults keyed by path/ref rather than only `vaultId`, last active vault.
- Service-gating tests for watchers/indexers/writers where the code path is touched.
- Companion UI tests for no-vault, selected, uninitialized, missing, and invalid projections as UI integration lands.

## Remaining Issues

### Epic: Vault selector and Markdown settings foundation

Goal: implement a system-wide vault selector and settings architecture. The app must start without an active vault, and vault-dependent services must only run when a valid active vault exists.

Definition of done:

- App can run with no selected vault.
- Companion UI can select and initialize vaults.
- `VaultContext` is central and system-wide.
- Vault-dependent services are gated by `VaultStatus` and permissions.
- Settings are loaded through a central service.
- Human-readable Markdown settings files exist in the vault settings folder.
- Local clone settings are Git-ignored.
- Companion UI writes to the same settings files Obsidian can edit.
- Hardcoded configurable values are extracted into settings where appropriate.
- Central/satellite/read-only roles are represented and enforced where relevant.

### Add no-vault startup mode and central VaultContext

Scope:

- Add `VaultStatus`: `none`, `selected`, `missing`, `invalid`, `uninitialized`.
- Add `VaultContext`.
- Add `VaultManager` or equivalent service.
- Ensure app startup does not require a vault.
- Ensure Companion UI can render in no-vault mode.
- Gate vault-dependent services.

Acceptance criteria:

- App starts with `VaultStatus.none` when no vault is configured. Verify: `tests/vault/test_vault_manager.py::test_initial_context_is_none_without_config`.
- Selecting a missing path gives `VaultStatus.missing`. Verify: `tests/vault/test_vault_manager.py::test_select_missing_path_gives_missing`.
- Selecting a folder without Design Handoff settings gives `VaultStatus.uninitialized`. Verify: `tests/vault/test_vault_manager.py::test_select_existing_uninitialized_folder`.
- Vault-dependent watchers/indexers/writers do not start in no-vault mode. Verify: `tests/vault/test_vault_service_gating.py::test_vault_dependent_services_are_gated_without_selected_vault`.

### Add vault initialization with Markdown settings files

Scope:

- Create `settings/`.
- Create `vault.md`, `paths.md`, `workflow.md`, `design-handoff.md`, `companion-ui.md`, `local.md`, `.gitignore`.
- Use Markdown files with YAML frontmatter.
- Do not overwrite existing files unsafely.
- Mark uninitialized vaults clearly.

Acceptance criteria:

- Existing Obsidian vault without Design Handoff settings is marked uninitialized. Verify: `tests/vault/test_vault_manager.py::test_select_existing_uninitialized_folder`.
- Initialization creates all required settings files. Verify: `tests/vault/test_vault_initialization.py::test_initialize_vault_creates_expected_settings_files`.
- `local.md` and `*.local.md` are Git-ignored. Verify: `tests/vault/test_vault_initialization.py::test_initialize_vault_creates_local_settings_gitignore`.

### Add app-local known vault registry and recent vault handling

Scope:

- Add app-local settings store or integrate equivalent.
- Store `appInstallId`.
- Store known vault refs.
- Store last active vault ref.
- Support missing/moved vault repair.
- Support same logical vault cloned twice by distinguishing `vaultId` from `localInstanceId` and path.

Acceptance criteria:

- Recent vaults can be listed from app-local settings. Verify: `tests/vault/test_app_local_settings.py::test_known_vault_registry_round_trips`.
- Missing paths are represented without crashing. Verify: `tests/vault/test_app_local_settings.py::test_missing_known_vault_path_is_preserved_for_repair`.
- Same `vaultId` at multiple paths does not collapse into one entry. Verify: `tests/vault/test_app_local_settings.py::test_same_vault_id_at_multiple_paths_keeps_separate_refs`.

### Add scoped SettingsService and SettingsRegistry

Scope:

- Shipped foundation: built-in defaults, app-local settings, vault-shared settings, vault-local settings, runtime overrides, setting definitions, source tracking, and validation errors.
- Remaining downstream work: wire additional runtime consumers into the service and extract legacy settings incrementally.

Acceptance criteria:

- Missing settings fall back to defaults. Verify: `tests/settings/test_scoped_settings_service.py::test_missing_settings_fall_back_to_defaults`.
- Invalid settings do not crash the app. Verify: `tests/settings/test_scoped_settings_service.py::test_invalid_settings_returns_validation_error_and_defaults`.
- Effective settings can report source file/scope. Verify: `tests/settings/test_scoped_settings_service.py::test_effective_settings_report_sources`.
- Vault-local settings override vault-shared settings. Verify: `tests/settings/test_scoped_settings_service.py::test_vault_local_settings_override_shared_settings`.

### Expose vault selection and settings in Companion UI

Scope:

- No-vault screen.
- Open existing vault.
- Create/init new vault.
- Initialize existing uninitialized vault.
- Change vault.
- Open settings folder.
- Reload settings.
- Display validation errors.
- Show machine role and write permissions.
- Edit supported settings and write to Markdown settings files.

Acceptance criteria:

- UI works with no active vault. Verify: `tests/companion_ui/test_vault_selector_states.py::test_no_vault_state_renders`.
- UI shows selected/missing/invalid/uninitialized states. Verify: `tests/companion_ui/test_vault_selector_states.py::test_vault_status_states_render`.
- UI writes settings to the correct scope. Verify: `tests/companion_ui/test_vault_settings_editor.py::test_companion_writes_markdown_settings_scope`.
- UI respects satellite/read-only restrictions. Verify: `tests/companion_ui/test_vault_settings_editor.py::test_settings_editor_respects_role_permissions`.

### Extract configurable hardcoded values into settings

Scope:

- Folder names.
- Template paths.
- Archive paths.
- Workflow statuses.
- Feature flags.
- Watcher/indexing behavior.
- Import/export paths.
- UI defaults.
- Metadata conventions.

Acceptance criteria:

- Vault-dependent paths are resolved through `VaultContext` and settings. Verify: `tests/settings/test_paths_resolver.py::test_vault_paths_resolve_from_vault_context_settings`.
- Changing settings affects all relevant subsystems consistently. Verify: `tests/settings/test_scoped_settings_service.py::test_settings_change_updates_path_resolver`.
- No subsystem has its own independent hardcoded vault path for user-configurable vault behavior. Verify: `tests/architecture/test_no_hardcoded_vault_paths.py::test_user_configurable_vault_paths_use_context`.

### Add primary/satellite/read-only/automation role behavior

Scope:

- `machineRole` in local settings.
- `syncRole` in local settings.
- `allowWritesToVault`.
- `allowSharedSettingsEdits`.
- `allowLocalSettingsEdits`.
- `enableVaultWatcher`.
- `enableAutoIndexing`.
- Companion UI role display.
- Service gating by role.

Acceptance criteria:

- `readOnlySatellite` cannot write vault project files. Verify: `tests/vault/test_vault_service_gating.py::test_read_only_satellite_blocks_vault_writes`.
- Satellite can be configured to edit local settings only. Verify: `tests/vault/test_vault_service_gating.py::test_satellite_can_allow_local_only_settings_edits`.
- `automationNode` can run without UI if configured. Verify: `tests/vault/test_vault_service_gating.py::test_automation_node_can_run_background_services_when_enabled`.

### Support external Obsidian settings edits and validation recovery

Scope:

- Detect settings file changes if watcher infrastructure exists.
- Add reload settings action.
- Preserve Markdown body when Companion UI writes.
- Detect invalid YAML/frontmatter.
- Detect Git conflict markers.
- Keep last valid settings or safe defaults on invalid settings.
- Show validation errors.

Acceptance criteria:

- Manual settings edits are reflected after reload/watch. Verify: `tests/settings/test_scoped_settings_service.py::test_reload_reflects_external_markdown_edit`.
- Invalid settings do not crash the app. Verify: `tests/settings/test_scoped_settings_service.py::test_invalid_settings_returns_validation_error_and_defaults`.
- Git conflict markers are reported clearly. Verify: `tests/vault/test_vault_manager.py::test_conflicted_settings_mark_vault_invalid`.
