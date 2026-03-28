from __future__ import annotations

from pathlib import Path

import yaml

from app.ingest.config import resolve_ingest_config


def _write_system_settings(vault_root: Path) -> None:
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


def test_ingest_override_merges_settings(tmp_path: Path) -> None:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    _write_system_settings(vault_root)

    override_path = vault_root / "⚙️ System" / "settings" / "ingest.override.md"
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(
        """---\ninclude_folders:\n  - "📥 Inbox"\nignore_glob:\n  - "Legacy/**"\n---\n\nOverride settings for ingest.\n""",
        encoding="utf-8",
    )

    config = resolve_ingest_config(vault_root)

    assert config.include_folders == ["📥 Inbox"]
    assert "Legacy/**" in config.ignore_glob
    for pattern in [".obsidian/**", ".trash/**", "_system/companions/**"]:
        assert pattern in config.ignore_glob
    assert "⚙️ System/**" not in config.ignore_glob
    assert "⚙️ System/vault.layout.md" not in config.ignore_glob
