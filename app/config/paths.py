from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from app.config.environment import active_environment


@dataclass(frozen=True)
class ResolvedPaths:
    vault_root: Path
    yggdrasil_root: Optional[Path]
    system_settings_path: Optional[Path]
    environment: Literal["dev", "prod", "test"] = "prod"


_DEFAULT_VAULT = Path("vault")


class VaultRootMisconfiguredError(RuntimeError):
    """Raised when an explicitly configured vault root cannot be used."""

    def __init__(self, env_var: str, configured_path: Path) -> None:
        self.env_var = env_var
        self.configured_path = configured_path
        super().__init__(
            f"{env_var} is set to a missing vault root: {configured_path}"
        )


def _clean_path(value: str | Path | None) -> Optional[Path]:
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    value = value.strip()
    return Path(value) if value else None


def resolve_vault_root(cli_override: Path | None = None, *, environment: Literal["dev", "prod", "test"] | None = None) -> Path:
    """Resolve vault root path, optionally scoped to environment.

    Args:
        cli_override: Explicit override (takes precedence)
        environment: If 'dev' or 'test', appends matching suffix; if 'prod' or None, uses base path

    Returns:
        Vault root path, environment-scoped if requested
    """
    if cli_override is not None:
        return Path(cli_override)

    env_root = _clean_path(os.getenv("VAULT_ROOT"))
    if environment == "dev":
        env_specific = _clean_path(os.getenv("VAULT_ROOT_DEV"))
    elif environment == "test":
        env_specific = _clean_path(os.getenv("VAULT_ROOT_TEST"))
    else:
        env_specific = None

    if env_specific is not None:
        if not env_specific.exists():
            env_var = (
                "VAULT_ROOT_DEV"
                if environment == "dev"
                else "VAULT_ROOT_TEST"
            )
            raise VaultRootMisconfiguredError(env_var, env_specific)
        return env_specific

    if env_root is not None:
        if not env_root.exists():
            raise VaultRootMisconfiguredError("VAULT_ROOT", env_root)
        base = env_root
    else:
        base = _DEFAULT_VAULT

    if environment == "dev":
        return base.parent / f"{base.name}-dev"
    if environment == "test":
        return base.parent / f"{base.name}-test"

    return base


def resolve_yggdrasil_root() -> Optional[Path]:
    env_root = _clean_path(os.getenv("YGGDRASIL_ROOT"))
    if env_root:
        return env_root
    home_default = Path.home() / "Yggdrasil"
    return home_default if home_default.exists() else None


def _candidate_settings_paths(vault_root: Path | None, yggdrasil_root: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if vault_root is not None:
        candidates.append(vault_root / "_system" / "settings" / "system-settings.yaml")
        candidates.append(vault_root / "@Settings" / "system-settings.yaml")
    if yggdrasil_root is not None:
        mimer_root = yggdrasil_root / "Mimer"
        candidates.append(mimer_root / "@Settings" / "system-settings.yaml")
    return candidates


def resolve_system_settings_path(
    *,
    explicit: Path | None = None,
    vault_root: Path | None = None,
    yggdrasil_root: Path | None = None,
) -> Optional[Path]:
    if explicit is not None:
        return Path(explicit)
    env_override = _clean_path(os.getenv("SETTINGS_PATH"))
    if env_override is not None:
        return env_override

    vault = resolve_vault_root(vault_root)
    ygg = yggdrasil_root or resolve_yggdrasil_root()

    for candidate in _candidate_settings_paths(vault, ygg):
        if candidate.exists():
            return candidate

    return vault / "_system" / "settings" / "system-settings.yaml"


def resolve_flow_settings_path(path: Path | None = None, vault_root: Path | None = None) -> Optional[Path]:
    if path is not None:
        return Path(path)
    env_path = _clean_path(os.getenv("FLOW_SETTINGS_PATH"))
    if env_path is not None:
        return env_path
    vault = resolve_vault_root(vault_root)
    default_path = vault / "_system" / "settings" / "flows.settings.yaml"
    if default_path.exists():
        return default_path
    fallback = Path("docs/settings/flows.settings.yaml")
    if fallback.exists():
        return fallback
    return default_path


def resolve_runtime_artifact_path(
    artifact_path: Path | str,
    *,
    environment: Literal["dev", "prod", "test"] | None = None,
) -> Path:
    """Resolve a runtime artifact path, optionally scoped to environment.

    For dev environment, artifacts go into 'tmp-dev/' subdirectories.
    For test environment, artifacts go into 'tmp-test/' subdirectories.
    For prod or unspecified, uses the base path.

    Args:
        artifact_path: Base artifact path (e.g., Path('tmp/index-outbox.jsonl'))
        environment: If 'dev' or 'test', paths resolve to environment-scoped location

    Returns:
        Environment-scoped artifact path
    """
    base = Path(artifact_path)

    if environment in ("dev", "test"):
        suffix = environment
        parent = base.parent
        name = base.name
        if parent == Path("tmp"):
            return Path(f"tmp-{suffix}") / name
        suffixed_parent_name = f"{parent.name}-{suffix}" if parent.name else f"tmp-{suffix}"
        return parent.parent / suffixed_parent_name / name if parent.parent != Path(".") else Path(suffixed_parent_name) / name

    return base


def resolve_paths(
    *,
    vault_root: Path | None = None,
    settings_path: Path | None = None,
    yggdrasil_root: Path | None = None,
    environment: Literal["dev", "prod", "test"] | None = None,
) -> ResolvedPaths:
    env = environment or active_environment()
    vault = resolve_vault_root(vault_root, environment=env)
    ygg = yggdrasil_root or resolve_yggdrasil_root()
    system_settings = resolve_system_settings_path(explicit=settings_path, vault_root=vault, yggdrasil_root=ygg)
    return ResolvedPaths(vault_root=vault, yggdrasil_root=ygg, system_settings_path=system_settings, environment=env)


__all__ = [
    "ResolvedPaths",
    "VaultRootMisconfiguredError",
    "resolve_vault_root",
    "resolve_yggdrasil_root",
    "resolve_system_settings_path",
    "resolve_flow_settings_path",
    "resolve_runtime_artifact_path",
    "resolve_paths",
]
