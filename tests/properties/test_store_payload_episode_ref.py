"""Store-payload episode_ref census (ERE-05, #3180 -- invariant->producers enforcement).

episode_ref is vault-canonical (ERE-03): every producer that rebuilds a note's DB-side
``store_objects``/``store_vector_index`` payload and writes it with full-overwrite semantics MUST
carry episode_ref forward, or a reingest / cold rebuild blind-drops a stamped binding and retrieval
reverts to ``unbound`` (docs/EPISODE_RESOLUTION_ENGINE/ASSIGN_EPISODE_REF_TO_ARTIFACTS.md). The
round-2 and round-3 re-reviews of PR #3520 each found a producer that had missed the carry (first
``vault_alpha.py``, then ``vault_root.py`` + ``alpha_human_flows.py``), so the per-producer patches
alone proved fragile. This census is the real structural fix.

Two gates, mirroring the existing ``tests/properties`` census tests
(``test_mirror_census_is_closed`` / ``test_every_write_note_relative_seam_has_port_coverage``):

- ``test_store_payload_sink_census_is_closed``: every store-payload sink call site
  (``ingest_object``/``index_ingest_object`` and any ``.put(payload=...)``) is classified with a
  one-line justification -- a NEW unclassified sink fails here.
- ``test_every_store_payload_producer_carries_episode_ref``: every site classified as a producer
  (``carries_*``) is shown, statically, to include an ``episode_ref`` key in the payload it passes
  -- a producer that drops the key fails here even if it is registered.
"""

from __future__ import annotations

from tests.properties._machinery import (
    HARNESS_EXCLUDED_FILES,
    STORE_PAYLOAD_PRODUCER_PREFIXES,
    STORE_PAYLOAD_SINK_CLASSIFICATION,
    _STORE_PAYLOAD_ALL_PREFIXES,
    find_store_payload_sink_sites,
    payload_keys_at_sink,
)


def test_store_payload_sink_census_is_closed() -> None:
    """Every store-payload sink call site in ``app/`` is a classified entry -- a NEW unregistered
    sink (the next silent-drop regression) fails instead of shipping, mirroring
    ``test_mirror_census_is_closed``. Adding the call is not enough; the same PR must add a
    one-line justification to ``STORE_PAYLOAD_SINK_CLASSIFICATION``."""
    sites = find_store_payload_sink_sites()
    assert sites, "expected at least the known production store-payload sink sites"

    unregistered = [key for key in sites if key not in STORE_PAYLOAD_SINK_CLASSIFICATION]
    assert not unregistered, (
        "Unregistered store-payload sink call site(s) found -- classify each in "
        "STORE_PAYLOAD_SINK_CLASSIFICATION (tests/properties/_machinery.py) with a one-line "
        f"justification before merging: {unregistered}"
    )

    live = set(sites)
    stale = [key for key in STORE_PAYLOAD_SINK_CLASSIFICATION if key not in live]
    assert not stale, (
        "STORE_PAYLOAD_SINK_CLASSIFICATION has stale entries no longer matching a real sink "
        f"call site (line drift or removed site): {stale}"
    )

    bad = [
        (key, value)
        for key, value in STORE_PAYLOAD_SINK_CLASSIFICATION.items()
        if not value.startswith(_STORE_PAYLOAD_ALL_PREFIXES)
    ]
    assert not bad, (
        f"Every classification must start with one of {_STORE_PAYLOAD_ALL_PREFIXES}: {bad}"
    )


def test_every_store_payload_producer_carries_episode_ref() -> None:
    """Every ``carries_*`` producer's payload includes an ``episode_ref`` key (checked statically
    -- following the payload variable / ``**unpack`` to its dict literal). A registered producer
    that drops the key still fails here: this is the gate that catches the round-2/round-3
    durability bug at its structural root, not per-producer whack-a-mole."""
    offenders: list[tuple[str, int, str]] = []
    for (rel, line), classification in sorted(STORE_PAYLOAD_SINK_CLASSIFICATION.items()):
        prefix = classification.split(":", 1)[0]
        if prefix not in STORE_PAYLOAD_PRODUCER_PREFIXES:
            continue
        keys = payload_keys_at_sink(rel, line)
        if keys is None:
            offenders.append((rel, line, "payload arg could not be statically resolved"))
        elif "episode_ref" not in keys:
            offenders.append((rel, line, f"payload has no episode_ref key (keys={sorted(keys)})"))
    assert not offenders, (
        "store-payload producer(s) missing an episode_ref carry -- every carries_* site must "
        "include episode_ref in the payload it writes (ERE-03/ERE-05 invariant->producers): "
        f"{offenders}"
    )


def test_harness_excluded_files_are_not_treated_as_producers() -> None:
    """Sanity: any sink in a harness-excluded file (formal-model.md §2.3) is classified
    ``harness_excluded``, never a producer -- so the harness seeder is never held to the
    episode_ref carry and never silently exempts a real producer either."""
    for (rel, line), classification in STORE_PAYLOAD_SINK_CLASSIFICATION.items():
        if rel in HARNESS_EXCLUDED_FILES:
            assert classification.startswith("harness_excluded"), (
                f"{rel}:{line} is harness-excluded but classified {classification!r}"
            )
