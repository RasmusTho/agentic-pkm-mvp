"""Full-context cache identity for retrieval and downstream context artifacts (MVR-03).

The rule the contract states, and this module enforces: cache and downstream context
artifacts are keyed by `context_id`, generation, registry/binding revisions, authorization
epoch, workspace/no-workspace state, principal, cognitive scope, sphere memberships,
situated identity, the non-reversible selection-capability digest, dimension/filter, the
binding set, and the effective settings bundle revision/digest --

**never by binding plus generation alone.**

That exclusion is the whole point. Two bearer selections can share a binding and a
generation while carrying different workspace state, scope, spheres, situated identity, or
capability digest; keying on the pair would let one session's cached retrieval context be
served to the other.

Two further invariants are structural here:

- Raw bearer ids never enter a key. Only `selection_capability_digest` does.
- Action, write class, and permission never enter a key. They are separate GOV decision
  inputs and receipt fields, and folding them into cache identity would quietly turn WSP
  scope into a permission.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from app.vault.active_context_v1 import ActiveContextSetV1

CONTEXT_CACHE_KEY_VERSION = "active-context-cache.v1"


@dataclass(frozen=True)
class ContextCacheIdentity:
    """A cache identity plus the components it was derived from.

    The components are retained so a mismatch is debuggable without reversing the digest,
    and so a test can assert *which* input changed the key.
    """

    key: str
    components: tuple[str, ...]

    def __str__(self) -> str:  # pragma: no cover - convenience
        return self.key


def context_cache_identity(
    snapshot: ActiveContextSetV1,
    *,
    settings_bundle_digest: str,
) -> ContextCacheIdentity:
    """Derive the full-context cache identity for one immutable snapshot."""

    components = snapshot.context_identity_components() + (
        f"settings_bundle={settings_bundle_digest}",
    )
    material = "|".join(components)
    key = hashlib.sha256(f"{CONTEXT_CACHE_KEY_VERSION}|{material}".encode()).hexdigest()
    return ContextCacheIdentity(key=key, components=components)


__all__ = [
    "CONTEXT_CACHE_KEY_VERSION",
    "ContextCacheIdentity",
    "context_cache_identity",
]
