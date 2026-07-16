from __future__ import annotations

from pathlib import Path

from app.instance.vault_registry import CURRENT_REGISTRY_SCHEMA, VaultRegistryStore, preflight_registry_payload


def test_production_registry_imports_use_instance_package() -> None:
    offenders = []
    for path in Path("app").rglob("*.py"):
        if path.as_posix() == "app/vault/app_local.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "app.vault.app_local" in text:
            offenders.append(path.as_posix())
    assert offenders == []
    compatibility = Path("app/vault/app_local.py").read_text(encoding="utf-8")
    assert "from app.instance.vault_registry import" in compatibility


def test_registry_schema_producers_match_runtime_precondition(tmp_path) -> None:
    path = tmp_path / "vault-registry.md"
    snapshot = VaultRegistryStore(path).load()
    assert snapshot.schema == CURRENT_REGISTRY_SCHEMA
    assert preflight_registry_payload(path).schema == CURRENT_REGISTRY_SCHEMA

    legacy = tmp_path / "legacy.md"
    legacy.write_text(
        "---\nschema: design-handoff.app-local.v1\nappInstallId: app-fixture\nknownVaults: {}\n---\n",
        encoding="utf-8",
    )
    assert VaultRegistryStore(legacy).load_or_migrate().schema == CURRENT_REGISTRY_SCHEMA
    assert preflight_registry_payload(legacy).schema == CURRENT_REGISTRY_SCHEMA
