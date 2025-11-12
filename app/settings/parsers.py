from __future__ import annotations

import re
from typing import Any, Dict

import yaml

from .loader import find_fenced_settings

CHECKBOX = re.compile(r"(?m)^- \[(?P<on>[xX ])\] +(?P<key>[\w_.-]+)\s*$")
TABLE_ROW = re.compile(r"(?m)^\|(?P<k>[^|]+)\|(?P<v>[^|]+)\|\s*$")


def assign_dotpath(dst: Dict[str, Any], path: str, value: Any) -> None:
    cur = dst
    parts = [p.strip() for p in path.split(".") if p.strip()]
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    if parts:
        cur[parts[-1]] = value


def coerce(value: str) -> Any:
    raw = value.strip()
    lowered = raw.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def parse_section(md: str) -> Dict[str, Any]:
    block = find_fenced_settings(md)
    if block:
        loaded = yaml.safe_load(block) or {}
        return loaded
    out: Dict[str, Any] = {}
    for match in CHECKBOX.finditer(md):
        assign_dotpath(out, match.group("key"), match.group("on").lower() == "x")
    for match in TABLE_ROW.finditer(md):
        key = match.group("k").strip().strip("|- ")
        value = match.group("v").strip().strip("|- ")
        if key and value and key.lower() != "key":
            assign_dotpath(out, key, coerce(value))
    return out
