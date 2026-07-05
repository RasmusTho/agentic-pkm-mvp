"""Heimdal observation log + publish path (#3039, Epic #3019 slice A2).

Covers the issue's three behavioral Acceptance Criteria:

- ``test_append_only_enforced`` — any attempt to update or delete an
  existing observation row is rejected; only append succeeds.
- ``test_per_consumer_cursor_read`` — two independent consumers each
  advance their own cursor and read the full log independently; one
  consumer's progress does not affect the other.
- ``test_idempotency_key_dedup_and_revision`` — re-publishing the same
  evidence yields the same ``derive_idempotency_key`` and does not create a
  duplicate row; a revision produces a new, distinct key.

Default (``not pg``) tests drive the real production call site: the memory
backend's store has no update/delete method anywhere in its public API (the
only mutation path in this module's contract), so the enforcement is
structural, not simulated. ``test_append_only_enforced_pg`` additionally
exercises the actual Postgres trigger against a real database (``pg``
marker), proving the DB-level defense-in-depth independently of the Python
API -- a hand-written SQL UPDATE/DELETE against the table is rejected by the
database itself, not merely "no caller happens to expose it".
"""

from __future__ import annotations

import uuid

import pytest

from app.events.schema import make_outbox_event
from app.heimdal import observation_log
from app.heimdal.observation_log import (
    ObservationLogSchemaMissingError,
    append_observation,
    count_observations,
    read_observations_from,
    reset_memory_observation_log,
)
from app.heimdal.cursor_store import (
    advance_cursor,
    get_cursor,
    reset_memory_cursor_store,
)
from app.heimdal.publish import (
    advance_cursor_for_consumer,
    consume_observations,
    derive_observation_idempotency_key,
    observation_fingerprint,
    publish_observation,
    read_observations_for_consumer,
)
from app.services.outbox import derive_idempotency_key

pytestmark = pytest.mark.not_pg


@pytest.fixture(autouse=True)
def _reset_heimdal_stores():
    reset_memory_observation_log()
    reset_memory_cursor_store()
    yield
    reset_memory_observation_log()
    reset_memory_cursor_store()


def _publish(observation_id: str, *, text: str = "hello", stage_versions: dict | None = None):
    return publish_observation(
        topic="heimdal.observation.published",
        observation_id=observation_id,
        payload={"observation_id": observation_id, "content": text},
        source="heimdal.capture",
        stage_versions=stage_versions or {"asr": "1.0", "attribution": "1.0"},
    )


# --- AC1: append-only enforced -------------------------------------------------


def test_append_only_enforced() -> None:
    """Only append succeeds; there is no update/delete path anywhere in the API.

    Drives the real production call site: `append_observation` is the only
    write entrypoint the module exposes (mirrored by `publish_observation`,
    the actual producer-facing seam). We assert structurally that no
    mutation method exists on the module or the backend object it resolves,
    and behaviorally that appending twice with different keys never
    overwrites the first row -- the log only grows.
    """
    row1 = _publish("obs-1", text="first")
    assert row1 is not None
    assert count_observations() == 1

    row2 = _publish("obs-2", text="second")
    assert row2 is not None
    assert count_observations() == 2

    # The original row's content is untouched by the second append.
    rows = read_observations_from(0)
    assert len(rows) == 2
    assert rows[0].envelope["payload"]["content"] == "first"
    assert rows[1].envelope["payload"]["content"] == "second"

    # No update/delete surface exists on the public module API (structural
    # enforcement -- the real production call site has nothing to invoke).
    assert not hasattr(observation_log, "update_observation")
    assert not hasattr(observation_log, "delete_observation")
    assert not hasattr(observation_log, "update")
    assert not hasattr(observation_log, "delete")

    public_names = set(observation_log.__all__)
    mutating_names = {name for name in public_names if "update" in name or "delete" in name}
    assert mutating_names == set(), f"unexpected mutation surface exported: {mutating_names}"


