"""Provisional Daily Briefing tunables.

These defaults live here exactly once until the Settings Spine
``SINGLE_DEFAULT_REGISTRY`` (SETTINGS-02) is delivered, at which point they
must migrate into that registry rather than being copied into call sites.
"""

BRIEFING_GENERATION_HOUR = 7
BRIEFING_TIMEZONE = "Europe/Stockholm"
BRIEFING_ENABLED = True

__all__ = [
    "BRIEFING_ENABLED",
    "BRIEFING_GENERATION_HOUR",
    "BRIEFING_TIMEZONE",
]
