"""Immutable commitment-state evidence shared by activity producers and debrief admission."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


def commitment_state_fingerprint(fields: Mapping[str, Any]) -> str:
    # ERE's mechanical episode_ref stamp and YAML formatting are not state changes.
    state = {key: fields.get(key) for key in (
        "kind", "commitment", "commitment_id", "commitment_kind", "commitment_state", "state", "status",
    )}
    return hashlib.sha256(json.dumps(state, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
