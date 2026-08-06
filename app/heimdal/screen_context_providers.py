"""Local context providers for the screen derivation stage (SCREEN-02, #3344).

Specified by `docs/HEIMDAL_SCREEN_STREAM/DERIVE_ACTIVITY_OBSERVATIONS.md`
:: What This Task Does step 2: the frontmost app/window is **provider #1**;
others (active calendar event, the frontmost editor's git branch,
playing media) plug in as declared providers "without changing the derivation
contract".

Two rules define this seam and are the reason it is a registry rather than a
growing parameter list on the stage:

- **Providers run host-side over the already-read bundle.** A provider is
  handed the decoded frame bundle the gated raw read (HEIM-5) already
  produced. None of them re-reads the screen, opens a new raw handle, or
  reaches any network, so adding one adds no new evidence path and no new
  egress surface to review.
- **Providers enrich, they do not decide.** A contribution is context
  (`facts`), surfaced mentions, and optionally the segmenter `dimensions` the
  span coalescer keys on. A provider never publishes, never resolves a
  canonical identity, and cannot change the observation payload contract --
  which is what keeps "add a provider" a local change rather than a contract
  change.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

#: Provider #1 -- the frontmost app/window metadata captured with the frame.
FRONTMOST_APP_PROVIDER = "frontmost_app"


@dataclass(frozen=True)
class FrameContext:
    """What a provider may read: one already-gated frame bundle, nothing more."""

    raw_ref: str
    observed_at: str
    bundle: Mapping[str, Any]


@dataclass(frozen=True)
class ContextContribution:
    """One provider's contribution to a frame's derivation.

    ``facts`` are short human-legible context lines (they reach both the local
    model's prompt and the published markdown), ``mentions`` are surfaced
    entity mentions (never canonical identities -- resolution is stamped
    ``unresolved`` downstream, HEIM-6/HEIM-11), and ``dimensions`` are the
    segmenter axes this provider is authoritative for (INV-SCREEN-E).
    """

    provider: str
    facts: Tuple[str, ...] = ()
    mentions: Tuple[Mapping[str, Any], ...] = ()
    dimensions: Mapping[str, str] = field(default_factory=dict)


ContextProvider = Callable[[FrameContext], Optional[ContextContribution]]


def _bundle_value(bundle: Mapping[str, Any], key: str) -> str:
    value = bundle.get(key)
    return str(value).strip() if value is not None else ""


def frontmost_app_provider(context: FrameContext) -> Optional[ContextContribution]:
    """Provider #1: the frontmost app / window / capture scope of this frame.

    These are the three metadata dimensions the client captures alongside the
    pixels; the fourth segmenter dimension (the derived goal) comes from the
    derivation itself, not from a provider.
    """
    app = _bundle_value(context.bundle, "app")
    window = _bundle_value(context.bundle, "window")
    scope = _bundle_value(context.bundle, "scope")

    facts = []
    mentions = []
    if app:
        facts.append(f"frontmost app: {app}")
        mentions.append({"surface_form": app, "kind_hint": "app"})
    if window:
        facts.append(f"window: {window}")
        mentions.append({"surface_form": window, "kind_hint": "document"})
    if scope:
        facts.append(f"capture scope: {scope}")

    return ContextContribution(
        provider=FRONTMOST_APP_PROVIDER,
        facts=tuple(facts),
        mentions=tuple(mentions),
        dimensions={"app": app, "window": window, "scope": scope},
    )


def _default_registry() -> Dict[str, ContextProvider]:
    return {FRONTMOST_APP_PROVIDER: frontmost_app_provider}


_REGISTRY: Dict[str, ContextProvider] = _default_registry()


def register_context_provider(name: str, provider: ContextProvider) -> None:
    """Register one local context provider under a stable name.

    Refuses a duplicate name loudly rather than silently replacing a
    registered provider: two providers quietly sharing a name would make the
    derived observation depend on import order.
    """
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"context provider name must be a non-empty string, got {name!r}")
    if not callable(provider):
        raise TypeError(f"context provider {name!r} must be callable, got {type(provider)!r}")
    if name in _REGISTRY:
        raise ValueError(f"context provider {name!r} is already registered")
    _REGISTRY[name] = provider


def unregister_context_provider(name: str) -> None:
    """Remove a registered provider (raises if it was never registered)."""
    if name not in _REGISTRY:
        raise KeyError(name)
    del _REGISTRY[name]


def registered_context_providers() -> Tuple[Tuple[str, ContextProvider], ...]:
    """Every registered provider in registration order (deterministic)."""
    return tuple(_REGISTRY.items())


def reset_context_providers() -> None:
    """Restore the built-in provider set (test/dev reset hook)."""
    _REGISTRY.clear()
    _REGISTRY.update(_default_registry())


def collect_context(context: FrameContext) -> Tuple[ContextContribution, ...]:
    """Run every registered provider over one frame, in registration order."""
    contributions = []
    for _, provider in registered_context_providers():
        contribution = provider(context)
        if contribution is not None:
            contributions.append(contribution)
    return tuple(contributions)


__all__ = [
    "ContextContribution",
    "ContextProvider",
    "FRONTMOST_APP_PROVIDER",
    "FrameContext",
    "collect_context",
    "frontmost_app_provider",
    "register_context_provider",
    "registered_context_providers",
    "reset_context_providers",
    "unregister_context_provider",
]
