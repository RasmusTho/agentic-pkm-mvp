from __future__ import annotations

from pathlib import Path

import pytest

from app.vault.app_local import AppLocalSettingsStore
from app.vault.manager import VaultManager
from app.vault.paths import (
    NoVaultSelectedError,
    VaultPathResolutionError,
    VaultPathResolver,
    get_vault_inbox_dir_rel,
    get_vault_runtime_dir_rel,
    get_vault_system_dir_rel,
    resolve_vault_system_dir_rel_or_default,
)

pytestmark = pytest.mark.not_pg


def test_vault_path_helpers_do_not_fallback_to_cwd_vault(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Vault path helpers must not synthesize Path("vault") for no-vault callers.

    Slice 05B (#2384): with no vault selected (``VAULT_ROOT`` unset and no
    explicit ``vault_root``) the shared resolver raises ``NoVaultSelectedError``
    instead of silently resolving the CWD-relative ``./vault``. Nothing is read
    from or created under the current working directory.
    """
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_RUNTIME_DIR_REL", raising=False)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(NoVaultSelectedError):
        get_vault_inbox_dir_rel(None)
    with pytest.raises(NoVaultSelectedError):
        get_vault_system_dir_rel(None)
    with pytest.raises(NoVaultSelectedError):
        get_vault_runtime_dir_rel(None)
    with pytest.raises(NoVaultSelectedError):
        resolve_vault_system_dir_rel_or_default(None)

    assert not (tmp_path / "vault").exists()


def test_vault_path_helpers_set_but_missing_stay_loud(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A set-but-missing VAULT_ROOT remains a loud misconfiguration, not no-vault."""
    from app.config.paths import VaultRootMisconfiguredError

    missing = tmp_path / "missing-vault"
    monkeypatch.setenv("VAULT_ROOT", str(missing))
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)

    with pytest.raises(VaultRootMisconfiguredError):
        get_vault_inbox_dir_rel(None)


def _write_settings(
    vault_root: Path,
    *,
    inbox: str,
    runtime: str,
    system: str,
    include_paths: bool = True,
    include_top_level: bool = False,
) -> None:
    settings_dir = vault_root / "_system" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "uuid: TEST",
        "title: System Settings (Canonical)",
        "version: 0.3.0",
        "runtime:",
        "  environment: dev",
        "  database_url: postgresql://app:app@localhost:15432/app",
        "  enable_outbox: true",
        "  enable_tracing: true",
    ]
    if include_paths:
        lines.extend(
            [
                "paths:",
                f"  inbox_dir_rel: {inbox}",
                f"  runtime_dir_rel: {runtime}",
                f"  system_dir_rel: {system}",
            ]
        )
    if include_top_level:
        lines.extend(
            [
                f"inbox_dir_rel: {inbox}",
                f"runtime_dir_rel: {runtime}",
                f"system_dir_rel: {system}",
            ]
        )
    lines.extend(
        [
            "ingest:",
            "  active_vault_path: vault",
            "  file_glob:",
            "  - '**/*.md'",
            "  ignore_glob:",
            "  - _system/**",
            "  write_policy: write_on_diff",
            "index:",
            "  bm25_enabled: true",
            "  vector_enabled: true",
            "  embedding_model: deterministic-1536",
            "  min_confidence: 0.15",
            "  rules: []",
            "sync:",
            "  debounce_ms: 1200",
            "  inactive_grace_s: 5",
            "observability:",
            "  otlp_endpoint: http://localhost:4318",
            "  jaeger_ui: http://localhost:16686",
            "  trace_level: info",
            "events:",
            "  catalog_path: vault/_system/events/catalog.yaml",
            "  sla_outbox_to_index_ms: 2000",
        ]
    )
    (settings_dir / "system-settings.yaml").write_text("\n".join(lines), encoding="utf-8")


def test_paths_defaults_without_settings(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_RUNTIME_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)

    with pytest.raises(FileNotFoundError):
        get_vault_inbox_dir_rel(tmp_path)
    with pytest.raises(FileNotFoundError):
        get_vault_runtime_dir_rel(tmp_path)
    with pytest.raises(FileNotFoundError):
        get_vault_system_dir_rel(tmp_path)


def test_paths_use_settings_when_present(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_RUNTIME_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)

    _write_settings(tmp_path, inbox="MyInbox", runtime="System/Runtime/Alpha", system="System")

    assert get_vault_inbox_dir_rel(tmp_path) == "MyInbox"
    assert get_vault_runtime_dir_rel(tmp_path) == "System/Runtime/Alpha"
    assert get_vault_system_dir_rel(tmp_path) == "System"


def test_paths_use_top_level_when_paths_missing(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_RUNTIME_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)

    _write_settings(
        tmp_path,
        inbox="LegacyInbox",
        runtime="System/Runtime/Legacy",
        system="System",
        include_paths=False,
        include_top_level=True,
    )

    assert get_vault_inbox_dir_rel(tmp_path) == "LegacyInbox"
    assert get_vault_runtime_dir_rel(tmp_path) == "System/Runtime/Legacy"
    assert get_vault_system_dir_rel(tmp_path) == "System"


def test_paths_prefer_paths_block_over_top_level(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_RUNTIME_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)

    _write_settings(
        tmp_path,
        inbox="CanonicalInbox",
        runtime="System/Runtime/Canonical",
        system="System",
        include_paths=True,
        include_top_level=True,
    )

    assert get_vault_inbox_dir_rel(tmp_path) == "CanonicalInbox"
    assert get_vault_runtime_dir_rel(tmp_path) == "System/Runtime/Canonical"
    assert get_vault_system_dir_rel(tmp_path) == "System"


