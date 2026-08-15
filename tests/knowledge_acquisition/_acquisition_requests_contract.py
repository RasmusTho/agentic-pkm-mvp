"""YSS-04 (#3919): shared service-layer contract for the acquisition queue.

The SAME behavioral assertions run against the memory backend (implicitly via
`test_acquisition_requests.py`'s AC tests) and the real Postgres backend
(`test_acquisition_requests_pg.py`) — proving the queue semantics hold
identically on both backends (AC7), mirroring
`_source_registry_contract.py`'s pattern.

Every assertion uses unique synthetic item refs (INV-YSS-9: no real ids) so
the suite is self-contained against a shared database.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import pytest

from app.knowledge_acquisition.acquisition_requests import (
    ACQUISITION_FAILED_TOPIC,
    ACQUISITION_REQUESTED_TOPIC,
    ACQUISITION_STARTED_TOPIC,
    DEFAULT_MAX_ATTEMPTS,
    AcquisitionRequests,
    DiscoveryTrigger,
    request_identity,
)


class _FakeCursor:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeOutboxConn:
    """In-memory outbox emulating the keyed insert's PK-conflict dedup.

    The ONE shared fake for this suite: the memory-backend AC tests and the pg
    parity suite must exercise identical outbox semantics, so there is exactly
    one emulation to keep in sync with the real insert shape.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}

    def execute(self, sql: str, params: tuple = ()) -> _FakeCursor:
        text = " ".join(sql.lower().split())
        if text.startswith("insert into outbox (id,"):
            assert "on conflict (id) do nothing" in text
            row_id, topic, payload, created_at, attempts, legacy_key, vault_binding_id, *_ = params
            if row_id in self.rows:
                return _FakeCursor([])
            self.rows[row_id] = {
                "id": row_id,
                "topic": topic,
                "payload": payload,
                "created_at": created_at,
                "attempts": attempts,
                "legacy_key": legacy_key,
                "vault_binding_id": vault_binding_id,
            }
            return _FakeCursor([(row_id,)])
        raise AssertionError(f"unexpected SQL shape reached the outbox: {text!r}")

    def close(self) -> None:  # pragma: no cover - psycopg parity
        pass

    def rows_for(self, topic: str) -> list[dict[str, Any]]:
        return [r for r in self.rows.values() if r["topic"] == topic]

    def payloads_for(self, topic: str) -> list[dict[str, Any]]:
        import json as _json

        return [_json.loads(r["payload"])["payload"] for r in self.rows_for(topic)]


MakeQueue = Callable[[], AcquisitionRequests]


def _item() -> str:
    return uuid.uuid4().hex[:11]


def _trigger(**overrides: Any) -> DiscoveryTrigger:
    defaults: dict[str, Any] = dict(
        binding_id=str(uuid.uuid4()),
        collection_kind="owned_playlist",
        collection_ref="PL__test__contract",
        trigger="poll",
    )
    defaults.update(overrides)
    return DiscoveryTrigger(**defaults)


def _enqueue(q: AcquisitionRequests, conn: FakeOutboxConn, item: str, **kw: Any):
    return q.enqueue(
        source_kind="youtube_url",
        item_ref=item,
        source_ref=f"https://www.youtube.com/watch?v={item}",
        trigger=kw.pop("trigger", _trigger()),
        conn=conn,
        **kw,
    )


def _terminalize(q: AcquisitionRequests, conn: FakeOutboxConn, *rows: Any) -> None:
    """Leave no claimable rows behind: each assertion runs against a shared
    database in the pg parity suite, so a leftover pending/in_progress row from
    one assertion must never leak into the next one's claim ordering."""
    for row in rows:
        current = q.get(row.request_id)
        if current is not None and current.status in ("pending", "in_progress"):
            q.dead_letter(
                row.request_id,
                expected_attempt=(current.attempts if current.status == "in_progress" else None),
                reason_code="pipeline_dead_letter",
                error="contract cleanup",
                conn=conn,
            )


