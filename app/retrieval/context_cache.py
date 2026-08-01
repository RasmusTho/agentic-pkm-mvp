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


class ContextScopedCache:
    """A minimal cache whose entries are addressed by full-context identity.

    Deliberately tiny: the contract needs a place where "invalidate before the next lookup"
    is a real, testable operation, not a new caching subsystem. `app/retrieval/hybrid.py`
    keeps owning the document store; this owns context-keyed derived entries.
    """

    def __init__(self) -> None:
        self._entries: dict[str, dict[str, object]] = {}
        #: context_id -> the identity keys derived under it, so a generation rotation can
        #: invalidate every entry for that context without reversing any digest.
        self._context_index: dict[str, set[str]] = {}

    def get(self, identity: ContextCacheIdentity, key: str) -> object | None:
        return self._entries.get(identity.key, {}).get(key)

    def put(
        self,
        identity: ContextCacheIdentity,
        key: str,
        value: object,
        *,
        context_id: str | None = None,
    ) -> None:
        self._entries.setdefault(identity.key, {})[key] = value
        if context_id is not None:
            self._context_index.setdefault(context_id, set()).add(identity.key)

    def invalidate(self, identity: ContextCacheIdentity) -> None:
        self._entries.pop(identity.key, None)

    def invalidate_context(self, context_id: str) -> int:
        """Drop every entry whose identity was derived for one context id.

        Used by the resolver's cache-invalidation descriptor when a binding revision,
        registry revision, or authority verdict changed and the generation rotated.
        """

        dropped = 0
        for cache_key in self._context_index.pop(context_id, set()):
            if self._entries.pop(cache_key, None) is not None:
                dropped += 1
        return dropped

    def __len__(self) -> int:
        return sum(len(entries) for entries in self._entries.values())


__all__ = [
    "CONTEXT_CACHE_KEY_VERSION",
    "ContextCacheIdentity",
    "ContextScopedCache",
    "context_cache_identity",
]
