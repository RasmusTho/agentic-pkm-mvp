"""Pure Companion renderer for the offer-only evening reflection trigger."""

from __future__ import annotations

from html import escape
from typing import Mapping


def render_evening_reflection_offer_html(
    offer: Mapping[str, object] | None,
    *,
    note_path: str = "",
) -> str:
    """Render a tap affordance only for the server-declared inert offer.

    The renderer performs no request and starts no conversation.  Its only
    output is a button carrying the explicit action for the Companion event
    dispatcher to invoke after a human tap.
    """
    if not offer:
        return ""
    action = str(offer.get("action") or "")
    if offer.get("tap_required") is not True or action != "journaling.reflection.begin":
        return ""
    label = escape(str(offer.get("label") or "Reflect on today?"))
    safe_note_path = escape(note_path, quote=True)
    return (
        '<section class="evening-reflection-offer" '
        'data-testid="evening-reflection-offer" data-offer-only="true" '
        f'data-note-path="{safe_note_path}">'
        f'<button type="button" data-action="{escape(action, quote=True)}" '
        'data-api-path="/api/companion/journaling/reflection/start" '
        f'data-requires-explicit-tap="true">{label}</button>'
        '<span data-testid="evening-reflection-status" role="status" '
        'aria-live="polite"></span></section>'
    )


__all__ = ["render_evening_reflection_offer_html"]
