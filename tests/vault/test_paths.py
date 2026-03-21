from __future__ import annotations

from pathlib import Path

import pytest

from app.vault.paths import (
    get_vault_inbox_dir_rel,
    get_vault_runtime_dir_rel,
    get_vault_system_dir_rel,
)

pytestmark = pytest.mark.not_pg


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
