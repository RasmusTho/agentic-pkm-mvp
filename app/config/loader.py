from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from app.config.paths import resolve_system_settings_path


def load_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    resolved = resolve_system_settings_path(explicit=path)
    return yaml.safe_load(resolved.read_text(encoding="utf-8"))
