"""One overlay modal-frame contract for every shell overlay (CUIDR-02, #2445).

Implements ``docs/COMPANION_UI_DEEP_REVIEW_REMEDIATION/OVERLAY_MODAL_FRAME_SPEC.md``
against the shared overlay host (``overlay_host.py``, #1785). The deep review's
cross-cutting "Overlay-grammar consistency" finding is that today every overlay
ad-hoc-positions itself, varies its header furniture, and wires its own dismiss
— so the user must re-learn how to open, read, and close each one.

This module is the **single frame render path**. It owns, in one place:

- the two declared frame **positions** (:data:`FRAME_POSITIONS`): ``center``
  and ``right-drawer``; every overlay root carries exactly one via
  ``data-overlay-frame-position``;
- the fixed **header furniture** order — **title · status-pill · ⓘ · close** —
  emitted by :func:`overlay_frame_header` as a single
  ``<header data-region="overlay-header">``; the status-pill and ⓘ slots render
  only when the overlay supplies content for them (no empty placeholders);
- the one **close** affordance, which routes through ``overlayHost.dismiss()``
  — the same dismiss grammar the host's single scrim and ``Esc`` already use
  (the scrim itself lives once in ``overlay_host.overlay_host_markup``);
- a **focus-trap** hook: the frame stamps ``data-overlay-focus-trap="true"`` on
  every overlay root so the shared host controller can confine keyboard focus
  to the open overlay (the trap motion itself is exercised in live UAT).

The frame is **presentation only**: it carries no entry-state, authority,
posture, staleness, or receipt classification. The ``status_pill`` slot renders
a string the overlay already declared (e.g. Settings' ``read-only``); it never
derives one. Like the rest of the shell, the functions here are pure string
emitters with no I/O — ``render_index_html`` embeds the result.
"""

from __future__ import annotations

import html as _html
from typing import Optional

from companion_ui.workspace.guidance_layer import guidance_toggle_markup

# The two declared frame positions (spec §Frame positions defined). Every
# overlay root carries exactly one of these on ``data-overlay-frame-position``;
# adding a position is a spec change.
FRAME_POSITIONS: tuple[str, ...] = ("center", "right-drawer")

# The fixed header-furniture order, left to right (spec §Header furniture
# slots). ``status`` and ``info`` are conditionally present; ``title`` and
# ``close`` are always present. Exposed so the sole-source test can assert the
# canonical order without re-deriving it.
HEADER_FURNITURE_ORDER: tuple[str, ...] = ("title", "status", "info", "close")

# The one dismiss grammar every overlay shares (host scrim, ``Esc``, and this
# close button all route here). Named once so no overlay re-invents it.
OVERLAY_DISMISS_CALL = "overlayHost.dismiss()"
OVERLAY_DISMISS_INTENT = "overlay.dismiss"

# Marker comments bracketing the canonical header markup. The sole-source test
# greps these so it can prove the header furniture is emitted only from this
# module and nowhere else.
HEADER_MARKER_OPEN = "<!-- overlay-frame-header -->"
HEADER_MARKER_CLOSE = "<!-- /overlay-frame-header -->"


def _e(value: object) -> str:
    return _html.escape(str(value if value is not None else ""), quote=True)


def frame_position_attr(position: str) -> str:
    """The ``data-overlay-frame-position`` attribute for an overlay root.

    Rejects any position outside :data:`FRAME_POSITIONS` — the position set is
    a contract, not a hint, so a bespoke value can never slip onto an overlay.
    """
    if position not in FRAME_POSITIONS:
        raise ValueError(
            f"undeclared overlay frame position {position!r}; "
            f"declared: {FRAME_POSITIONS}"
        )
    return f'data-overlay-frame-position="{position}"'


def overlay_frame_header(
    *,
    overlay_id: str,
    title: str,
    status_pill: Optional[str] = None,
    status_pill_testid: Optional[str] = None,
    guidance_surface: Optional[str] = None,
    close_label: str = "Close and return to the document",
) -> str:
    """The one canonical overlay header — furniture in the fixed order.

    Emits a single ``<header data-region="overlay-header">`` whose children are,
    left to right: **title · status-pill · ⓘ · close**.

    - ``title`` — always rendered; the overlay's plain-language name.
    - ``status_pill`` — rendered only when supplied: a string the overlay
      already declared (e.g. Settings' ``read-only``). Presentation only — the
      frame never derives a status. ``status_pill_testid`` keeps an overlay's
      shipped testid stable when one already exists.
    - ``guidance_surface`` — when supplied, renders the shared ``ⓘ`` guidance
      toggle for that surface (the existing :func:`guidance_toggle_markup`).
    - ``close`` — always rendered; routes through ``overlayHost.dismiss()``,
      the one dismiss grammar shared with the host scrim and ``Esc``.

    The result is bracketed by :data:`HEADER_MARKER_OPEN` /
    :data:`HEADER_MARKER_CLOSE` so the sole-source test can prove header
    furniture originates only here.
    """
    title_html = (
        '<span class="overlay-frame-title" data-region="overlay-title" '
        f'data-overlay-id="{_e(overlay_id)}">{_e(title)}</span>'
    )

    status_html = ""
    if status_pill is not None and str(status_pill) != "":
        testid = status_pill_testid or "overlay-frame-status-pill"
        status_html = (
            '<span class="overlay-frame-status-pill" '
            f'data-testid="{_e(testid)}" data-region="overlay-status-pill">'
            f"{_e(status_pill)}</span>"
        )

    info_html = ""
    if guidance_surface is not None:
        # The ⓘ slot is the shared guidance toggle (presentation-only, no
        # transport) — the same affordance the overlays already shipped.
        info_html = (
            '<span class="overlay-frame-info" data-region="overlay-info">'
            f"{guidance_toggle_markup(guidance_surface)}</span>"
        )

    close_html = (
        '<button type="button" class="overlay-frame-close" '
        'data-testid="overlay-frame-close" data-region="overlay-close" '
        f'data-overlay-id="{_e(overlay_id)}" '
        f'data-intent="{OVERLAY_DISMISS_INTENT}" '
        f'aria-label="{_e(close_label)}" '
        f'onclick="{OVERLAY_DISMISS_CALL}">&times;</button>'
    )

    return (
        f"{HEADER_MARKER_OPEN}"
        '<header class="overlay-frame-header" data-region="overlay-header" '
        f'data-overlay-id="{_e(overlay_id)}" '
        f'data-furniture-order="{" ".join(HEADER_FURNITURE_ORDER)}">'
        f"{title_html}{status_html}{info_html}{close_html}"
        "</header>"
        f"{HEADER_MARKER_CLOSE}"
    )


def overlay_frame_root_attrs(*, overlay_id: str, position: str) -> str:
    """The shared overlay-root attributes the frame stamps on every overlay.

    Carries the declared frame position and the focus-trap hook the host
    controller reads to confine keyboard focus while the overlay is open. Kept
    in one helper so no overlay hand-rolls the attribute set.
    """
    return (
        f'{frame_position_attr(position)} '
        f'data-overlay-id="{_e(overlay_id)}" '
        'data-overlay-focus-trap="true"'
    )


__all__ = [
    "FRAME_POSITIONS",
    "HEADER_FURNITURE_ORDER",
    "HEADER_MARKER_CLOSE",
    "HEADER_MARKER_OPEN",
    "OVERLAY_DISMISS_CALL",
    "OVERLAY_DISMISS_INTENT",
    "frame_position_attr",
    "overlay_frame_header",
    "overlay_frame_root_attrs",
]
