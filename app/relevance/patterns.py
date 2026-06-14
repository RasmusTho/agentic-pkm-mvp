"""User-declared patterns — soft guidance for the attention loop.

A declared pattern expresses "when I'm in *this* context, surface *that*"
(``docs/plans/CONTEXTUAL_RELEVANCE_ENGINE.md`` §3.2). Patterns are **soft bias**,
never rigid rules: they can nudge a moment's effective urgency up (so it earns a
reach-out) or suppress it (defer it), but they never force an external effect and
never touch the deterministic gate or the zero-tolerance floor. The emergent /
learned pattern loop is an explicit follow-on, not this slice.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.relevance.schema import URGENCY_ORDER, Moment, UrgencyBand, urgency_rank


@dataclass(frozen=True)
class DeclaredPattern:
    """A human-declared soft-guidance rule for surfacing."""

    name: str
    when_state: str | None = None
    match_trigger_kind: str | None = None
    match_ref_prefix: str | None = None
    urgency_boost: int = 0
    suppress: bool = False


@dataclass(frozen=True)
class PatternEffect:
    """The net soft-guidance effect on a single moment."""

    effective_band: UrgencyBand
    applied: tuple[str, ...]
    suppressed: bool


def matches(pattern: DeclaredPattern, moment: Moment, state: str) -> bool:
    """Return whether a pattern applies to a moment in the current state."""

    if pattern.when_state is not None and pattern.when_state.strip().lower() != state:
        return False
    if pattern.match_trigger_kind is not None and moment.trigger.kind != pattern.match_trigger_kind:
        return False
    if pattern.match_ref_prefix is not None and not any(
        ref.ref.startswith(pattern.match_ref_prefix) for ref in moment.surfaced_refs
    ):
        return False
    return True


def apply_patterns(
    moment: Moment, patterns: tuple[DeclaredPattern, ...], state: str
) -> PatternEffect:
    """Compute a moment's effective urgency after soft-guidance patterns."""

    rank = urgency_rank(moment.urgency.band)
    applied: list[str] = []
    suppressed = False
    for pattern in patterns:
        if not matches(pattern, moment, state):
            continue
        applied.append(pattern.name)
        if pattern.suppress:
            suppressed = True
        rank = max(0, min(len(URGENCY_ORDER) - 1, rank + pattern.urgency_boost))
    return PatternEffect(
        effective_band=URGENCY_ORDER[rank],
        applied=tuple(applied),
        suppressed=suppressed,
    )


__all__ = ["DeclaredPattern", "PatternEffect", "apply_patterns", "matches"]
