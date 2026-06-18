from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from app.vault.markdown_settings import MarkdownSettingsStore


APP_LOCAL_SCHEMA = "design-handoff.app-local.v1"

_APP_DIR_NAME = "Agentic PKM"
_SETTINGS_FILENAME = "app-local.md"
# Repo-consistent, container-safe writable runtime dir. The dev/worker/watcher
# services bind-mount the repo at /app and pre-create /app/tmp (see
# docker-compose.yaml), so this is writable even when the container runs as a
# host UID/GID with no passwd entry.
_CONTAINER_RUNTIME_DIR = Path("/app/tmp")


def _can_host(directory: Path) -> bool:
    """True if `directory` is (or can be created as) a writable directory.

    Walks up to the nearest existing ancestor: the directory is hostable when
    that ancestor is a writable directory, so a later ``mkdir(parents=True)``
    will succeed.
    """
    probe = directory
    while True:
        if probe.exists():
            return probe.is_dir() and os.access(probe, os.W_OK)
        parent = probe.parent
        if parent == probe:
            return False
        probe = parent


def _usable_home() -> Path | None:
    """Return a usable home directory, or None when home is unusable.

    Unusable means: HOME unset and no passwd entry, or home resolves to the
    filesystem root ("/"), which happens for a hostless container UID.
    """
    home_env = os.getenv("HOME", "").strip()
    if home_env:
        candidate = Path(home_env)
    else:
        try:
            candidate = Path.home()
        except (RuntimeError, OSError):
            return None
    # A bare root anchor ("/") is not a usable home for app-local state.
    if str(candidate) == candidate.anchor:
        return None
    return candidate


def default_app_local_settings_path() -> Path:
    override = os.getenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", "").strip()
    if override:
        return Path(override).expanduser()

    # Prefer an explicit XDG data home when set and writable.
    xdg = os.getenv("XDG_DATA_HOME", "").strip()
    if xdg:
        base = Path(xdg).expanduser() / _APP_DIR_NAME
        if _can_host(base):
            return base / _SETTINGS_FILENAME

    # Standard host location (macOS dev host, prod-as-root with HOME=/root).
    home = _usable_home()
    if home is not None:
        base = home / "Library" / "Application Support" / _APP_DIR_NAME
        if _can_host(base):
            return base / _SETTINGS_FILENAME

    # Hostless container UID / unwritable HOME: fall back to a writable runtime
    # dir rather than crashing on an unwritable /Library path.
    base = _CONTAINER_RUNTIME_DIR / "agentic-pkm"
    if _can_host(base):
        return base / _SETTINGS_FILENAME

    return Path(tempfile.gettempdir()) / "agentic-pkm" / _SETTINGS_FILENAME


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
