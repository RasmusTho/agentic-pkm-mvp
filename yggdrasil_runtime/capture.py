"""Capture stage — the first runtime stage that stamps a complete ``MetadataBundle``.

``capture(text, principal_id)`` returns an in-memory artifact whose ``.metadata_bundle`` carries
identity, the active scope binding, the three orthogonal role dimensions, sensitivity, suppression
state, and provenance. Every downstream runtime object inherits from this foundation.

Scope-vs-vault: ``scope_id`` is the cognitive/policy/provenance frame (stamped from the active scope
binding, WSP); ``vault_id`` is storage topology. They are never equal — collapsing them would let
storage location silently define policy (the exact error the architecture forbids).

In-memory only: captured artifacts live in a process-local registry; nothing persists across a
restart, and there is no WriteGuard/durable-mutation path here (out of scope for the slice). The DRI
stage (#2581) reads this registry to derive segments that inherit a captured artifact's bundle.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from yggdrasil_runtime.metadata import MetadataBundle

# Default active scope binding for capture (WSP would supply this at runtime). Distinct from any
# vault id so scope_id != vault_id holds by construction.
DEFAULT_CAPTURE_SCOPE = "scope:capture/inbox"
DEFAULT_VAULT_ID = "vault:local"


@dataclass
class CapturedArtifact:
    """A captured human input plus its metadata bundle (the unit capture emits and stores)."""

    metadata_bundle: MetadataBundle
    text: str


# Process-local in-memory store. Not durable; the runtime equivalent of "captured, not yet persisted".
_CAPTURED: dict[str, CapturedArtifact] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def capture(
    text: str,
    principal_id: str,
    *,
    scope_id: str = DEFAULT_CAPTURE_SCOPE,
    vault_id: str = DEFAULT_VAULT_ID,
) -> CapturedArtifact:
    """Capture a thought and stamp a complete MetadataBundle.

    The returned object exposes ``.metadata_bundle`` with a truthy ``scope_id`` and ``source_role``;
    the artifact is registered in the in-memory store so DRI can later inherit its bundle.
    """
    object_id = f"artifact:{uuid4().hex[:12]}"
    content_hash = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
    bundle = MetadataBundle(
        object_id=object_id,
        object_type="artifact",
        scope_id=scope_id,
        source_role="human_capture",
        authority_state="captured",
        evidence_role="reference",
        sensitivity="private",
        suppression_state="visible",
        created_by=principal_id,
        created_at=_now_iso(),
        provenance_event_ids=[f"prov:capture:{uuid4().hex[:8]}"],
        vault_id=vault_id,
        principal_id=principal_id,
        content_hash=content_hash,
    )
    artifact = CapturedArtifact(metadata_bundle=bundle, text=text)
    _CAPTURED[object_id] = artifact
    return artifact


def get_captured(object_id: str) -> CapturedArtifact | None:
    """Return a previously captured artifact by id, or None. Used by the DRI stage (#2581)."""
    return _CAPTURED.get(object_id)


def reset_captured() -> None:
    """Clear the in-memory capture store (test isolation)."""
    _CAPTURED.clear()
