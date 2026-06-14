"""Companion-UI "now" / glance surface renderer.

A pure projection of vault-native moments materialized by the Contextual
Relevance Engine. It renders a read-only glance the human *pulls* and, when the
governed attention loop has already recorded an in-app reach-out decision, marks
that moment with an in-app nudge. It has no OS notification transport and mutates
nothing.
"""

from __future__ import annotations

from html import escape
from typing import Any, Mapping, Sequence

_REF_LINK_CLASS = "moment-ref"


def render_now_surface_html(moments: Sequence[Mapping[str, Any]] | None = None) -> str:
    """Render the glance surface for the given moment view-models.

    The returned HTML carries ``data-surface="glance"`` and
    ``data-pull-only="true"`` unless a governed in-app nudge is present. It
    contains no OS notification, push, or alert affordance.
    """

    items = list(moments or [])
    has_nudges = any(_has_in_app_nudge(moment) for moment in items)
    if not items:
        body = (
            '<p class="now-empty">Nothing to surface right now. '
            "You're oriented.</p>"
        )
    else:
        body = "\n".join(_render_moment_card(moment) for moment in items)

    return (
        '<section data-testid="now-surface" data-surface="glance" '
        f'data-pull-only="{str(not has_nudges).lower()}" '
        f'data-in-app-nudges="{str(has_nudges).lower()}" '
        'role="region" aria-label="Now — current moments">\n'
        '  <header class="now-header">'
        "<h2>Now</h2>"
        f'<p class="now-note">{_surface_note(has_nudges)}</p>'
        "</header>\n"
        f'  <ol class="now-moments">\n{body}\n  </ol>\n'
        "</section>"
    )


def _render_moment_card(moment: Mapping[str, Any]) -> str:
    moment_id = escape(str(moment.get("moment_id", "")))
    title = escape(str(moment.get("title", "Moment")))
    band = escape(str(moment.get("urgency_band", "routine")))
    basis = escape(str(moment.get("need_basis", "")))
    authority = escape(str(moment.get("authority", "non-authoritative")))
    nudge_html = _render_in_app_nudge(moment)

    refs_html = "\n".join(
        _render_ref(ref) for ref in moment.get("surfaced_refs", []) or []
    )
    return (
        f'    <li class="moment-card" data-moment-id="{moment_id}" '
        f'data-urgency="{band}" data-authority="{authority}">\n'
        f'      <h3 class="moment-title">{title}</h3>\n'
        f'      <p class="moment-meta"><span class="moment-urgency">{band}</span> · '
        f'<span class="moment-basis">{basis}</span></p>\n'
        f"{nudge_html}"
        f'      <ul class="moment-refs">\n{refs_html}\n      </ul>\n'
        "    </li>"
    )


def _surface_note(has_nudges: bool) -> str:
    if has_nudges:
        return escape(
            "Current moments from your vault. Highlighted nudges have a governed receipt."
        )
    return escape(
        "A pull-only glance. These are non-authoritative proposals from your vault "
        "\u2014 the system does not interrupt you here."
    )


def _has_in_app_nudge(moment: Mapping[str, Any]) -> bool:
    nudge = moment.get("in_app_nudge")
    return isinstance(nudge, Mapping) and nudge.get("active") is True


def _render_in_app_nudge(moment: Mapping[str, Any]) -> str:
    nudge = moment.get("in_app_nudge")
    if not isinstance(nudge, Mapping) or nudge.get("active") is not True:
        return ""
    receipt_id = escape(str(nudge.get("receipt_id", "")))
    effective_band = escape(str(nudge.get("effective_band", "")))
    interruptibility = escape(str(nudge.get("interruptibility_state", "")))
    return (
        '      <p class="moment-nudge" data-testid="moment-in-app-nudge" '
        'data-rung="in_app_nudge" '
        f'data-receipt-id="{receipt_id}" data-effective-band="{effective_band}" '
        f'data-interruptibility="{interruptibility}">'
        "Nudge: ready now, with receipt.</p>\n"
    )


def _render_ref(ref: Mapping[str, Any]) -> str:
    target = str(ref.get("ref", ""))
    href = escape(target.replace(" ", "%20"), quote=True)
    label = escape(target)
    why = escape(str(ref.get("why", "")))
    return (
        f'        <li><a class="{_REF_LINK_CLASS}" href="{href}">{label}</a>'
        f" — {why}</li>"
    )


__all__ = ["render_now_surface_html"]
