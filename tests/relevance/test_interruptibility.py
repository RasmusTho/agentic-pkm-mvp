"""Regression tests for the interruptibility threshold default (#2015).

The reach-out contract (``docs/CONCEPTS/REACHOUT_AND_SCARCITY_GATE_CONTRACT.md``
:: Interruption threshold) mandates default-to-silence: "When interruptibility is
**uncertain, the gate holds to the higher threshold** (silence)." An unknown or
unrecognized interruptibility reading must therefore hold *all* gated rungs
unreachable, not merely raise the bar to ``pressing``/``critical`` (which still
permits in-app/push on a pressing/critical moment).
"""

from __future__ import annotations

from app.relevance.interruptibility import threshold_for


def test_unknown_state_defaults_to_silence() -> None:
    """Unknown/unrecognized interruptibility holds every gated rung unreachable."""

    for state in (None, "unknown", "", "not-a-real-state", "sensor-gap"):
        threshold = threshold_for(state)
        assert threshold.in_app_min is None, f"{state!r}: in-app rung must be unreachable"
        assert threshold.push_min is None, f"{state!r}: push rung must be unreachable"


def test_known_states_still_resolve_rungs() -> None:
    """Recognized states keep their seeded curve (no over-broad silencing)."""

    home = threshold_for("home")
    assert home.in_app_min == "timely"
    assert home.push_min == "pressing"

    meeting = threshold_for("meeting")
    assert meeting.in_app_min == "critical"
    assert meeting.push_min is None
