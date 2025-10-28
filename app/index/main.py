from pathlib import Path
from typing import Any, Dict, List
import yaml

from app.index.build import build_index_from_settings

def build_from_canonical_settings(path: Path | str = "vault/_system/settings/system-settings.yaml") -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Missing settings YAML at {p}")
    settings = yaml.safe_load(p.read_text(encoding="utf-8"))
    return build_index_from_settings(settings)
