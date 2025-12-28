from __future__ import annotations

from pathlib import Path

import yaml

from app.ingest.vault_alpha import run_vault_alpha_ingest
from app.retrieval.hybrid import get_store
from app.stores import reset_store_backends


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
            "ignore_glob": ["_system/**"],
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


def test_default_include_folders_scans_root(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MOCK_RESPONSE", "Mock response")

    reset_store_backends()
    get_store().set_documents([])

    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    (vault_root / "RootNote.md").write_text("Root note body", encoding="utf-8")
    _write_system_settings(vault_root)

    summary = run_vault_alpha_ingest(vault_root, max_notes=10, include_test_note=False, force=True)

    assert summary.included_folders == ["."]
    assert summary.scanned >= 1
    assert summary.ingested >= 1
