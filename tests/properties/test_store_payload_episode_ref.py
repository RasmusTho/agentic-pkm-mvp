"""Store-payload episode_ref census (ERE-05, #3180 -- invariant->producers enforcement).

episode_ref is vault-canonical (ERE-03): every producer that writes a note's DB-side
``store_objects`` / ``store_vector_index`` payload MUST carry episode_ref, or a stamped binding is
blind-dropped and retrieval reverts to ``unbound`` (docs/EPISODE_RESOLUTION_ENGINE/
ASSIGN_EPISODE_REF_TO_ARTIFACTS.md). Rounds 2/3/4 of PR #3520 each found a producer the previous
census missed; round 4 CLOSED the scanner gap.

**Scanner method coverage (round-4 meta-fix).** ``find_store_payload_sink_sites`` recognizes EVERY
store-payload sink method name -- ``put``, ``upsert``, ``save_object``, ``ingest_object``,
``index_ingest_object`` (``_SINK_METHOD_NAMES``). The round-3 scanner recognized only
``put``/``ingest_object`` and so was blind to the ``save_object`` facade
(``app/objects/__init__.py``) and the ``upsert`` protocol method
(``app/stores/base.py::VectorIndex``/``ObjectsStore``) -- which is exactly why two live producers
(``services/indexer.py::handle_ingest_object_created`` on POST /ingest, and
``knowledge_acquisition/raw_record.py``) dropped episode_ref while the census passed.
``test_scanner_recognizes_all_store_write_methods`` locks the method set.

**Three gates:**
- ``test_store_payload_sink_census_is_closed`` -- every sink site is classified with a
  justification; a NEW unclassified sink fails.
- ``test_every_store_payload_producer_carries_episode_ref`` -- every PRODUCER site is verified by
  the check its classification names (dict-literal key / builder-choke / preserve).
- ``test_build_indexed_unit_payload_always_sets_episode_ref`` -- the structural choke that backs the
  ``carries_via_indexed_unit_builder`` classification: every store_vector_index payload routed
  through the builder carries episode_ref (present preserved, absent -> honest 'unbound').

**Proof-of-bite (verified manually during round-4 implementation, for EACH method name):**
temporarily deleting the episode_ref carry at a ``save_object`` producer
(``knowledge_acquisition/raw_record.py``) OR at an ``index_ingest_object`` producer
(``ingest/external.py``) OR at an ``upsert`` producer's builder input makes
``test_every_store_payload_producer_carries_episode_ref`` fail with that site enumerated; restoring
it passes. The gate bites for put/upsert/save_object/ingest_object/index_ingest_object alike.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from app.index.artifact_metadata import build_indexed_unit_payload
from tests.properties._machinery import (
    HARNESS_EXCLUDED_FILES,
    STORE_PAYLOAD_CARRIES_DICT_PREFIXES,
    STORE_PAYLOAD_PRODUCER_PREFIXES,
    STORE_PAYLOAD_SINK_CLASSIFICATION,
    _SINK_METHOD_NAMES,
    _STORE_PAYLOAD_ALL_PREFIXES,
    find_store_payload_sink_sites,
    payload_keys_at_sink,
    payload_source_blob,
)


def _prefix(classification: str) -> str:
    return classification.split(":", 1)[0]


def test_scanner_recognizes_all_store_write_methods() -> None:
    """The scanner recognizes EVERY store-payload sink method (round-4 meta-fix). If a new store
    write primitive is added to app/stores/base.py or the app/objects facade, add its method name
    here AND teach the scanner, or producers reached through it silently escape the census (the
    round-3 failure mode: only put/ingest_object were recognized)."""
    assert _SINK_METHOD_NAMES == frozenset(
        {"put", "upsert", "save_object", "ingest_object", "index_ingest_object"}
    )


def test_store_payload_sink_census_is_closed() -> None:
    """Every store-payload sink call site in ``app/`` is a classified entry -- a NEW unregistered
    sink fails instead of shipping, mirroring ``test_mirror_census_is_closed``."""
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
    """Every PRODUCER site carries episode_ref, verified by the check its classification names:

    - ``carries_frontmatter`` / ``carries_unbound_default`` / ``carries_normalized``: the
      statically-resolved payload dict includes an ``episode_ref`` key.
    - ``carries_via_indexed_unit_builder``: the payload traces to a ``build_indexed_unit_payload``
      call (whose episode_ref default is proven by
      ``test_build_indexed_unit_payload_always_sets_episode_ref``).
    - ``preserves_existing_payload``: the payload is built from an existing row's ``.payload`` (a
      stamped episode_ref survives the update).

    ``carries_at_construction`` producers build the payload in a separate function (opaque at the
    call site) and are verified by a named RUNTIME test (``test_normalizer_run_carries_episode_ref_
    to_store_objects``, ``test_plan_to_object_carries_episode_ref``) rather than the static resolver.

    A producer that drops episode_ref -- via ANY sink method -- fails here even if it is registered.
    """
    offenders: list[tuple[str, int, str]] = []
    for (rel, line), classification in sorted(STORE_PAYLOAD_SINK_CLASSIFICATION.items()):
        prefix = _prefix(classification)
        if prefix not in STORE_PAYLOAD_PRODUCER_PREFIXES:
            continue
        if prefix in STORE_PAYLOAD_CARRIES_DICT_PREFIXES:
            keys = payload_keys_at_sink(rel, line)
            if keys is None or "episode_ref" not in keys:
                offenders.append((rel, line, f"payload dict has no episode_ref key (keys={keys})"))
        elif prefix == "carries_via_indexed_unit_builder":
            blob = payload_source_blob(rel, line) or ""
            if "build_indexed_unit_payload" not in blob:
                offenders.append((rel, line, "payload does not trace to build_indexed_unit_payload"))
        elif prefix == "preserves_existing_payload":
            blob = payload_source_blob(rel, line) or ""
            if ".payload" not in blob:
                offenders.append((rel, line, "payload is not built from an existing row's .payload"))
        elif prefix == "carries_at_construction":
            # opaque at the call site; verified by the named runtime tests below. Assert only that
            # the classification points at a runtime test (so the escape hatch is not free-form).
            if "Verified by" not in classification and "verified by" not in classification:
                offenders.append((rel, line, "carries_at_construction must name a runtime test"))
    assert not offenders, (
        "store-payload producer(s) missing an episode_ref carry -- every producer must carry "
        "episode_ref by the mechanism its classification names (ERE-03/ERE-05 invariant->producers)"
        f": {offenders}"
    )


def test_no_non_producer_escape_hatches() -> None:
    """Round-5 structural hardening: the ONLY non-producer classifications are
    ``transport_passthrough`` (forwards a verified caller payload) and ``harness_excluded``. The
    round-4 ``not_store_object_payload`` / ``superseded_by_store_put`` labels are GONE -- they hid a
    real store_objects producer (vault_root's objects_store.upsert). So every sink that is not a
    verified forward/harness MUST be a producer that carries/preserves/builds episode_ref; there is
    no 'this isn't really a payload' hand-wave left to hide behind."""
    allowed_non_producer = {"transport_passthrough", "harness_excluded"}
    for (rel, line), classification in STORE_PAYLOAD_SINK_CLASSIFICATION.items():
        prefix = _prefix(classification)
        assert prefix in STORE_PAYLOAD_PRODUCER_PREFIXES or prefix in allowed_non_producer, (
            f"{rel}:{line} classified {prefix!r} -- must be a producer or one of {allowed_non_producer}; "
            "no not_store_object_payload/superseded escape hatch (round-5)"
        )


def test_normalizer_run_carries_episode_ref_to_store_objects(tmp_path: Path) -> None:
    """carries_at_construction verification: the normalizer's payload (built cross-function in
    normalize_file) carries the note's vault-canonical episode_ref, so its save_object -> store_objects
    write never blind-drops a stamped binding (round-5)."""
    from app.agents.normalizer.agent import normalize_file

    bound = tmp_path / "bound.md"
    bound.write_text(
        "---\nuuid: 11111111-1111-4111-8111-111111111111\ntitle: t\nepisode_ref:\n  - ep-x\n---\n\nbody\n",
        encoding="utf-8",
    )
    dom = normalize_file(str(bound), trace_id="t")
    assert dom["payload"]["episode_ref"] == ["ep-x"]

    unbound = tmp_path / "unbound.md"
    unbound.write_text("---\nuuid: 22222222-2222-4222-8222-222222222222\ntitle: t\n---\n\nbody\n", encoding="utf-8")
    dom2 = normalize_file(str(unbound), trace_id="t")
    assert dom2["payload"]["episode_ref"] == "unbound"


def test_plan_to_object_carries_episode_ref() -> None:
    """carries_at_construction verification: a Plan's store_objects payload carries the honest
    'unbound' sentinel (a Plan never originates in an episode)."""
    from app.domain.plan import Plan

    plan = Plan(uuid="plan-1", parent_plan=None, depth=0, goal="g", status="planned")
    assert plan.to_object().payload["episode_ref"] == "unbound"


def test_build_indexed_unit_payload_always_sets_episode_ref() -> None:
    """The structural choke behind ``carries_via_indexed_unit_builder``: every store_vector_index
    payload RETRIEVAL reads is built here, so this builder must ALWAYS emit episode_ref -- a present
    schema-valid binding preserved, anything absent/malformed defaulted to the honest 'unbound'
    (never dropped, never overwriting a real binding with 'unbound')."""
    oid = uuid.uuid4()
    base = dict(object_id=oid, kind="note", source_ref="x", text="hi")

    assert build_indexed_unit_payload(payload={"title": "t"}, **base)["episode_ref"] == "unbound"
    assert build_indexed_unit_payload(payload={}, **base)["episode_ref"] == "unbound"
    assert build_indexed_unit_payload(payload=None, **base)["episode_ref"] == "unbound"
    assert build_indexed_unit_payload(payload={"episode_ref": ["ep-1", "ep-2"]}, **base)[
        "episode_ref"
    ] == ["ep-1", "ep-2"]
    assert build_indexed_unit_payload(payload={"episode_ref": "pending"}, **base)["episode_ref"] == "pending"
    assert build_indexed_unit_payload(payload={"episode_ref": "bogus"}, **base)["episode_ref"] == "unbound"


def test_harness_excluded_files_are_not_treated_as_producers() -> None:
    """Any sink in a harness-excluded file (formal-model.md §2.3) is classified
    ``harness_excluded``, never a producer."""
    for (rel, line), classification in STORE_PAYLOAD_SINK_CLASSIFICATION.items():
        if rel in HARNESS_EXCLUDED_FILES:
            assert classification.startswith("harness_excluded"), (
                f"{rel}:{line} is harness-excluded but classified {classification!r}"
            )
