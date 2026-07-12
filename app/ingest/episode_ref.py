"""Shared episode_ref projection helper for store-payload producers (ERE-05, #3180).

``episode_ref`` is vault-canonical (ERE-03): the ERE-05 assignment seam
(``app.episodes.assignment``) stamps it on a note's OWN frontmatter, and every producer that
rebuilds the note's DB-side ``store_objects``/``store_vector_index`` payload MUST carry it forward
so a reingest / cold rebuild reprojects the binding instead of blind-dropping it (retrieval reads
``payload['episode_ref']`` -- an absent key silently reverts a stamped note to ``unbound``). This is
the invariant->producers rule; the round-2 and round-3 re-reviews both found a producer that had
missed it, so the carry logic is single-sourced here and every producer imports it (never a local
copy that can drift).

The enforcement census ``tests/properties/test_store_payload_episode_ref.py`` fails if a
store-payload producer is added without carrying ``episode_ref``.
"""

from __future__ import annotations

from typing import Any, Mapping

# episode_ref string sentinels (schemas/_defs.schema.json :: episode_ref). Mirrors
# app.retrieval.envelope._EPISODE_REF_SENTINELS / mimer_runtime.metadata.EPISODE_REF_SENTINELS
# (each layer keeps its own copy of this tiny closed set rather than importing across a boundary).
EPISODE_REF_SENTINELS = frozenset({"unbound", "pending"})

#: The honest default for a producer with no episode binding available (a fresh capture, an
#: external raw source, a note whose frontmatter carries none): "no episode is known"
#: (docs/architecture/semantic-dimensions.md :: episode_ref).
UNBOUND = "unbound"


def episode_ref_from_frontmatter(frontmatter: Mapping[str, Any] | None) -> str | list[str]:
    """Project a note's vault-canonical ``episode_ref`` from its frontmatter into a DB payload.

    Only schema-valid shapes cross -- the ``unbound``/``pending`` sentinels or a non-empty list of
    non-empty ``episode_id`` strings; anything absent/malformed falls back to the honest
    :data:`UNBOUND` default (same posture as ``app.retrieval.envelope._episode_ref_from_payload``:
    never fail ingest on a dirty value, never smuggle an out-of-shape one). Pass ``None``/``{}`` for
    a producer that has no frontmatter at all (e.g. an external raw source) to get :data:`UNBOUND`.
    """
    value = (frontmatter or {}).get("episode_ref")
    if isinstance(value, str) and value in EPISODE_REF_SENTINELS:
        return value
    if isinstance(value, (list, tuple)) and value and all(isinstance(x, str) and x for x in value):
        return list(value)
    return UNBOUND


__all__ = ["EPISODE_REF_SENTINELS", "UNBOUND", "episode_ref_from_frontmatter"]
