"""Companion-UI "now" / glance surface renderer (pull-only).

A pure projection of vault-native moments materialized by the Contextual
Relevance Engine. It renders a read-only glance the human *pulls*; it never
reaches out, shows no notification/push affordance, and mutates nothing. This is
the first runtime slice (CRE-03): pull-only, no proactivity. The graduated
reach-out ladder (in-app nudge / OS push) is the attention-loop slice (CRE-04).
"""

from __future__ import annotations

from html import escape
from typing import Any, Mapping, Sequence

_REF_LINK_CLASS = "moment-ref"


def render_now_surface_html(moments: Sequence[Mapping[str, Any]] | None = None) -> str:
    """Render the glance surface for the given moment view-models, pull-only.

    The returned HTML carries ``data-surface="glance"`` and
    ``data-pull-only="true"`` and contains no notification, push, or alert
    affordance — surfacing presence is never urgency or approval.
    """

    items = list(moments or [])
    if not items:
        body = (
            '<p class="now-empty">Nothing to surface right now. '
            "You're oriented.</p>"
        )
    else:
        body = "\n".join(_render_moment_card(moment) for moment in items)

    return (
        '<section data-testid="now-surface" data-surface="glance" '
        'data-pull-only="true" role="region" aria-label="Now — current moments">\n'
        '  <header class="now-header">'
        "<h2>Now</h2>"
        '<p class="now-note">A pull-only glance. These are non-authoritative '
        "proposals from your vault — the system does not interrupt you here.</p>"
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

    refs_html = "\n".join(
        _render_ref(ref) for ref in moment.get("surfaced_refs", []) or []
    )
    return (
        f'    <li class="moment-card" data-moment-id="{moment_id}" '
        f'data-urgency="{band}" data-authority="{authority}">\n'
        f'      <h3 class="moment-title">{title}</h3>\n'
        f'      <p class="moment-meta"><span class="moment-urgency">{band}</span> · '
        f'<span class="moment-basis">{basis}</span></p>\n'
        f'      <ul class="moment-refs">\n{refs_html}\n      </ul>\n'
        "    </li>"
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
