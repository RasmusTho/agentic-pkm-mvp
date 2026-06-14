from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from app.vault.markdown_settings import MarkdownSettingsStore


APP_LOCAL_SCHEMA = "design-handoff.app-local.v1"


def default_app_local_settings_path() -> Path:
    override = os.getenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Application Support" / "Agentic PKM" / "app-local.md"


@dataclass(frozen=True)
class KnownVaultRef:
    ref: str
    path: str
    vault_id: str | None = None
    vault_name: str | None = None
    local_instance_id: str | None = None
    last_opened_at: str | None = None


@dataclass
class AppLocalSettings:
    app_install_id: str
    last_active_vault_ref: str | None = None
    known_vaults: dict[str, KnownVaultRef] = field(default_factory=dict)


class AppLocalSettingsStore:
    def __init__(self, path: Path | None = None, markdown_store: MarkdownSettingsStore | None = None) -> None:
        self.path = path or default_app_local_settings_path()
        self.markdown_store = markdown_store or MarkdownSettingsStore()

    def load(self) -> AppLocalSettings:
        if not self.path.exists():
            settings = AppLocalSettings(app_install_id=f"app-{uuid4()}")
            self.save(settings)
            return settings

        doc = self.markdown_store.read(self.path)
        raw_known = doc.frontmatter.get("knownVaults") or {}
        known: dict[str, KnownVaultRef] = {}
        if isinstance(raw_known, dict):
            for ref, value in raw_known.items():
                if not isinstance(value, dict):
                    continue
                path = str(value.get("path") or "").strip()
                if not path:
                    continue
                known[str(ref)] = KnownVaultRef(
                    ref=str(ref),
                    path=path,
                    vault_id=_optional_str(value.get("vaultId")),
                    vault_name=_optional_str(value.get("vaultName")),
                    local_instance_id=_optional_str(value.get("localInstanceId")),
                    last_opened_at=_optional_str(value.get("lastOpenedAt")),
                )
        install_id = str(doc.frontmatter.get("appInstallId") or "").strip() or f"app-{uuid4()}"
        return AppLocalSettings(
            app_install_id=install_id,
            last_active_vault_ref=_optional_str(doc.frontmatter.get("lastActiveVaultRef")),
            known_vaults=known,
        )

    def save(self, settings: AppLocalSettings) -> None:
        known = {
            ref: {
                "path": item.path,
                "vaultId": item.vault_id,
                "vaultName": item.vault_name,
                "localInstanceId": item.local_instance_id,
                "lastOpenedAt": item.last_opened_at,
            }
            for ref, item in sorted(settings.known_vaults.items())
        }
        self.markdown_store.write_frontmatter(
            self.path,
            {
                "schema": APP_LOCAL_SCHEMA,
                "scope": "app-local",
                "appInstallId": settings.app_install_id,
                "lastActiveVaultRef": settings.last_active_vault_ref,
                "knownVaults": known,
            },
            body=(
                "# App Local Settings\n"
                "This file stores local application preferences and recently used vaults.\n"
                "It does not define project behavior.\n"
            ),
        )

    def upsert_known_vault(self, item: KnownVaultRef, *, make_active: bool = True) -> AppLocalSettings:
        settings = self.load()
        settings.known_vaults[item.ref] = item
        if make_active:
            settings.last_active_vault_ref = item.ref
        self.save(settings)
        return settings


def _optional_str(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


__all__ = [
    "APP_LOCAL_SCHEMA",
    "AppLocalSettings",
    "AppLocalSettingsStore",
    "KnownVaultRef",
    "default_app_local_settings_path",
]
