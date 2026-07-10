"""Single derived workspace vault-reachability posture (#3361).

DESIGN_AUDIT.md (`companion-ui/design_handoff/2026-07-07-uat-design-audit/
DESIGN_AUDIT.md`) §3.1 / top-10 #1 — bugs B1/B2/B5: the same runtime health
was described four contradictory ways (topbar said "vault ok" while the rail
said "degraded" and the browser said "read-only fallback"), the degraded path
invented a false "Initialize this vault" CTA on a live vault, and raw errno /
DNS transport strings leaked into user-facing copy.

This module is the SINGLE derivation point for the vault-*reachability* axis
("is my vault OK right now?"): every consuming surface (topbar chip, the one
calm banner, the calm error copy, and the vault picker's "reconnecting"
variant) calls `derive_vault_posture` and renders from its output; none of
them classifies vault reachability independently.

Deliberately narrower than the pre-existing `_compute_primary_posture` /
`COARSE_VAULT_POSTURES` writeguard+canvas posture (#1260, `overlay_host.py`)
— that is a different axis (the safety/write posture) and stays out of this
module's scope (DESIGN_AUDIT.md §3.1's "rail lane copy" is explicitly Slice B
/ out of scope for #3361).
"""

from __future__ import annotations

import json

WORKSPACE_VAULT_POSTURES: tuple[str, ...] = ("healthy", "degraded")

# The one reachability classification: which vault_state values count as
# reachable. Shared with `overlay_host.coarse_vault_posture` so the two
# posture consumers can never diverge on a future vault_state value.
REACHABLE_VAULT_STATES: frozenset[str] = frozenset({"ok"})

# Transport-level failure markers that classify an *unstructured* error
# string as "the runtime itself is unreachable" (#3361, DESIGN_AUDIT.md §3.1
# bug B2). Single shared constant consumed (via
# ``is_runtime_unreachable_error`` below) by BOTH
# `serve_dev_page._render_error_section` / `_is_runtime_unreachable` AND
# `entry_state._is_runtime_unavailable_error` — the entry-state mirror must
# stay in lockstep, otherwise a DNS failure renders unreachable *copy* while
# the entry state still resolves `shell_active` and drops the Retry /
# System-map affordances.
#
# The markers are error-SHAPED phrases, not bare topic words (round-2 review
# finding): ordinary prose can legitimately contain "network" ("Note not
# found for Notes/Network Diagram.md") or "errno" as a note-path fragment,
# and a bare-substring match would misclassify a note-load failure as the
# runtime being down. Real transport failures always carry one of the
# phrases below ("[Errno 61] Connection refused", "Network is unreachable",
# "The read operation timed out", "Temporary failure in name resolution").
TRANSPORT_UNAVAILABLE_MARKERS: tuple[str, ...] = (
    "connection refused",
    "timed out",
    "timeouterror",
    "connecttimeout",
    "readtimeout",
    "timeout of ",
    "timeout exceeded",
    "network is unreachable",
    "network error",
    "networkerror",
    "network failure",
    "[errno",
    "name or service not known",
    "nodename nor servname",
    "name resolution",
)

# The single calm sentence every degraded vault-reachability surface shows.
# Never a second, independently-worded banner (DESIGN_AUDIT.md §3.1 fix).
CALM_RECONNECT_BANNER_TEXT = (
    "Some features are paused while the vault reconnects. Reading and "
    "capture still work."
)

# The single calm sentence for an unstructured (errno/DNS/transport) error —
# replaces raw exception text (e.g. "[Errno -2] Name or service not known")
# on any user-facing entry/error surface (DESIGN_AUDIT.md §6 copy table).
CANT_REACH_VAULT_COPY = "Can't reach the vault right now. Retrying…"

# Vault-picker "reconnecting" copy (redesigns.html §3, "After — configured
# vault, no false CTA").
RECONNECTING_PICKER_TITLE = "Open a vault"
RECONNECTING_PICKER_SUB = (
    "Your configured vault is reconnecting. Open it now, or browse for "
    "another."
)