def test_append_only_enforced_direct_backend_has_no_mutation_method() -> None:
    """The resolved backend object itself carries no update/delete method.

    Negative/completeness path: even reaching past the module-level
    functions into the backend instance `append_observation` delegates to
    exposes no way to mutate a row.
    """
    backend = observation_log._backend()
    assert not hasattr(backend, "update")
    assert not hasattr(backend, "delete")
    assert not hasattr(backend, "update_observation")
    assert not hasattr(backend, "delete_observation")


@pytest.mark.pg
def test_append_only_enforced_pg() -> None:
    """Real Postgres trigger rejects UPDATE/DELETE at the database level (HEIM-1).

    Exercises the actual production migration path (`_bootstrap_pg` /
    the `8b21e6a1f0c4` migration's trigger), against a real database --
    not a fake/stub connection. A hand-written SQL statement against the
    table (bypassing this module's API entirely) is still rejected by the
    database itself: defense in depth beyond "the Python API has no
    update/delete method".
    """
    pytest.importorskip("psycopg")

    # Real Postgres rows persist across separate test runs (unlike the
    # memory backend, which the autouse fixture resets) -- a unique
    # observation_id per invocation avoids colliding with a prior run's
    # idempotency key and being (correctly) deduped away as "no new row".
    unique_id = f"obs-pg-{uuid.uuid4()}"
    row = _publish(unique_id, text="pg-first")
    assert row is not None

    conn = observation_log._pg_connect()
    try:
        cur = conn.cursor()
        with pytest.raises(Exception) as excinfo:
            cur.execute(
                f"UPDATE {observation_log._TABLE} SET topic = 'tampered' WHERE id = %s",
                (row.id,),
            )
        assert "append-only" in str(excinfo.value).lower() or "HEIM-1" in str(excinfo.value)

        with pytest.raises(Exception) as excinfo_del:
            cur.execute(f"DELETE FROM {observation_log._TABLE} WHERE id = %s", (row.id,))
        assert "append-only" in str(excinfo_del.value).lower() or "HEIM-1" in str(excinfo_del.value)
    finally:
        conn.close()

    # The row survived both attempted mutations, untouched.
    rows = read_observations_from(row.sequence)
    matching = [r for r in rows if r.id == row.id]
    assert len(matching) == 1
    assert matching[0].envelope["payload"]["content"] == "pg-first"


# --- AC2: per-consumer cursor read ---------------------------------------------


def test_per_consumer_cursor_read() -> None:
    """Two independent consumers each advance their own cursor over the log.

    One consumer's progress must not affect the other's, and a brand-new
    consumer_id must be able to read the full log from event zero.
    """
    for i in range(5):
        assert _publish(f"obs-{i}") is not None
    assert count_observations() == 5

    # Consumer A reads and advances through the first 2 events.
    batch_a1 = consume_observations("mimer-projector", limit=2)
    assert [r.sequence for r in batch_a1] == [0, 1]
    assert get_cursor("mimer-projector") == 2

    # Consumer B has never been seen: it starts at 0 and can read everything,
    # independent of consumer A's progress.
    assert get_cursor("second-consumer") == 0
    batch_b_full = read_observations_for_consumer("second-consumer")
    assert [r.sequence for r in batch_b_full] == [0, 1, 2, 3, 4]

    # Consumer A's cursor is unaffected by consumer B merely reading (reads
    # do not mutate the cursor until explicitly advanced).
    assert get_cursor("mimer-projector") == 2

    # Advance consumer B fully; consumer A's position is still untouched.
    advance_cursor_for_consumer("second-consumer", batch_b_full)
    assert get_cursor("second-consumer") == 5
    assert get_cursor("mimer-projector") == 2

    # Consumer A resumes from where it left off, reading only what remains.
    batch_a2 = consume_observations("mimer-projector")
    assert [r.sequence for r in batch_a2] == [2, 3, 4]
    assert get_cursor("mimer-projector") == 5


def test_cursor_advance_is_monotone_and_isolated_per_consumer() -> None:
    """advance_cursor never moves a cursor backwards, and never touches another consumer's row."""
    advance_cursor("alpha", 3)
    assert get_cursor("alpha") == 3

    # A stale/out-of-order advance to an earlier position is a no-op.
    advance_cursor("alpha", 1)
    assert get_cursor("alpha") == 3

    # A different consumer_id remains at its own default (0), unaffected.
    assert get_cursor("beta") == 0
    advance_cursor("beta", 1)
    assert get_cursor("alpha") == 3
    assert get_cursor("beta") == 1