def test_paths_env_overrides_settings(monkeypatch, tmp_path: Path) -> None:
    _write_settings(tmp_path, inbox="MyInbox", runtime="System/Runtime/Alpha", system="System")

    monkeypatch.setenv("VAULT_INBOX_DIR_REL", "EnvInbox")
    monkeypatch.setenv("VAULT_RUNTIME_DIR_REL", "EnvRuntime")
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "EnvSystem")

    assert get_vault_inbox_dir_rel(tmp_path) == "EnvInbox"
    assert get_vault_runtime_dir_rel(tmp_path) == "EnvRuntime"
    assert get_vault_system_dir_rel(tmp_path) == "EnvSystem"


def test_paths_use_at_settings_when_present(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_RUNTIME_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)

    settings_dir = tmp_path / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "system-settings.yaml").write_text(
        "\n".join(
            [
                "paths:",
                "  inbox_dir_rel: 📥 Inbox",
                "  runtime_dir_rel: ⚙️ System/Runtime/Alpha",
                "  system_dir_rel: ⚙️ System",
            ]
        ),
        encoding="utf-8",
    )

    assert get_vault_inbox_dir_rel(tmp_path) == "📥 Inbox"
    assert get_vault_runtime_dir_rel(tmp_path) == "⚙️ System/Runtime/Alpha"
    assert get_vault_system_dir_rel(tmp_path) == "⚙️ System"


def test_paths_do_not_fallback_to_other_vault_settings(monkeypatch, tmp_path: Path) -> None:
    target_vault = tmp_path / "target-vault"
    target_vault.mkdir()

    ygg_root = tmp_path / "Yggdrasil"
    settings_dir = ygg_root / "Mimer" / "@Settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    (settings_dir / "system-settings.yaml").write_text(
        "\n".join(
            [
                "paths:",
                "  inbox_dir_rel: 📥 Inbox",
                "  runtime_dir_rel: ⚙️ System/Runtime/Alpha",
                "  system_dir_rel: ⚙️ System",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("YGGDRASIL_ROOT", str(ygg_root))
    monkeypatch.delenv("VAULT_INBOX_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_RUNTIME_DIR_REL", raising=False)
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)

    with pytest.raises(FileNotFoundError):
        get_vault_inbox_dir_rel(target_vault)
    with pytest.raises(FileNotFoundError):
        get_vault_runtime_dir_rel(target_vault)
    with pytest.raises(FileNotFoundError):
        get_vault_system_dir_rel(target_vault)


def _write_layout_note(path: Path, *, system_folder: str, inbox_folder: str = "Inbox") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        f"system_folder: {system_folder}\n"
        f"inbox_folder: {inbox_folder}\n"
        "desk_folder: Desk\n"
        "---\n",
        encoding="utf-8",
    )


def test_system_dir_default_only_handles_missing_layout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)

    assert resolve_vault_system_dir_rel_or_default(tmp_path) == "⚙️ System"


def test_system_dir_default_does_not_mask_ambiguous_layout_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("VAULT_SYSTEM_DIR_REL", raising=False)

    _write_layout_note(tmp_path / "A" / "vault.layout.md", system_folder="A")
    _write_layout_note(tmp_path / "B" / "vault.layout.md", system_folder="B")

    with pytest.raises(ValueError, match="Multiple vault.layout.md"):
        resolve_vault_system_dir_rel_or_default(tmp_path)


def _init_vault_with_handoff(vault_root: Path, handoff: str) -> "VaultManager":
    settings_dir = vault_root / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)

    def write(name: str, content: str) -> None:
        (settings_dir / name).write_text(content, encoding="utf-8")

    write(
        "vault.md",
        "---\nschema: design-handoff.vault.v1\nscope: vault-shared\nvaultId: v\nvaultName: X\n---\n",
    )
    write(
        "paths.md",
        "---\nscope: vault-shared\n"
        f"handoffFolder: {handoff}\n"
        "assetsFolder: Design Handoff/Assets\n"
        "templatesFolder: Design Handoff/Templates\n"
        "archiveFolder: Design Handoff/Archive\n---\n",
    )
    write("workflow.md", "---\nscope: vault-shared\n---\n")
    write("design-handoff.md", "---\nscope: vault-shared\n---\n")
    write("companion-ui.md", "---\nscope: vault-shared\n---\n")
    write(
        "local.md",
        "---\nschema: design-handoff.local.v1\nscope: vault-local\nlocalInstanceId: l1\nmachineRole: primary\n---\n",
    )
    manager = VaultManager(app_local_store=AppLocalSettingsStore(path=vault_root.parent / "app-local.md"))
    return manager


def test_rejects_parent_traversal(tmp_path: Path) -> None:
    """A vault-relative path with parent traversal that resolves outside the
    selected vault must be rejected, not silently resolved to a sibling dir."""
    vault_root = tmp_path / "vault"
    manager = _init_vault_with_handoff(vault_root, "../OtherProject")
    context = manager.select_vault(vault_root, remember=False)
    assert context.status == "selected"

    with pytest.raises(VaultPathResolutionError):
        VaultPathResolver().resolve(context)


def test_allows_legitimate_relative_paths(tmp_path: Path) -> None:
    """Regression guard: ordinary vault-relative subpaths still resolve inside the vault."""
    vault_root = tmp_path / "vault"
    manager = _init_vault_with_handoff(vault_root, "Design Handoff")
    context = manager.select_vault(vault_root, remember=False)

    resolved = VaultPathResolver().resolve(context)
    assert resolved.handoff_dir == (vault_root / "Design Handoff")
