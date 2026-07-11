"""Fused Episode id minting (ADR-0051; ERE-02 AC4).

The fused ``episode_id`` (``ep-<uuid>``) is a *different identifier space* from Heimdal's
per-capture-session ``episode_id`` (FABLE_COMPANION §1.3: "groups observations from one
continuous capture session"). Heimdal's contract fixes no id shape for that session id --
it is adapter-chosen, arbitrary-string, and never carries the ``ep-`` prefix by contract.
That asymmetry is exactly what makes the two spaces disjoint: any id honoring the fused
shape below is *never* a raw Heimdal session id, and this module additionally rejects the
degenerate case where a caller tries to echo a supplied raw id directly into the fused
``episode_id`` field (defense in depth, not just format luck).

Heimdal's per-session id is a legitimate *input* to an episode note -- it belongs in
``derived_from`` as a single-stream boundary hint (ADR-0051 §5 amendment) -- it must never
be promoted, unchanged, into the note's own ``episode_id``.
"""

from __future__ import annotations

import re
from uuid import uuid4

EPISODE_ID_PREFIX = "ep-"

# ep-<uuid4 canonical form>. Anchored so a partial/embedded match cannot pass.
_FUSED_EPISODE_ID_RE = re.compile(
    r"^ep-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class EpisodeIdCollisionError(ValueError):
    """Raised when an episode_id would collide with the Heimdal per-session id space."""


def mint_episode_id() -> str:
    """Mint a fresh fused episode id, disjoint-by-construction from Heimdal session ids."""
    return f"{EPISODE_ID_PREFIX}{uuid4()}"


def is_fused_episode_id(candidate: str) -> bool:
    """Whether ``candidate`` has the fused ``ep-<uuid>`` shape."""
    return bool(_FUSED_EPISODE_ID_RE.match(candidate))


def validate_fused_episode_id(
    candidate: str,
    *,
    derived_from: list[str] | None = None,
) -> None:
    """Reject an ``episode_id`` that is not fused-shaped or that echoes a raw Heimdal
    session id supplied as a ``derived_from`` boundary hint on the same note.

    Two independent checks, both load-bearing (ERE-02 AC4):

    1. **Shape.** A non-``ep-<uuid>`` string is, by definition, not a fused id -- it is
       either malformed or (most concerningly) a raw Heimdal session id being reused
       directly. Heimdal never mints ``ep-`` prefixed ids, so this check alone makes the
       two spaces disjoint by construction for any store-minted id.
    2. **Self-derivation.** Even a well-shaped id must not appear in its own
       ``derived_from`` list -- an episode cannot derive from itself, and this is the
       concrete collision the AC calls out: "store rejects an id that echoes a raw
       Heimdal session id" supplied as a boundary hint.
    """
    if not isinstance(candidate, str) or not is_fused_episode_id(candidate):
        raise EpisodeIdCollisionError(
            f"episode_id {candidate!r} is not a fused id (ep-<uuid>); a raw Heimdal "
            "per-session episode_id must never be promoted directly into this field "
            "(ADR-0051; ERE-02 AC4) -- record it in derived_from instead"
        )
    for raw in derived_from or []:
        if raw == candidate:
            raise EpisodeIdCollisionError(
                f"episode_id {candidate!r} echoes a derived_from entry; a fused episode "
                "note may derive from a Heimdal session id but must never reuse it as "
                "its own episode_id"
            )


__all__ = [
    "EPISODE_ID_PREFIX",
    "EpisodeIdCollisionError",
    "is_fused_episode_id",
    "mint_episode_id",
    "validate_fused_episode_id",
]