def assert_identity_and_trigger_merge(make_queue: MakeQueue) -> None:
    q = make_queue()
    conn = FakeOutboxConn()
    item = _item()
    t1, t2 = _trigger(), _trigger(collection_kind="inbox_playlist")

    r1 = _enqueue(q, conn, item, trigger=t1)
    r2 = _enqueue(q, conn, item, trigger=t2)
    assert r1.request_id == r2.request_id == request_identity("youtube_url", item, 1)
    assert len(r2.discovery_triggers) == 2
    assert {t["binding_id"] for t in r2.discovery_triggers} == {t1.binding_id, t2.binding_id}
    # Identical re-discovery converges without unbounded growth.
    r3 = _enqueue(q, conn, item, trigger=t1)
    assert len(r3.discovery_triggers) == 2
    assert len(conn.rows_for(ACQUISITION_REQUESTED_TOPIC)) == 1
    _terminalize(q, conn, r1)


def assert_durable_completed_lifecycle(make_queue: MakeQueue) -> None:
    q = make_queue()
    conn = FakeOutboxConn()
    item = _item()
    row = _enqueue(q, conn, item)
    assert row.status == "pending"
    assert row.attempts == 0
    assert row.completed_at is None

    # A fresh service instance sees the same durable row (restart durability).
    q2 = make_queue()
    reloaded = q2.get(row.request_id)
    assert reloaded is not None and reloaded.status == "pending"

    claimed = q2.claim_batch(10, conn=conn)
    claimed_ids = [c.request_id for c in claimed]
    assert row.request_id in claimed_ids
    mine = next(c for c in claimed if c.request_id == row.request_id)
    assert mine.status == "in_progress"
    assert mine.attempts == 1
    assert conn.rows_for(ACQUISITION_STARTED_TOPIC)

    done = q2.complete(
        row.request_id,
        expected_attempt=mine.attempts,
        content_identity="cid-contract",
        artifact_path="inbox/n.md",
        conn=conn,
    )
    assert done.status == "completed"
    assert done.completed_at is not None
    assert done.content_identity == "cid-contract"
    assert done.artifact_path == "inbox/n.md"

    # Late duplicate discovery never reopens a terminal request.
    late = _enqueue(q2, conn, item)
    assert late.status == "completed"
    _terminalize(q2, conn, *claimed)


def assert_claim_order_and_backoff_gate(make_queue: MakeQueue) -> None:
    q = make_queue()
    conn = FakeOutboxConn()
    now = datetime.now(timezone.utc)

    older_normal = _enqueue(q, conn, _item(), priority="normal", now=now)
    high = _enqueue(q, conn, _item(), priority="high", now=now + timedelta(seconds=1))
    newer_normal = _enqueue(q, conn, _item(), priority="normal", now=now + timedelta(seconds=2))

    order = [r.request_id for r in q.claim_batch(3, now=now + timedelta(seconds=3), conn=conn)]
    assert order == [high.request_id, older_normal.request_id, newer_normal.request_id]

    # Backoff gate: a failed attempt is not claimable before next_attempt_at.
    q.fail(
        high.request_id,
        expected_attempt=q.get(high.request_id).attempts,
        reason_code="network_error",
        error="transient",
        now=now,
        conn=conn,
    )
    gated = q.get(high.request_id)
    assert gated.status == "pending"
    assert gated.next_attempt_at is not None
    assert q.claim_batch(5, now=now + timedelta(seconds=30), conn=conn) == []
    reclaim = q.claim_batch(5, now=now + timedelta(hours=7), conn=conn)
    assert high.request_id in [r.request_id for r in reclaim]
    _terminalize(q, conn, older_normal, high, newer_normal)


