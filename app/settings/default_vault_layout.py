from __future__ import annotations

from copy import deepcopy
from typing import Any


DEFAULT_VAULT_LAYOUT: dict[str, Any] = {
    "version": "1",
    "layout": {
        "system_folder": "⚙️ System",
        "inbox_folder": "📥 Inbox",
        "desk_folder": "🛠️ Workbench",
        "runtime_dir_rel": "⚙️ System/Runtime/Alpha",
        "root_folders": ["⚙️ System", "📥 Inbox", "🛠️ Workbench"],
        "include_folders": ["📥 Inbox", "🛠️ Workbench"],
        "ignore_glob": [],
    },
    "paths": {
        "system_dir_rel": "⚙️ System",
        "inbox_dir_rel": "📥 Inbox",
        "runtime_dir_rel": "⚙️ System/Runtime/Alpha",
    },
}


def load_default_vault_layout() -> dict[str, Any]:
    return deepcopy(DEFAULT_VAULT_LAYOUT)
