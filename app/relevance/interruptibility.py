"""Context-dependent interruption threshold for the reach-out/scarcity gate.

Implements the deterministic threshold of
``docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md``: a per-rung minimum
urgency band keyed on the human's current interruptibility, with a
non-negotiable zero-tolerance floor (sleep / declared do-not-disturb). The
tolerance *curve* is seeded here and may later be learned; the comparison and the
floor stay deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.relevance.schema import UrgencyBand

# Sleep / declared do-not-disturb: zero tolerance — never reach out, regardless
# of urgency. A hard, deterministic floor; not a learned preference.
ZERO_TOLERANCE_STATES = frozenset({"sleep", "dnd", "do-not-disturb", "do_not_disturb"})

# Seeded tolerance curve: interruptibility state -> (in_app_min, push_min).
# Higher cognitive load => higher bar. ``None`` means the rung is unreachable.
_SEEDED_CURVE: dict[str, tuple[UrgencyBand | None, UrgencyBand | None]] = {
    "home": ("timely", "pressing"),
    "low": ("timely", "pressing"),
    "focus": ("pressing", "critical"),
    "high": ("pressing", "critical"),
    "meeting": ("critical", None),
}
# Default-to-silence when interruptibility is uncertain or unrecognized: hold
# *all* gated rungs unreachable (``None``), not merely a high band. Per the
# reach-out contract (REACHOUT_AND_SCARCITY_GATE_CONTRACT.md :: Interruption
# threshold), an uncertain reading must yield silence — a ("pressing","critical")
# bar still permits in-app/push on a pressing/critical moment, which violates the
# default direction. Only the glance (pull) floor remains available.
_DEFAULT_CURVE: tuple[UrgencyBand | None, UrgencyBand | None] = (None, None)


@dataclass(frozen=True)
class InterruptibilityThreshold:
    """The reach-out bar for the current context. ``None`` rung = unreachable."""

    state: str
    in_app_min: UrgencyBand | None
    push_min: UrgencyBand | None
    zero_tolerance: bool = False


def threshold_for(state: str | None) -> InterruptibilityThreshold:
    """Return the deterministic interruption threshold for an interruptibility state."""

    norm = (state or "unknown").strip().lower()
    if norm in ZERO_TOLERANCE_STATES:
        return InterruptibilityThreshold(
            state=norm, in_app_min=None, push_min=None, zero_tolerance=True
        )
    in_app_min, push_min = _SEEDED_CURVE.get(norm, _DEFAULT_CURVE)
    return InterruptibilityThreshold(state=norm, in_app_min=in_app_min, push_min=push_min)


def coerce_threshold(value: str | InterruptibilityThreshold | None) -> InterruptibilityThreshold:
    """Accept either an interruptibility state name or a pre-built threshold."""

    if isinstance(value, InterruptibilityThreshold):
        return value
    return threshold_for(value)


__all__ = [
    "InterruptibilityThreshold",
    "ZERO_TOLERANCE_STATES",
    "threshold_for",
    "coerce_threshold",
]
