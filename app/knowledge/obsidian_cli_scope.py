from __future__ import annotations

from typing import Sequence


def scoped_cli_args(vault: str, args: Sequence[str]) -> list[str]:
    """Ensure Obsidian CLI args are scoped with `vault=<...>` as first arg."""

    scoped_vault = vault.strip()
    if not scoped_vault:
        raise ValueError("vault is required")
    return [f"vault={scoped_vault}", *list(args)]


def has_valid_vault_scope(argv: Sequence[str]) -> bool:
    if not argv:
        return False
    return isinstance(argv[0], str) and argv[0].startswith("vault=") and len(argv[0]) > len("vault=")


__all__ = ["has_valid_vault_scope", "scoped_cli_args"]
