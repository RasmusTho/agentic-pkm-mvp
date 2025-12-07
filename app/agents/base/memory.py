from __future__ import annotations

import time
import uuid
from typing import Any, Dict, Tuple

MemoryKey = Tuple[str, str, str | None]
_MEMORY: Dict[MemoryKey, list[dict[str, Any]]] = {}


def _key(agent: str, key: str, scope_object_id: str | None) -> MemoryKey:
    return (agent, key, scope_object_id)


def remember(
    *,
    agent: str,
    key: str,
    value: dict[str, Any],
    scope_object_id: str | None = None,
    ttl_seconds: int | None = None,
) -> None:
    """
    Lightweight, in-process memory helper for agents.
    Stores the latest value per (agent, key, scope) with optional TTL.
    """
    expires_at = int(time.time()) + int(ttl_seconds) if ttl_seconds else None
    entry = {
        "id": str(uuid.uuid4()),
        "value": value,
        "expires_at": expires_at,
    }
    bucket = _MEMORY.setdefault(_key(agent, key, scope_object_id), [])
    bucket.append(entry)
    # keep latest at the end; trim unbounded growth
    if len(bucket) > 64:
        del bucket[:-64]


def recall(*, agent: str, key: str, scope_object_id: str | None = None) -> dict[str, Any] | None:
    """
    Return the most recent non-expired value for (agent, key, scope).
    """
    bucket = _MEMORY.get(_key(agent, key, scope_object_id), [])
    now = int(time.time())
    for entry in reversed(bucket):
        expires_at = entry.get("expires_at")
        if expires_at and now > int(expires_at):
            continue
        return entry.get("value")
    return None
