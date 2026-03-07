from __future__ import annotations

import os
from collections.abc import Mapping


def resolve_obsidian_vault_name(env: Mapping[str, str] | None = None) -> str:
    source = env if env is not None else os.environ
    return (source.get("OBSIDIAN_VAULT_NAME") or "").strip() or "Vault"


__all__ = ["resolve_obsidian_vault_name"]
