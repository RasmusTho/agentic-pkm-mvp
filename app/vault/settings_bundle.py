"""Effective-settings bundle revision/digest (MVR-03).

`docs/MULTI_VAULT_RUNTIME/README.md :: Active context and isolation` requires caches,
retrieval results, and settings bundles to be keyed by "the effective per-binding/request-
wide settings bundle revision or digest", and requires a Settings Spine hot reload to
atomically invalidate matching entries or rotate the affected context generation *before* a
later lookup.

`SettingsService.resolve()` recomputes the bundle from disk on every call and carries no
version, so there was nothing to key on. This module supplies exactly that missing value and
nothing more: a content digest over the resolved effective settings.

A digest rather than a counter is the right shape here because `resolve()` is stateless --
there is no place to persist a monotonic revision, and a digest is *stronger* for the
purpose: it changes if and only if a behaviour-shaping value changed, so a no-op reload does
not needlessly invalidate.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any, Protocol


class _HasValue(Protocol):
    key: str
    value: Any


def settings_bundle_digest(settings: Mapping[str, _HasValue]) -> str:
    """Stable digest over every effective setting key and value.

    Sorted by key so bundle ordering can never change the digest, and `repr()`-encoded so
    two distinct values (`1` and `"1"`, `None` and `"None"`) cannot collide into one bundle
    identity.
    """

    material = "|".join(
        f"{key}={value.value!r}" for key, value in sorted(settings.items())
    )
    return hashlib.sha256(f"settings-bundle.v1|{material}".encode()).hexdigest()[:32]


__all__ = ["settings_bundle_digest"]
