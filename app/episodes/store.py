"""Guarded write seam for Episode notes (ERE-02; ADR-0051 OD-1/OD-2; #2910 guard-at-seam
precedent).

Two write classes are kept explicit and are never blurred (INV-ERE-B):

- Every write -- regardless of ``segmentation`` -- goes through the same guarded knowledge-write
  seam (``app.knowledge.write_ops.write_note_relative``), action ``episodes.write_note``. That
  function asserts ``WriteGuard.assert_writes_allowed(action)`` *inside the port itself*, before
  any path resolution or filesystem mutation (guard-at-seam), so a blocked write is atomic --
  zero bytes touched -- regardless of caller. This is the health/fail-closed gate every
  vault-write seam must assert.
- ``segmentation: proposed`` is a low-trust opt-out proposal (ADR-0051 §5): it never goes through
  ``app.governance.governed_write`` (no ``PolicyDecision`` / ``DecisionToken`` / ``AuthorityReceipt``).
  Canonical standing for an episode arrives via silent acceptance or human re-cut (ERE-07), not a
  governed transition -- so this module has no governance import at all, by construction, not just
  by convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.episodes.ids import mint_episode_id, validate_fused_episode_id
from app.episodes.notes import episode_note_rel_path, render_episode_note
from app.episodes.schema import validate_episode_note_fields
from app.knowledge.contracts import WriteReceipt
from app.knowledge.write_ops import write_note_relative
from app.write_guard import DEFAULT_WRITE_GUARD, WriteGuard

# Distinct action string for the episode write seam (mirrors the
# knowledge.write_note / memory.materialize per-seam-action pattern), asserted by
# write_note_relative itself -- not a caller-side helper (AC2: enforcement lives at the
# production seam).
EPISODE_WRITE_ACTION = "episodes.write_note"

_ALLOWED_SEGMENTATIONS = ("proposed", "accepted", "re-cut")


class EpisodeStoreError(ValueError):
    """Raised when an episode note write is rejected before reaching the write seam."""


@dataclass(frozen=True)
class EpisodeWriteResult:
    """Result of a guarded episode-note write. Deliberately carries only a
    ``WriteReceipt`` -- never a ``DecisionToken``/``AuthorityReceipt`` -- so a proposal-class
    write is structurally incapable of looking like a governed mutation (AC3)."""

    receipt: WriteReceipt
    episode_id: str
    fields: dict[str, Any]


def write_episode_note(
    *,
    title: str,
    scope: str,
    start: str,
    closed: bool = False,
    end: str | None = None,
    space: list[str] | None = None,
    protagonists: list[str] | None = None,
    goal: list[str] | None = None,
    causation: list[str] | None = None,
    parent_episode: str | None = None,
    segmentation: str = "proposed",
    derived_from: list[str] | None = None,
    episode_id: str | None = None,
    vault_root: Path | str,
    write_guard: WriteGuard = DEFAULT_WRITE_GUARD,
) -> EpisodeWriteResult:
    """Write a vault-canonical episode note through the guarded seam.

    ``episode_id`` defaults to a freshly minted fused id (``ep-<uuid>``, disjoint-by-construction
    from Heimdal's per-session id space); an explicit ``episode_id`` is still validated against
    the same disjointness rule (AC4) so no caller can smuggle a raw Heimdal session id through.
    """
    if segmentation not in _ALLOWED_SEGMENTATIONS:
        raise EpisodeStoreError(
            f"segmentation must be one of {_ALLOWED_SEGMENTATIONS}, got {segmentation!r}"
        )

    derived = list(derived_from or [])
    eid = episode_id if episode_id is not None else mint_episode_id()
    validate_fused_episode_id(eid, derived_from=derived)

    fields: dict[str, Any] = {
        "episode_id": eid,
        "scope": scope,
        "title": title,
        "time": {"start": start, "closed": closed, **({"end": end} if end else {})},
        "space": list(space or []),
        "protagonists": list(protagonists or []),
        "goal": list(goal or []),
        "causation": list(causation or []),
        "parent_episode": parent_episode,
        "segmentation": segmentation,
        "derived_from": derived,
    }
    # Schema validation (AC1) happens before the write seam is even reached -- a
    # malformed note is rejected with zero filesystem mutation, same as a blocked guard.
    validate_episode_note_fields(fields)

    content = render_episode_note(fields)
    rel_path = episode_note_rel_path(eid)

    # Guard-at-seam (#2910 precedent): write_note_relative asserts
    # write_guard.assert_writes_allowed(EPISODE_WRITE_ACTION) itself, before any path
    # resolution or filesystem mutation -- this call IS the production seam AC2 verifies,
    # not a caller-side check that could be bypassed by a different call path. No
    # governance import anywhere in this module: a proposal-class write reaches only this
    # seam and produces only a WriteReceipt (AC3).
    receipt = write_note_relative(
        rel_path,
        content,
        vault_root=vault_root,
        action=EPISODE_WRITE_ACTION,
        write_guard=write_guard,
    )
    return EpisodeWriteResult(receipt=receipt, episode_id=eid, fields=fields)


__all__ = [
    "EPISODE_WRITE_ACTION",
    "EpisodeStoreError",
    "EpisodeWriteResult",
    "write_episode_note",
]
