"""Read-only admission seam for the future governed interest overlay.

The eventual YouTube overlay renderer owns evidence connections and language
policy.  This module only admits an already-governed ProfileAgent projection
for an explicitly bound consumer scope; it has no profile write or inference
path.
"""

from __future__ import annotations

from pathlib import Path

from app.knowledge.profile_consumer_projection import (
    ProfileConsumerProjection,
    rebuild_profile_projection,
)


def admit_profile_for_interest_overlay(
    vault_root: Path | str,
    *,
    active_scope_id: str | None,
) -> ProfileConsumerProjection:
    """Admit only the governed same-scope profile projection for #4117."""

    return rebuild_profile_projection(vault_root, active_scope_id=active_scope_id)


def read_governed_profile_for_overlay(
    vault_root: Path | str,
    *,
    active_scope_id: str | None,
) -> ProfileConsumerProjection:
    """Named read-only production adapter used by the future overlay renderer."""

    return admit_profile_for_interest_overlay(
        vault_root,
        active_scope_id=active_scope_id,
    )


__all__ = [
    "admit_profile_for_interest_overlay",
    "read_governed_profile_for_overlay",
]