def assert_retry_then_exhaustion_dead_letter(make_queue: MakeQueue) -> None:
    q = make_queue()
    conn = FakeOutboxConn()
    row = _enqueue(q, conn, _item())
    # Moving clock: each iteration jumps a day, always past the ≤6 h backoff
    # gate the previous fail() set (fail at t gates retry at t + backoff).
    t = datetime.now(timezone.utc)
    for _ in range(DEFAULT_MAX_ATTEMPTS):
        t = t + timedelta(days=1)
        claimed = q.claim_batch(1, now=t, conn=conn)
        assert [c.request_id for c in claimed] == [row.request_id]
        q.fail(
            row.request_id,
            expected_attempt=claimed[0].attempts,
            reason_code="network_error",
            error="down",
            now=t,
            conn=conn,
        )
    final = q.get(row.request_id)
    assert final.status == "dead_lettered"
    assert final.attempts == DEFAULT_MAX_ATTEMPTS
    assert final.last_failure["reason_code"] == "network_error"
    assert conn.rows_for(ACQUISITION_FAILED_TOPIC)


def assert_explicit_dead_letter(make_queue: MakeQueue) -> None:
    q = make_queue()
    conn = FakeOutboxConn()
    row = _enqueue(q, conn, _item())
    claimed = q.claim_batch(1, conn=conn)[0]
    q.dead_letter(
        row.request_id,
        expected_attempt=claimed.attempts,
        reason_code="pipeline_dead_letter",
        error="stage",
        conn=conn,
    )
    final = q.get(row.request_id)
    assert final.status == "dead_lettered"
    assert final.last_failure["reason_code"] == "pipeline_dead_letter"


def assert_reset_stale_in_progress(make_queue: MakeQueue) -> None:
    q = make_queue()
    conn = FakeOutboxConn()
    row = _enqueue(q, conn, _item())
    q.claim_batch(1, conn=conn)
    assert q.get(row.request_id).status == "in_progress"
    assert q.reset_stale_in_progress(older_than_seconds=3600) == 0
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    assert q.reset_stale_in_progress(older_than_seconds=3600, now=future) >= 1
    recovered = q.get(row.request_id)
    assert recovered.status == "pending"
    assert recovered.attempts == 1
    _terminalize(q, conn, row)


def assert_terminal_states_never_reopened(make_queue: MakeQueue) -> None:
    """INV-YSS-3: a late fail/complete from a stale drainer cannot reopen a
    terminal row, and the no-op emits no event."""
    q = make_queue()
    conn = FakeOutboxConn()

    # completed stays completed through a late fail().
    row = _enqueue(q, conn, _item())
    claimed = next(
        item for item in q.claim_batch(10, conn=conn) if item.request_id == row.request_id
    )
    q.complete(
        row.request_id,
        expected_attempt=claimed.attempts,
        content_identity="cid-terminal",
        conn=conn,
    )
    failed_before = len(conn.rows_for(ACQUISITION_FAILED_TOPIC))
    after = q.fail(
        row.request_id,
        expected_attempt=claimed.attempts,
        reason_code="network_error",
        error="stale drainer",
        conn=conn,
    )
    assert after.status == "completed"
    assert after.content_identity == "cid-terminal"
    assert len(conn.rows_for(ACQUISITION_FAILED_TOPIC)) == failed_before

    # dead_lettered stays dead_lettered through a late complete().
    row2 = _enqueue(q, conn, _item())
    claimed2 = next(
        item for item in q.claim_batch(10, conn=conn) if item.request_id == row2.request_id
    )
    q.dead_letter(
        row2.request_id,
        expected_attempt=claimed2.attempts,
        reason_code="pipeline_dead_letter",
        error="stage",
        conn=conn,
    )
    after2 = q.complete(
        row2.request_id,
        expected_attempt=claimed2.attempts,
        content_identity="cid-late",
        conn=conn,
    )
    assert after2.status == "dead_lettered"
    assert q.get(row2.request_id).content_identity is None


