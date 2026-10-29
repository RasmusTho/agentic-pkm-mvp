"""Immutable commitment-content evidence shared by activity producers and debrief admission."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from app.agents.panel.filters import strip_ai_panels
from app.agents.panel.writeback import strip_ai_status_block
from app.domain.state_axes import normalize_artifact_state_axes


def commitment_content_fingerprint(fields: Mapping[str, Any], body: str) -> str:
    # Preserve every semantic field (including summary/target/source_goal and
    # future fields). Only ERE's mechanical episode_ref stamp is excluded.
    # Match the existing ingest normalization, not YAML serialization/formatting.
    normalized = normalize_artifact_state_axes(dict(fields), default_review_state="provisional")
    # Vault-sync has already normalized its immutable frontmatter. Retain the
    # derived legacy marker on a second pass so raw and emitted forms agree.
    if "legacy_review_state" in fields:
        normalized.setdefault("legacy_review_state", fields["legacy_review_state"])
    normalized.pop("episode_ref", None)
    content = {"frontmatter": normalized, "body": strip_ai_status_block(strip_ai_panels(body)).strip()}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
