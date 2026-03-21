from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


def _template_path() -> Path:
    return Path(__file__).resolve().parents[2] / "docs" / "settings" / "default-vault-layout.yaml"


def load_default_vault_layout() -> dict[str, Any]:
    payload = yaml.safe_load(_template_path().read_text(encoding="utf-8")) or {}
    data = payload if isinstance(payload, dict) else {}
    return deepcopy(data)


__all__ = ["load_default_vault_layout"]
