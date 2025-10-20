from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class PlannedAction:
    tool: str
    args: dict[str, Any]
    description: str = ""
