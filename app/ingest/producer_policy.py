"""Canonical activation and inventory for the optional legacy filesystem producer.

The native registry watcher is not this producer. Merely configuring VAULT_DIR
for another adapter must never enable a second writer or claim its inventory.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    value = activation.strip().lower() if activation is not None else "0"
    if value not in {"0", "false", "no", "off", "1", "true", "yes", "on"}:
        raise ValueError("producer policy ambiguous")
    enabled = value in {"1", "true", "yes", "on"}
    root = None
    if enabled:
        if directory is None or not directory.strip() or not Path(directory).is_absolute():
            raise ValueError("producer policy ambiguous")
        root = Path(directory).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("producer policy ambiguous")
    return FilesystemProducerPolicy(enabled, root, (activation, directory))