def test_cursor_rejects_invalid_input() -> None:
    with pytest.raises(ValueError):
        get_cursor("")
    with pytest.raises(ValueError):
        advance_cursor("", 1)
    with pytest.raises(ValueError):
        advance_cursor("consumer", -1)


# --- AC3: idempotency key dedup + revision -------------------------------------


def test_idempotency_key_dedup_and_revision() -> None:
    """Re-publish of the same evidence dedups; a revision produces a new row."""
    first = _publish("obs-dedup", text="same content", stage_versions={"asr": "1.0"})
    assert first is not None
    assert count_observations() == 1

    # Exact re-publish (crash-retry of the same evidence, same stage
    # versions): same derived key, no duplicate row.
    second = _publish("obs-dedup", text="same content", stage_versions={"asr": "1.0"})
    assert second is None
    assert count_observations() == 1

    # A revision (improved stage_versions over the SAME observation_id and
    # content) must derive a DISTINCT key and produce a genuinely new row.
    revised = _publish("obs-dedup", text="same content", stage_versions={"asr": "2.0"})
    assert revised is not None
    assert count_observations() == 2
    assert revised.idempotency_key != first.idempotency_key

    # A correction (same observation_id, different payload content) is also
    # a new, distinct row.
    corrected = _publish("obs-dedup", text="corrected content", stage_versions={"asr": "1.0"})
    assert corrected is not None
    assert count_observations() == 3


def test_derive_observation_idempotency_key_matches_shared_helper() -> None:
    """The Heimdal-specific derivation is the shared KERNEL-02 helper, not a fork."""
    fingerprint = observation_fingerprint({"observation_id": "o-1", "content": "x"})
    key = derive_observation_idempotency_key(
        topic="heimdal.observation.published",
        observation_id="o-1",
        content_fingerprint=fingerprint,
    )
    expected = derive_idempotency_key("heimdal.observation.published", "o-1", fingerprint)
    assert key == expected


def test_observation_fingerprint_changes_with_stage_versions() -> None:
    payload = {"observation_id": "o-2", "content": "same"}
    fp_v1 = observation_fingerprint(payload, stage_versions={"asr": "1.0"})
    fp_v1_again = observation_fingerprint(dict(payload), stage_versions={"asr": "1.0"})
    fp_v2 = observation_fingerprint(payload, stage_versions={"asr": "2.0"})

    assert fp_v1 == fp_v1_again
    assert fp_v1 != fp_v2


def test_publish_observation_rejects_bad_topic_and_id() -> None:
    with pytest.raises(ValueError):
        publish_observation(
            topic="not.heimdal.family",
            observation_id="o-1",
            payload={},
            source="test",
        )
    with pytest.raises(ValueError):
        publish_observation(
            topic="heimdal.observation.published",
            observation_id="",
            payload={},
            source="test",
        )


def test_append_observation_requires_idempotency_key() -> None:
    envelope = make_outbox_event(
        "heimdal.observation.published",
        source="test",
        payload={"observation_id": "o-1"},
    )
    with pytest.raises(ValueError):
        append_observation(envelope, idempotency_key="")
    with pytest.raises(ValueError):
        append_observation(envelope, idempotency_key="   ")


def test_read_observations_from_rejects_negative_sequence() -> None:
    with pytest.raises(ValueError):
        read_observations_from(-1)


def test_pg_backend_schema_missing_is_fail_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Postgres backend never silently no-ops on a missing/undropped schema.

    Simulates the pg-selected, autocreate-disabled path by calling the
    assert helper directly against a stub connection with no table --
    mirrors the KERNEL-05 outbox precedent (`OutboxSchemaMissingError`).
    """

    class _StubCursor:
        def execute(self, *_args, **_kwargs):
            return self

        def fetchone(self):
            return (None,)

    class _StubConn:
        def cursor(self):
            return _StubCursor()

    with pytest.raises(ObservationLogSchemaMissingError):
        observation_log._assert_pg_schema(_StubConn())
