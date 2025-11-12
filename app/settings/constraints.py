from __future__ import annotations

from typing import Any, Iterable, Optional


def clamp_int(value: Any, *, lo: Optional[int] = None, hi: Optional[int] = None, default: int = 0) -> int:
    try:
        num = int(value)
    except Exception:
        return default
    if lo is not None and num < lo:
        return lo
    if hi is not None and num > hi:
        return hi
    return num


def as_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "x"}:
        return True
    if text in {"0", "false", "no", "off", ""}:
        return False
    return default


def enum_or_default(value: Any, allowed: Iterable[str], default: str) -> str:
    text = str(value)
    return text if text in allowed else default


def is_secret_ref(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("${SECRET:") and value.endswith("}")
