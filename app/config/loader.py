from pathlib import Path
import yaml
from typing import Any, Dict, Optional

DEFAULT_PATH = Path("vault/_system/settings/system-settings.yaml")

def load_settings(path: Optional[Path] = None) -> Dict[str, Any]:
    p = path or DEFAULT_PATH
    return yaml.safe_load(p.read_text(encoding="utf-8"))
