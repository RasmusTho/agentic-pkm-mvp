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

WORKSPACE_VAULT_POSTURES: tuple[str, ...] = ("healthy", "degraded")

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


def derive_vault_posture(vault_state: str) -> str:
    """Derive the single vault-reachability posture from the server-declared
    ``vault_state`` (``"ok"`` / ``"unreachable"`` / ``"unresolved"``).

    ``"ok"`` -> ``"healthy"``. Anything else — including an out-of-contract
    value the runtime did not declare — fails closed to ``"degraded"``
    rather than inventing a third posture or defaulting to healthy.
    """
    if vault_state == "ok":
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
