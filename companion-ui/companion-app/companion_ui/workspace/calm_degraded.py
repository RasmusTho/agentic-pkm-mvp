"""Calm degraded grammar + runtime-enum/identifier humanisation map (CUIDR-01).

Single source of the Companion UI's degraded/unavailable/error *copy*. Every
user-facing surface that needs to say "this is unavailable / partial / failed"
reads from one grammar template here, and every runtime enum or internal
identifier passes through one humanising map before it reaches HTML.

Hard constraint (presentation only): this module does NOT classify state. It
never decides *whether* a surface is degraded, stale, blocked, or unavailable —
that classification is server-authoritative and arrives in the runtime payload.
This module only maps the runtime-declared *display token* to human copy, and
fails closed (raw token suppressed) when a token is unknown. The classified
value still travels in ``data-*`` attributes on the rendered element so the
runtime declaration remains observable; only the visible copy is humanised.

The grammar template:

    "<what> unavailable — <why>. <nothing-clause>. <what to do>."

where ``<nothing-clause>`` is one of "Nothing was lost", "Nothing was decided",
or "Nothing was mutated" depending on the surface's write posture.
"""

from __future__ import annotations

import re
from typing import Final

# ---------------------------------------------------------------------------
# Nothing-clause vocabulary (the calm degraded voice — a deliberate commitment).
# ---------------------------------------------------------------------------
NOTHING_LOST: Final[str] = "Nothing was lost"
NOTHING_DECIDED: Final[str] = "Nothing was decided"
NOTHING_MUTATED: Final[str] = "Nothing was mutated"

_NOTHING_CLAUSES: Final[frozenset[str]] = frozenset(
    {NOTHING_LOST, NOTHING_DECIDED, NOTHING_MUTATED}
)

# Fail-closed fallback used when a runtime degraded-reason token is unknown.
# The raw token is never surfaced; the calm voice is preserved.
FAIL_CLOSED_DEGRADED: Final[str] = (
    "… unavailable — details withheld. Nothing was lost."
)

# ---------------------------------------------------------------------------
# Runtime-enum / internal-identifier → human-copy map.
#
# Covers the confirmed leak tokens from the deep review (REVIEW_RESPONSE.txt
# §03/§04 C3, D3). The value is the *display* string; the classified value
# itself still arrives from the runtime payload and is preserved in data-*.
# ---------------------------------------------------------------------------
_ENUM_MAP: Final[dict[str, str]] = {
    "resurfacing_source_unavailable": "Orientation source unavailable",
    "orientation_unavailable": "Orientation unavailable",
    "orientation_source_unavailable": "Orientation source unavailable",
    "lifecycle.move": "Move note",
}

# Internal identifiers that must never appear as user-facing copy. They are
# correlation IDs, not labels — suppress them in copy and let the calling site
# fall back to the artefact/proposal description. The raw value is still allowed
# in data-* attributes (server-authoritative correlation), which this map does
# not touch.
_SUPPRESS_ID_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"^prop-[\w.-]+$"),
    re.compile(r"^proposal-[\w.-]+$"),
    re.compile(r"^art-[\w.-]+$"),
    re.compile(r"^artifact-[\w.-]+$"),
    re.compile(r"^note-[\w.-]+$"),
)


def _is_suppressed_identifier(token: str) -> bool:
    return any(pattern.match(token) for pattern in _SUPPRESS_ID_PATTERNS)


def calm_degraded(
    what: str,
    why: str,
    nothing_clause: str = NOTHING_LOST,
    what_to_do: str = "",
) -> str:
    """Render the one calm degraded-copy grammar.

    Produces ``"<what> unavailable — <why>. <nothing-clause>. <what to do>."``.

    This is the *sole* code path that emits unavailable/error copy on any
    user-facing surface. No surface may inline its own unavailable-state string
    literal.

    ``nothing_clause`` defaults to "Nothing was lost"; pass NOTHING_DECIDED or
    NOTHING_MUTATED for surfaces with a different write posture. An unrecognised
    nothing-clause falls back to "Nothing was lost" so the voice stays calm.
    ``what_to_do`` is optional (e.g. "Refresh to retry."); when omitted the
    sentence ends after the nothing-clause.
    """
    what = (what or "Something").strip()
    why = (why or "details withheld").strip()
    clause = nothing_clause if nothing_clause in _NOTHING_CLAUSES else NOTHING_LOST
    # Normalise an accidental trailing period on the why-clause.
    why = why.rstrip(".")
    sentence = f"{what} unavailable — {why}. {clause}."
    action = (what_to_do or "").strip()
    if action:
        action = action.rstrip(".")
        sentence = f"{sentence} {action}."
    return sentence


def humanise_token(token: object) -> str:
    """Map a single runtime enum / identifier to human-facing copy.

    - A known enum returns its mapped human copy.
    - A ``prop-*`` / ``art-*`` / ``note-*``-style internal identifier returns the
      empty string (suppressed — the caller uses the artefact/proposal
      ``description`` instead). The raw id is never returned.
    - Any other value (a legitimate, already-human action class such as
      ``bounded.panel_action``, or free-text) passes through unchanged.

    This is the general humanisation map used before a classified *label* token
    reaches a user surface. It does NOT fail closed for arbitrary strings — only
    for the degraded-reason path (see :func:`humanise_degraded_reason`), where an
    unknown token must collapse to the calm fallback rather than leak.
    """
    text = "" if token is None else str(token).strip()
    if not text:
        return ""
    if text in _ENUM_MAP:
        return _ENUM_MAP[text]
    if _is_suppressed_identifier(text):
        return ""
    return text


def humanise_degraded_reason(token: object) -> str:
    """Map a runtime degraded-reason token to human copy, failing closed.

    Known reason enums map to their human copy. An unknown / unmapped token does
    NOT leak: it collapses to :data:`FAIL_CLOSED_DEGRADED`
    ("… unavailable — details withheld. Nothing was lost.").
    """
    text = "" if token is None else str(token).strip()
    if not text:
        return FAIL_CLOSED_DEGRADED
    mapped = _ENUM_MAP.get(text)
    if mapped is not None:
        return mapped
    # Suppressed identifiers and unknown tokens both fail closed.
    return FAIL_CLOSED_DEGRADED


def is_mapped_token(token: object) -> bool:
    """True when ``token`` has an explicit entry in the enum map."""
    text = "" if token is None else str(token).strip()
    return text in _ENUM_MAP
