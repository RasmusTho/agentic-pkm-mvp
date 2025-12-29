from __future__ import annotations

from pathlib import Path

import yaml

from app.ingest.config import resolve_ingest_config


def test_ingest_defaults_use_layout_note(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    layout_dir = vault_root / "⚙️ System"
    layout_dir.mkdir(parents=True)
    layout_path = layout_dir / "vault.layout.md"
    layout_path.write_text(
        """---\ninclude_folders:\n  - "📥 Inbox"\n  - "🛠️ Workbench"\nignore_glob:\n  - "Legacy/**"\nsystem_folder: "⚙️ System"\n---\n\nLayout note.\n""",
        encoding="utf-8",
    )

    config = resolve_ingest_config(vault_root)

    assert config.include_folders == ["📥 Inbox", "🛠️ Workbench"]
    assert "Legacy/**" in config.ignore_glob
    assert ".obsidian/**" in config.ignore_glob
    assert ".trash/**" in config.ignore_glob
    assert "System/Metadata/VaultMirror/**" in config.ignore_glob
    assert "⚙️ System/**" not in config.ignore_glob
    assert "⚙️ System/vault.layout.md" not in config.ignore_glob


def _write_system_settings(vault_root: Path, include_folders: list[str]) -> None:
    settings_dir = vault_root / "_system" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    settings = {
        "uuid": "TEST-SETTINGS",
        "title": "Test Settings",
        "version": "0.0.0",
        "runtime": {
            "environment": "dev",
            "database_url": "postgresql://app:app@localhost:5432/app",
            "enable_outbox": True,
            "enable_tracing": False,
        },
        "ingest": {
            "active_vault_path": str(vault_root),
            "file_glob": ["**/*.md"],
            "ignore_glob": [],
            "include_folders": include_folders,
            "write_policy": "write_on_diff",
        },
        "index": {
            "bm25_enabled": True,
            "vector_enabled": False,
            "embedding_model": "mock",
            "min_confidence": 0.1,
            "rules": [],
        },
        "sync": {"debounce_ms": 1, "inactive_grace_s": 1},
        "observability": {
            "otlp_endpoint": "http://localhost:4318",
            "jaeger_ui": "http://localhost:16686",
            "trace_level": "info",
        },
        "events": {"catalog_path": "vault/_system/events/catalog.yaml", "sla_outbox_to_index_ms": 1000},
    }
    path = settings_dir / "system-settings.yaml"
    path.write_text(yaml.safe_dump(settings, sort_keys=False), encoding="utf-8")


def test_ingest_missing_include_folders_falls_back(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    layout_dir = vault_root / "⚙️ System"
    layout_dir.mkdir(parents=True)
    layout_path = layout_dir / "vault.layout.md"
    layout_path.write_text(
        """---\nignore_glob:\n  - "Legacy/**"\nsystem_folder: "⚙️ System"\n---\n\nLayout note.\n""",
        encoding="utf-8",
    )

    config = resolve_ingest_config(vault_root)

    assert config.include_folders == ["📥 Inbox", "🛠️ Workbench"]


def test_ingest_layout_overrides_settings_include(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_system_settings(vault_root, include_folders=["📥 Inbox"])
    layout_dir = vault_root / "⚙️ System"
    layout_dir.mkdir(parents=True)
    layout_path = layout_dir / "vault.layout.md"
    layout_path.write_text(
        """---\ninclude_folders:\n  - "."\nsystem_folder: "⚙️ System"\n---\n\nLayout note.\n""",
        encoding="utf-8",
    )

    config = resolve_ingest_config(vault_root)

    assert config.include_folders == ["."]