def error_detail(error: str) -> dict:
    """The structured ``detail`` dict from an ``HTTP <code>: {json}`` error.

    The workspace HTTP client wraps contract errors as
    ``HTTP <status>: <body>`` (``WorkspaceClientHTTPError``); the body's
    ``detail`` object carries the server-declared ``error`` kind. Anything
    else — plain prose, transport exception text — yields ``{}``.
    """
    if not error.startswith("HTTP "):
        return {}
    _, _, maybe_json = error.partition(": ")
    if not maybe_json:
        return {}
    try:
        payload = json.loads(maybe_json)
    except json.JSONDecodeError:
        return {}
    detail = payload.get("detail")
    return detail if isinstance(detail, dict) else {}


def is_runtime_unreachable_error(error: str) -> bool:
    """The ONE classifier for "this error means the runtime is unreachable".

    Consumed by both ``serve_dev_page`` (error copy + vault-setup-form
    suppression) and ``entry_state`` (no_vault resolution) so the two can
    never diverge (#3361 round-2 review finding — the entry-state mirror
    previously lacked the structured-error short-circuit and re-classified a
    note-load failure whose text happened to contain a transport word).

    Classification, in order:

    - empty error: not unreachable;
    - declared ``runtime_unavailable`` kind or a bare ``HTTP 503``: unreachable;
    - any OTHER declared error kind (``note_not_found``, ...): NOT a
      transport failure, no matter what words its user data contains — a
      note_not_found payload for ``Network/Runbook.md`` must never classify
      as the runtime being down;
    - otherwise (unstructured exception/transport text): unreachable iff it
      carries one of the error-shaped :data:`TRANSPORT_UNAVAILABLE_MARKERS`.
    """
    if not error:
        return False
    detail = error_detail(error)
    error_kind = str(detail.get("error") or "")
    lowered = error.lower()
    if error_kind == "runtime_unavailable" or lowered.startswith("http 503"):
        return True
    if error_kind:
        return False
    return any(marker in lowered for marker in TRANSPORT_UNAVAILABLE_MARKERS)


def vault_state_from_provenance(vault_provenance: str) -> str:
    """The three-way ``vault_state`` from the server-declared provenance.

    ``"unreachable"`` / ``"unresolved"`` pass through; every other declared
    provenance (``"resolved"``, ``"runtime"``, ...) is ``"ok"``. This is the
    ONE place that classification happens (#3361 review finding 1): the
    topbar chip and the calm banner must both consume a posture derived from
    this same value, never re-derive it from different inputs.
    """
    lowered = str(vault_provenance).lower()
    if lowered == "unreachable":
        return "unreachable"
    if lowered == "unresolved":
        return "unresolved"
    return "ok"


def derive_vault_posture(vault_state: str) -> str:
    """Derive the single vault-reachability posture from the server-declared
    ``vault_state`` (``"ok"`` / ``"unreachable"`` / ``"unresolved"``).

    ``"ok"`` -> ``"healthy"``. Anything else — including an out-of-contract
    value the runtime did not declare — fails closed to ``"degraded"``
    rather than inventing a third posture or defaulting to healthy.
    """
    if vault_state in REACHABLE_VAULT_STATES:
        return "healthy"
    return "degraded"


def vault_posture_chip_suffix(posture: str) -> str:
    """The topbar chip's posture suffix text (after the vault name).

    healthy -> ``"vault ok"``; degraded -> ``"reconnecting"`` (redesigns.html
    §3 "After" topbar frame: ``Niflheim · reconnecting``, no "vault" word).
    """
    return "vault ok" if posture == "healthy" else "reconnecting"


def render_posture_banner(posture: str) -> str:
    """The ONE calm banner for degraded vault posture.

    Empty string when healthy — no surface renders a second, independently
    worded banner for the same underlying signal (DESIGN_AUDIT.md §3.1).
    """
    if posture == "healthy":
        return ""
    return (
        '<div class="workspace-vault-unreachable-banner" '
        'data-testid="workspace-vault-unreachable-banner" '
        f'data-posture="{posture}">'
        f"<span>{CALM_RECONNECT_BANNER_TEXT}</span>"
        '<a href="#workspace-runtime-status" class="banner-retry-link" '
        'data-testid="workspace-vault-retry">retry</a>'
        "</div>"
    )
