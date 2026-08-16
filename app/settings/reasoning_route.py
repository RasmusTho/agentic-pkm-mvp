"""One side-effect-free effective route for provider-neutral reasoning.

The compiled Settings Spine owns the provider/model identity.  The temporary
``REASONING_MODEL`` bootstrap override is deliberately model-only: it must not
silently turn an OpenAI route into an Ollama route (or vice versa).
"""

from __future__ import annotations

import os
from dataclasses import replace

from app.components.llm.router import LLMRoute, LLMRouter, LLMTaskIntent
from app.settings.tiering import active_settings_profile


def resolve_effective_reasoning_route() -> LLMRoute:
    """Resolve the current compiled reasoning route without performing I/O.

    ``LLMRouter`` reads the atomically-published settings generation, so each
    call observes one bundle.  This resolver adds only the one-release legacy
    model override and never derives a provider from that override.
    """
    route = LLMRouter().route(LLMTaskIntent(task_kind="reasoning", risk="high"))
    legacy_model = (os.getenv("REASONING_MODEL") or "").strip()
    if not legacy_model:
        return route
    return replace(route, model=legacy_model, reason="legacy:REASONING_MODEL")


def describe_effective_reasoning_route() -> dict[str, object]:
    """Return safe explain data from the exact resolver used by execution."""
    route = resolve_effective_reasoning_route()
    legacy_model = (os.getenv("REASONING_MODEL") or "").strip()
    return {
        "provider": route.provider,
        "model": route.model,
        "mode": route.mode,
        "degraded": route.degraded,
        "origin": "env:REASONING_MODEL" if legacy_model else "settings:llm_routing.default_reasoning",
        "tier": active_settings_profile(),
    }
