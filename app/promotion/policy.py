from pathlib import Path
from typing import Any, Dict


def pick_target(meta: Dict[str, Any], move_policy: Dict[str, Any]) -> Path:
    targets = move_policy.get("targets", []) or []
    for rule in targets:
        cond = rule.get("when", {}) or {}
        if all(meta.get(k) == v for k, v in cond.items()):
            return Path(rule["path"])
    return Path(move_policy.get("default_target", "2_Cards/Concepts"))


__all__ = ["pick_target"]
