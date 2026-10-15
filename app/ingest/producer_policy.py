"""Canonical activation and inventory for native and optional filesystem producers.

The native registry watcher is not this producer. Merely configuring VAULT_DIR
for another adapter must never enable a second writer or claim its inventory.
"""
from __future__ import annotations

import os
import hashlib
from dataclasses import dataclass
from pathlib import Path


def parse_producer_activation(value: str) -> bool:
    value = value.strip().lower()
    if value not in {"0", "false", "no", "off", "1", "true", "yes", "on"}:
        raise ValueError("producer policy ambiguous")
    return value in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class FilesystemProducerPolicy:
    enabled: bool
    root: Path | None
    configuration: tuple[str | None, str | None]

    def includes(self, path: Path) -> bool:
        return bool(self.enabled and self.root is not None
                    and filesystem_source_in_inventory(path, self.root))


def filesystem_source_in_inventory(path: Path, root: Path) -> bool:
    return (path.is_relative_to(root) and path.suffix == ".md"
            and not any(part.startswith(".obsidian") for part in path.parts))


def filesystem_producer_policy() -> FilesystemProducerPolicy:
    """Unset activation means disabled; an enabled producer requires an explicit root.

    Both the real entrypoint and stopped-writer recovery consume this reader.
    No guessed path, permissive boolean coercion or synthesized environment is
    allowed to authorize either a producer claim or a recovery write.
    """
    activation, directory = os.getenv("FS_WATCHER_ENABLE"), os.getenv("VAULT_DIR")
    enabled = parse_producer_activation(activation if activation is not None else "0")
    root = None
    if enabled:
        if directory is None or not directory.strip() or not Path(directory).is_absolute():
            raise ValueError("producer policy ambiguous")
        root = Path(directory).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("producer policy ambiguous")
    return FilesystemProducerPolicy(enabled, root, (activation, directory))


@dataclass(frozen=True)
class RegistryProducerPolicy:
    enabled: bool
    root: Path | None
    scopes: tuple[str, ...]
    specifications: tuple[tuple[str, str, str], ...]
    sources: frozenset[Path]
    configuration: tuple[tuple[str, str | None], ...]
    registry_digest: str

    def includes(self, path: Path) -> bool:
        return self.enabled and path in self.sources


def registry_producer_policy(active_root: Path) -> RegistryProducerPolicy:
    """Read the actual native entrypoint's registry, binding and source scopes."""
    from app.settings.env_defaults import env_str
    from app.watcher.registry import DEFAULT_REGISTRY_CONFIG_PATH, load_registry_config, source_backed_registry_inventory
    from app.events.types import INGEST_VAULT_CHANGED, PANEL_SCAN_REQUESTED

    configuration = tuple((key, os.getenv(key)) for key in (
        "WATCHER_ENABLE", "WATCHER_VAULT_PATH", "WATCHER_SCOPE_GLOB", "PKM_SETTINGS_PROFILE",
        "VAULT_SYSTEM_DIR_REL",
    ))
    if not parse_producer_activation(env_str("WATCHER_ENABLE")):
        return RegistryProducerPolicy(False, None, (), (), frozenset(), configuration, "")
    raw_root = os.getenv("WATCHER_VAULT_PATH")
    if not raw_root or not Path(raw_root).is_absolute():
        raise ValueError("producer policy ambiguous")
    snapshot = DEFAULT_REGISTRY_CONFIG_PATH.read_bytes()
    cfg = load_registry_config(DEFAULT_REGISTRY_CONFIG_PATH, read_only=True)
    if not cfg.enable or cfg.vault_path.resolve(strict=True) != active_root:
        raise ValueError("producer policy ambiguous")
    if (len({spec.name for spec in cfg.specs}) != len(cfg.specs)
            or any(not spec.name or spec.name == "None"
                   or spec.emit_event not in {INGEST_VAULT_CHANGED, PANEL_SCAN_REQUESTED} for spec in cfg.specs)):
        raise ValueError("producer policy ambiguous")
    scopes = tuple(spec.scope_glob for spec in cfg.specs if spec.emit_event == INGEST_VAULT_CHANGED)
    sources = source_backed_registry_inventory(cfg)
    if cfg.config_path.read_bytes() != snapshot:
        raise ValueError("producer policy changed")
    specifications = tuple((spec.name, spec.emit_event, spec.scope_glob) for spec in cfg.specs)
    return RegistryProducerPolicy(True, active_root, scopes, specifications, sources, configuration,
        hashlib.sha256(snapshot).hexdigest())
