import json
from pathlib import Path
from typing import Any, Dict

BASE = Path(__file__).resolve().parents[1] / "data" / "context"

def _read(name: str) -> Any:
    p = BASE / name
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))

def load_context() -> Dict[str, Any]:
    return {
        "system": _read("system.json"),
        "projects": _read("projects.json"),
        "preferences": _read("preferences.json"),
    }
