"""Deprecated compatibility entrypoint for instance-local vault registry state.

Production code imports :mod:`app.instance.vault_registry`. External/test callers
may keep this path during the bounded MVR migration.
"""

from app.instance.vault_registry import (
    APP_LOCAL_SCHEMA,
    AppLocalSettings,
    AppLocalSettingsStore,
    KnownVaultRef,
    default_app_local_settings_path,
)

__all__ = [
    "APP_LOCAL_SCHEMA",
    "AppLocalSettings",
    "AppLocalSettingsStore",
    "KnownVaultRef",
    "default_app_local_settings_path",
]
