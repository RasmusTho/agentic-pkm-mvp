"""Shared production defaults for the evidence-bound acquisition pipeline."""

from __future__ import annotations


# The old ``summary`` extractor remains available for explicit legacy callers, but production
# acquisition and replay must not silently publish its free-text output.
DEFAULT_EXTRACTOR_IDS: tuple[str, ...] = ("synthesis", "claims")


def resolve_extractor_ids(
    extractor_ids: tuple[str, ...] | list[str],
    extractor_requirements: dict[str, str] | None,
) -> tuple[str, ...]:
    """Preserve the pre-anchored shorthand for explicit summary policies.

    Before anchored synthesis became the production default, callers could provide only
    ``extractor_requirements={"summary": ...}`` and rely on the summary default implicitly.
    Keep that persisted-policy shape readable while making every unqualified call anchored.
    """
    selected = tuple(extractor_ids)
    if selected == DEFAULT_EXTRACTOR_IDS and extractor_requirements is not None:
        if set(extractor_requirements) == {"summary"}:
            return ("summary",)
    return selected


__all__ = ["DEFAULT_EXTRACTOR_IDS", "resolve_extractor_ids"]
