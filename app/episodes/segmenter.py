"""Stub Episode segmenter entrypoint (ERE-01, #3176; body lands with ERE-04, #3179).

Scope (ERE-01, per the governing Issue): this module is *not* the
segmentation logic (out of scope, ERE-04) -- it is the enforced call-site
contract that segmentation-logic slice must build on top of.
:func:`run_segmenter_stub` / :func:`enumerate_consumable_streams` are the
production entrypoint asserted by AC5: the engine enumerates its stream
sources **only** via ``app.episodes.stream_registry`` -- never a hardcoded
list -- and an attempt to consume an unregistered or non-`live` stream_id is
rejected at this call site, not merely possible to reject in a unit test of
the registry module in isolation.
"""

from __future__ import annotations

from typing import Sequence

from app.episodes.stream_registry import (
    STATUS_LIVE,
    StreamRegistry,
    StreamRegistryEntry,
    UnregisteredStreamError,
    load_registry,
)


def enumerate_consumable_streams(
    stream_ids: Sequence[str] | None = None,
    *,
    registry: StreamRegistry | None = None,
) -> tuple[StreamRegistryEntry, ...]:
    """The segmenter's one legal way to learn which streams to consume.

    - With no ``stream_ids``: returns every ``live`` registry entry
      (registry-driven enumeration, never a hardcoded source list).
    - With explicit ``stream_ids``: resolves each one through the registry
      and raises :class:`UnregisteredStreamError` for any id that is not a
      registered ``live`` stream -- the entrypoint never silently consumes
      an unregistered or non-live source.
    """
    reg = registry if registry is not None else load_registry()
    if stream_ids is None:
        return reg.live_entries()

    resolved: list[StreamRegistryEntry] = []
    for stream_id in stream_ids:
        entry = reg.get(stream_id)
        if entry is None:
            raise UnregisteredStreamError(
                f"segmenter entrypoint: stream_id {stream_id!r} is not in the stream registry"
            )
        if entry.status != STATUS_LIVE:
            raise UnregisteredStreamError(
                f"segmenter entrypoint: stream_id {stream_id!r} is status={entry.status!r}, not live -- "
                "the engine may not consume a non-live registry entry"
            )
        resolved.append(entry)
    return tuple(resolved)


def run_segmenter_stub(
    *,
    stream_ids: Sequence[str] | None = None,
    registry: StreamRegistry | None = None,
) -> tuple[StreamRegistryEntry, ...]:
    """Stub production entrypoint (ERE-04 fills in real segmentation logic).

    Enumerates its consumers strictly via :func:`enumerate_consumable_streams`
    -- this is the call site AC5 asserts against.
    """
    return enumerate_consumable_streams(stream_ids, registry=registry)


__all__ = [
    "enumerate_consumable_streams",
    "run_segmenter_stub",
]