def assert_stale_attempt_cannot_mutate_new_in_progress_owner(make_queue: MakeQueue) -> None:
    """Attempt generation fences both memory and Postgres transition writers."""
    from app.knowledge_acquisition.acquisition_requests import (
        AcquisitionRequestValidationError,
    )

    q = make_queue()
    conn = FakeOutboxConn()
    row = _enqueue(q, conn, _item())
    attempt_one = q.claim_batch(1, conn=conn)[0]
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    assert q.reset_stale_in_progress(older_than_seconds=900, now=future) >= 1
    attempt_two = q.claim_batch(1, now=future, conn=conn)[0]
    assert attempt_two.attempts == attempt_one.attempts + 1

    with pytest.raises(AcquisitionRequestValidationError, match="stale attempt"):
        q.complete(
            row.request_id,
            expected_attempt=attempt_one.attempts,
            content_identity="cid-stale",
            conn=conn,
        )
    with pytest.raises(AcquisitionRequestValidationError, match="stale attempt"):
        q.fail(
            row.request_id,
            expected_attempt=attempt_one.attempts,
            reason_code="network_error",
            conn=conn,
        )
    with pytest.raises(AcquisitionRequestValidationError, match="stale attempt"):
        q.dead_letter(
            row.request_id,
            expected_attempt=attempt_one.attempts,
            reason_code="pipeline_dead_letter",
            conn=conn,
        )

    current = q.get(row.request_id)
    assert current is not None
    assert current.status == "in_progress"
    assert current.attempts == attempt_two.attempts
    q.dead_letter(
        row.request_id,
        expected_attempt=attempt_two.attempts,
        reason_code="pipeline_dead_letter",
        error="contract cleanup",
        conn=conn,
    )


def assert_pending_dead_letter_cannot_dispose_concurrent_claim(make_queue: MakeQueue) -> None:
    """An unowned disposition must be atomically fenced to ``pending``.

    Force the claim to land after ``dead_letter()`` observes ``pending`` but
    before the backend transition.  Both backends must reject the stale
    unowned disposition and preserve the newly claimed attempt.
    """
    from app.knowledge_acquisition.acquisition_requests import (
        AcquisitionRequestValidationError,
    )

    q = make_queue()
    conn = FakeOutboxConn()
    row = _enqueue(q, conn, _item())
    backend = q._backend  # noqa: SLF001 - deterministic backend race contract
    original = backend.set_dead_lettered
    claimed = None

    def claim_before_transition(*args: Any, **kwargs: Any):
        nonlocal claimed
        claimed = q.claim_batch(1, conn=conn)[0]
        return original(*args, **kwargs)

    backend.set_dead_lettered = claim_before_transition  # type: ignore[method-assign]
    try:
        with pytest.raises(AcquisitionRequestValidationError, match="not applicable"):
            q.dead_letter(
                row.request_id,
                reason_code="pipeline_dead_letter",
                error="unowned disposition",
                conn=conn,
            )
    finally:
        backend.set_dead_lettered = original  # type: ignore[method-assign]

    current = q.get(row.request_id)
    assert claimed is not None
    assert current is not None
    assert current.status == "in_progress"
    assert current.attempts == claimed.attempts
    q.dead_letter(
        row.request_id,
        expected_attempt=claimed.attempts,
        reason_code="pipeline_dead_letter",
        error="contract cleanup",
        conn=conn,
    )


ALL_CONTRACT_ASSERTIONS = (
    assert_identity_and_trigger_merge,
    assert_durable_completed_lifecycle,
    assert_claim_order_and_backoff_gate,
    assert_retry_then_exhaustion_dead_letter,
    assert_explicit_dead_letter,
    assert_reset_stale_in_progress,
    assert_terminal_states_never_reopened,
    assert_stale_attempt_cannot_mutate_new_in_progress_owner,
    assert_pending_dead_letter_cannot_dispose_concurrent_claim,
)
