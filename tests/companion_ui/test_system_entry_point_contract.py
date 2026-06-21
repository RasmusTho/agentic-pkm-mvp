"""Contract checks for the Companion UI system entry-point spec."""

from __future__ import annotations

import re
from pathlib import Path


def _declared_intents() -> set[str]:
    spec = Path("companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md").read_text(encoding="utf-8")
    table = spec.split("## Intent vocabulary (NORMATIVE)", 1)[1].split("Reserved,", 1)[0]
    return set(re.findall(r"`([^`]+)`", table))


def test_recents_open_intent_is_declared() -> None:
    assert "recents.open" in _declared_intents()


def test_recents_open_is_allowed_cold_start_transition() -> None:
    spec = Path("companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md").read_text(encoding="utf-8")
    transitions = spec.split("### Allowed transitions", 1)[1].split(
        "### Overlay-grammar rule",
        1,
    )[0]

    cold_start_transition = next(
        line for line in transitions.splitlines() if line.startswith("cold_start")
    )
    assert "recents.open" in cold_start_transition
