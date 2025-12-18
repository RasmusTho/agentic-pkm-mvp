from pathlib import Path
from typing import Any, Dict, List
import yaml

from app.config.paths import resolve_system_settings_path
from app.index.build import build_index_from_settings


def build_from_canonical_settings(path: Path | str | None = None) -> List[Dict[str, Any]]:
    resolved = Path(path) if path is not None else resolve_system_settings_path()
    if resolved is None or not resolved.exists():
        raise FileNotFoundError(f"Missing settings YAML at {resolved}")
    settings = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    return build_index_from_settings(settings)
