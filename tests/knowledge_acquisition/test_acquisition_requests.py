"""YSS-04 (#3919): durable acquisition request queue — memory backend + drain seam.

The binding contract is `docs/YOUTUBE_SOURCE_SYNC/SOURCE_SYNC_CONTRACT.md ::
AcquisitionRequest / Event topics / Retry and backoff` and INV-YSS-1..3 in that
dir's README. All source egress is stubbed at the plugin level
(`yt_dlp_extract_info` / `fetch_caption_body` monkeypatched, per
`test_acquire.py`), the LLM extractor is stubbed via
`summary_extractor.register(complete=...)`, and the outbox is the in-memory
`FakeOutboxConn` — no real Postgres for these `not_pg` tests, but
`DATABASE_URL` must be present for `acquire_youtube`'s DB-required guard
(presence check only; the fake conn is injected).

No real playlist/channel/account identifiers anywhere (INV-YSS-9).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app import objects as object_store_module
from app.knowledge_acquisition import youtube_plugin as plugin
from app.knowledge_acquisition.acquisition_requests import (
    ACQUISITION_FAILED_TOPIC,
    ACQUISITION_REQUESTED_TOPIC,
    ACQUISITION_STARTED_TOPIC,
    DEFAULT_MAX_ATTEMPTS,
    YOUTUBE_SOURCE_DISCOVERED_TOPIC,
    AcquisitionRequests,
    DiscoveryTrigger,
    attempt_event_key,
    compute_backoff_seconds,
    drain_one,
    request_identity,
    reset_memory_acquisition_requests,
)
from app.knowledge_acquisition.extraction_registry import clear_registry
from app.knowledge_acquisition.extractors import summary_extractor
from app.services.outbox import write_outbox_event
from app.events.models import new_event
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard
from tests.knowledge_acquisition._acquisition_requests_contract import FakeOutboxConn

pytestmark = pytest.mark.not_pg

FAKE_URL = "https://www.youtube.com/watch?v=abcdefghijk"
VIDEO_ID = "abcdefghijk"

# Synthetic binding ids only (INV-YSS-9).
BINDING_INBOX = str(uuid.uuid4())
BINDING_OWNED = str(uuid.uuid4())


# --- Harness (fetch/extractor stubs mirror test_acquire.py; the outbox fake is
# the ONE shared emulation in _acquisition_requests_contract so the memory and
# pg suites always test identical outbox semantics) ---------------------------


def _stub_completion(raw: str):
    def complete(*, system: str, user: str, trace_id=None, max_tokens=None) -> str:
        return raw

    return complete


_VALID_SUMMARY = json.dumps({"summary": "A deterministic test summary.", "confidence": 0.75})


@pytest.fixture(autouse=True)
def _reset_registry():
    clear_registry()
    summary_extractor.register(complete=_stub_completion(_VALID_SUMMARY))
    yield
    clear_registry()
    summary_extractor.register()


@pytest.fixture(autouse=True)
def _memory_store(monkeypatch):
    from app.stores import reset_store_backends

    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()
    reset_memory_acquisition_requests()
    yield
    reset_store_backends()
    object_store_module._MEMORY_STORE.clear()
    reset_memory_acquisition_requests()


@pytest.fixture(autouse=True)
def _configured_db_env(monkeypatch):
    """acquire_youtube's DB-required guard checks env presence only (conn is injected)."""
    monkeypatch.setenv("DATABASE_URL", "postgresql://test:test@localhost:5432/app_test")
    yield


def _base_info(**overrides):
    info = {
        "id": VIDEO_ID,
        "title": "A Test Video",
        "channel": "Test Channel",
        "channel_id": "UC123",
        "upload_date": "20260101",
        "duration": 600,
        "description": "desc",
        "chapters": [],
        "tags": ["a", "b"],
        "language": "en",
        "thumbnail": "https://example.com/thumb.jpg",
        "subtitles": {"en": [{"ext": "vtt", "url": "https://example.com/manual.vtt"}]},
        "automatic_captions": {},
    }
    info.update(overrides)
    return info


_CAPTION_BODY = (
    "WEBVTT\n\n"
    "00:00:00.000 --> 00:00:02.000\n"
    "Hello world\n\n"
    "00:00:02.000 --> 00:00:04.000\n"
    "This is a transcript about testing.\n"
)


def _stub_caption_fetch(monkeypatch, *, info: dict[str, Any] | None = None, body: str = _CAPTION_BODY):
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info or _base_info())
    monkeypatch.setattr(plugin, "fetch_caption_body", lambda url: body)


def _vault(root: Path) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext(
        status="selected",
        active_vault_id="vault-test",
        active_vault_name="Vault Test",
        active_vault_path=str(root),
    )


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _denying_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "safe_mode", "reason": "runtime degraded (test)"})


def _trigger(binding_id: str, kind: str = "owned_playlist", **overrides) -> DiscoveryTrigger:
    defaults = dict(
        binding_id=binding_id,
        collection_kind=kind,
        collection_ref="PL__test__synthetic",
        trigger="poll",
        playlist_item_id=None,
    )
    defaults.update(overrides)
    return DiscoveryTrigger(**defaults)


def _queue() -> AcquisitionRequests:
    return AcquisitionRequests.for_runtime()


def _enqueue(q: AcquisitionRequests, conn: FakeOutboxConn, *, binding=BINDING_INBOX, kind="inbox_playlist", priority="normal", item=VIDEO_ID, **kw):
    return q.enqueue(
        source_kind="youtube_url",
        item_ref=item,
        source_ref=f"https://www.youtube.com/watch?v={item}",
        trigger=_trigger(binding, kind),
        priority=priority,
        conn=conn,
        **kw,
    )


# ---------------------------------------------------------------------------
# AC1
# ---------------------------------------------------------------------------


def test_same_video_two_sources_single_request_merged_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_caption_fetch(monkeypatch)
    conn = FakeOutboxConn()
    q = _queue()

    r1 = _enqueue(q, conn, binding=BINDING_INBOX, kind="inbox_playlist", priority="high")
    r2 = _enqueue(q, conn, binding=BINDING_OWNED, kind="owned_playlist")

    # One request, deterministic identity, both triggers preserved (INV-YSS-2).
    assert r1.request_id == r2.request_id == request_identity("youtube_url", VIDEO_ID, 1)
    assert len(r2.discovery_triggers) == 2
    assert {t["binding_id"] for t in r2.discovery_triggers} == {BINDING_INBOX, BINDING_OWNED}

    # Exactly one acquisition.requested; one discovered event per source binding.
    assert len(conn.rows_for(ACQUISITION_REQUESTED_TOPIC)) == 1
    discovered = conn.payloads_for(YOUTUBE_SOURCE_DISCOVERED_TOPIC)
    assert {d["binding_id"] for d in discovered} == {BINDING_INBOX, BINDING_OWNED}

    # End-to-end through the (stubbed-egress) production pipeline: one candidate.
    vault = _vault(tmp_path / "vault")
    claimed = q.claim_batch(1, conn=conn)
    assert [c.request_id for c in claimed] == [r1.request_id]
    result = drain_one(claimed[0], vault_context=vault, queue=q, write_guard=_allowing_guard(), conn=conn)
    assert result.status == "completed"
    assert result.content_identity
    assert result.artifact_path
    notes = list((tmp_path / "vault").rglob("*.md"))
    assert len(notes) == 1

    # Converged: nothing left to claim.
    assert q.claim_batch(5, conn=conn) == []


# ---------------------------------------------------------------------------
# AC2
# ---------------------------------------------------------------------------


def test_request_durable_before_drain_and_restart_converges(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeOutboxConn()
    q = _queue()
    row = _enqueue(q, conn)
    assert row.status == "pending"
    assert row.completed_at is None

    # Simulated restart: a fresh service instance sees the same durable row.
    q2 = AcquisitionRequests.for_runtime()
    reloaded = q2.get(row.request_id)
    assert reloaded is not None
    assert reloaded.status == "pending"
    assert reloaded.request_id == row.request_id

    # Crash between enqueue and drain: re-discovery converges to the same row.
    again = _enqueue(q2, conn)
    assert again.request_id == row.request_id
    assert len(conn.rows_for(ACQUISITION_REQUESTED_TOPIC)) == 1

    # Drain through an injected acquire seam: pipeline runs exactly once.
    calls = {"n": 0}

    def fake_acquire(url, **kwargs):
        calls["n"] += 1
        from app.knowledge_acquisition.acquire import AcquireStageReceipt, AcquisitionReceipt

        return AcquisitionReceipt(
            source_kind="youtube_url",
            item_ref=VIDEO_ID,
            raw_record_id="raw-1",
            content_identity="cid-1",
            is_new_raw=True,
            acquisition_method="captions_manual",
            stages=(AcquireStageReceipt(stage="candidate", status="written", artifact_path="inbox/x.md"),),
        )

    claimed = q2.claim_batch(1, conn=conn)
    result = drain_one(claimed[0], vault_context=None, queue=q2, conn=conn, acquire_fn=fake_acquire)
    assert result.status == "completed"
    assert result.content_identity == "cid-1"
    assert calls["n"] == 1

    # Late duplicate discovery after completion: trigger append only, no reopen,
    # no second pipeline effect.
    late = _enqueue(q2, conn, binding=BINDING_OWNED, kind="owned_playlist")
    assert late.status == "completed"
    assert q2.claim_batch(5, conn=conn) == []
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# AC3
# ---------------------------------------------------------------------------


def test_writeguard_block_reported_and_retryable_at_call_site(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_caption_fetch(monkeypatch)
    conn = FakeOutboxConn()
    q = _queue()
    vault = _vault(tmp_path / "vault")
    row = _enqueue(q, conn)

    # Production call site: drain_one -> acquire_youtube (real), WriteGuard denies.
    claimed = q.claim_batch(1, conn=conn)
    blocked = drain_one(claimed[0], vault_context=vault, queue=q, write_guard=_denying_guard(), conn=conn)

    assert blocked.status == "pending"  # retryable, never completed/dead-lettered
    assert blocked.last_failure is not None
    assert blocked.last_failure["reason_code"] == "writeguard_blocked"
    assert blocked.next_attempt_at is not None
    failed = conn.payloads_for(ACQUISITION_FAILED_TOPIC)
    assert len(failed) == 1
    assert failed[0]["terminal"] is False
    assert failed[0]["reason_code"] == "writeguard_blocked"
    assert list((tmp_path / "vault").rglob("*.md")) == []

    # A later drain (past the backoff gate) completes it.
    future = datetime.now(timezone.utc) + timedelta(hours=7)
    reclaimed = q.claim_batch(1, now=future, conn=conn)
    assert [r.request_id for r in reclaimed] == [row.request_id]
    done = drain_one(reclaimed[0], vault_context=vault, queue=q, write_guard=_allowing_guard(), conn=conn)
    assert done.status == "completed"
    assert len(list((tmp_path / "vault").rglob("*.md"))) == 1


# ---------------------------------------------------------------------------
# AC4
# ---------------------------------------------------------------------------


def test_dead_letter_item_scoped_and_attempts_exhaustion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = FakeOutboxConn()
    q = _queue()
    vault = _vault(tmp_path / "vault")

    # Item A: extractor dead-letters (invalid completion) -> pipeline_dead_letter,
    # terminal and item-scoped.
    _stub_caption_fetch(monkeypatch)
    clear_registry()
    summary_extractor.register(complete=_stub_completion("not json at all"))
    row_a = _enqueue(q, conn, item=VIDEO_ID)
    claimed = q.claim_batch(1, conn=conn)
    dead = drain_one(claimed[0], vault_context=vault, queue=q, write_guard=_allowing_guard(), conn=conn)
    assert dead.status == "dead_lettered"
    assert dead.last_failure["reason_code"] == "pipeline_dead_letter"
    failed_events = conn.payloads_for(ACQUISITION_FAILED_TOPIC)
    assert len(failed_events) == 1
    assert failed_events[0]["terminal"] is True

    # Sibling item B is unaffected and completes once the extractor is healthy.
    info_b = _base_info(id="lmnopqrstuv")
    monkeypatch.setattr(plugin, "yt_dlp_extract_info", lambda url: info_b)
    clear_registry()
    summary_extractor.register(complete=_stub_completion(_VALID_SUMMARY))
    row_b = _enqueue(q, conn, item="lmnopqrstuv", binding=BINDING_OWNED, kind="owned_playlist")
    assert q.get(row_b.request_id).status == "pending"
    claimed_b = q.claim_batch(1, conn=conn)
    assert [c.request_id for c in claimed_b] == [row_b.request_id]
    done_b = drain_one(claimed_b[0], vault_context=vault, queue=q, write_guard=_allowing_guard(), conn=conn)
    assert done_b.status == "completed"
    # A's terminal state never changed.
    assert q.get(row_a.request_id).status == "dead_lettered"

    # Item C: attempts exhaustion dead-letters with terminal: true.
    row_c = _enqueue(q, conn, item="zzzzzzzzzzz", binding=str(uuid.uuid4()), kind="public_playlist")
    far_future = datetime.now(timezone.utc) + timedelta(days=365)
    for _attempt in range(DEFAULT_MAX_ATTEMPTS):
        claimed_c = q.claim_batch(1, now=far_future, conn=conn)
        assert [c.request_id for c in claimed_c] == [row_c.request_id]
        q.fail(row_c.request_id, reason_code="network_error", error="boom", conn=conn)
    final_c = q.get(row_c.request_id)
    assert final_c.status == "dead_lettered"
    assert final_c.attempts == DEFAULT_MAX_ATTEMPTS
    c_failed = [
        p for p in conn.payloads_for(ACQUISITION_FAILED_TOPIC) if p["request_id"] == row_c.request_id
    ]
    assert len(c_failed) == DEFAULT_MAX_ATTEMPTS
    assert [p["terminal"] for p in c_failed].count(True) == 1
    assert c_failed[-1]["terminal"] is True


# ---------------------------------------------------------------------------
# AC5
# ---------------------------------------------------------------------------


def test_backoff_gate_and_priority_order(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeOutboxConn()
    q = _queue()
    now = datetime.now(timezone.utc)

    # Backoff floor per contract: base 60 s, factor 4, cap 6 h.
    assert compute_backoff_seconds(1, rng=lambda: 0.0) == 60
    assert compute_backoff_seconds(2, rng=lambda: 0.0) == 240
    assert compute_backoff_seconds(3, rng=lambda: 0.0) == 960
    assert compute_backoff_seconds(6, rng=lambda: 0.0) == 21600
    assert compute_backoff_seconds(7, rng=lambda: 0.0) == 21600
    # Jitter never fires the gate EARLIER than the deterministic floor.
    for attempt in (1, 2, 5):
        assert compute_backoff_seconds(attempt) >= compute_backoff_seconds(attempt, rng=lambda: 0.0)

    row = _enqueue(q, conn, item="aaaaaaaaaaa", priority="normal")
    q.claim_batch(1, now=now, conn=conn)
    q.fail(row.request_id, reason_code="network_error", error="transient", now=now, conn=conn)

    gated = q.get(row.request_id)
    assert gated.status == "pending"
    gate = datetime.fromisoformat(gated.next_attempt_at)
    assert gate >= now + timedelta(seconds=60)

    # claim_batch respects the gate.
    assert q.claim_batch(5, now=now + timedelta(seconds=30), conn=conn) == []
    assert [r.request_id for r in q.claim_batch(5, now=gate + timedelta(seconds=1), conn=conn)] == [
        row.request_id
    ]
    q.fail(row.request_id, reason_code="network_error", error="still down", now=now, conn=conn)

    # Priority order: high (inbox-discovered) before normal, then requested_at.
    older_normal = _enqueue(q, conn, item="bbbbbbbbbbb", priority="normal", binding=str(uuid.uuid4()))
    high = _enqueue(q, conn, item="ccccccccccc", priority="high", binding=str(uuid.uuid4()), kind="inbox_playlist")
    newer_normal = _enqueue(q, conn, item="ddddddddddd", priority="normal", binding=str(uuid.uuid4()))

    order = [r.request_id for r in q.claim_batch(3, now=now, conn=conn)]
    assert order == [high.request_id, older_normal.request_id, newer_normal.request_id]


# ---------------------------------------------------------------------------
# AC6
# ---------------------------------------------------------------------------


def test_event_idempotency_keys_per_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeOutboxConn()
    q = _queue()
    row = _enqueue(q, conn)

    # Duplicate discovery: acquisition.requested dedups to one row.
    _enqueue(q, conn)
    assert len(conn.rows_for(ACQUISITION_REQUESTED_TOPIC)) == 1

    # Attempt 1 started event.
    q.claim_batch(1, conn=conn)
    started = conn.rows_for(ACQUISITION_STARTED_TOPIC)
    assert len(started) == 1

    # Re-emission of the SAME attempt (crash-retry duplicate delivery) dedups.
    dup = new_event(
        event_type=ACQUISITION_STARTED_TOPIC,
        payload={"request_id": row.request_id, "attempt": 1},
        source="knowledge_acquisition.source_sync",
    )
    write_outbox_event(dup, conn=conn, idempotency_key=attempt_event_key(ACQUISITION_STARTED_TOPIC, row.request_id, 1))
    assert len(conn.rows_for(ACQUISITION_STARTED_TOPIC)) == 1

    # A NEW attempt is a distinct event.
    now = datetime.now(timezone.utc)
    q.fail(row.request_id, reason_code="network_error", error="t1", now=now, conn=conn)
    q.claim_batch(1, now=now + timedelta(hours=7), conn=conn)
    started_after = conn.rows_for(ACQUISITION_STARTED_TOPIC)
    assert len(started_after) == 2
    attempts_seen = {p["attempt"] for p in conn.payloads_for(ACQUISITION_STARTED_TOPIC)}
    assert attempts_seen == {1, 2}

    # failed events are attempt-scoped too.
    q.fail(row.request_id, reason_code="network_error", error="t2", now=now, conn=conn)
    failed_payloads = [
        p for p in conn.payloads_for(ACQUISITION_FAILED_TOPIC) if p["request_id"] == row.request_id
    ]
    assert {p["attempt"] for p in failed_payloads} == {1, 2}


# ---------------------------------------------------------------------------
# Supporting unit tests
# ---------------------------------------------------------------------------


def test_request_identity_deterministic_and_policy_version_sensitive() -> None:
    a = request_identity("youtube_url", VIDEO_ID, 1)
    b = request_identity("youtube_url", VIDEO_ID, 1)
    c = request_identity("youtube_url", VIDEO_ID, 2)
    assert a == b != c
    assert uuid.UUID(a).version == 5


def test_enqueue_validates_inputs() -> None:
    conn = FakeOutboxConn()
    q = _queue()
    with pytest.raises(ValueError):
        q.enqueue(source_kind="", item_ref=VIDEO_ID, source_ref="x", trigger=_trigger(BINDING_INBOX), conn=conn)
    with pytest.raises(ValueError):
        q.enqueue(source_kind="youtube_url", item_ref=" ", source_ref="x", trigger=_trigger(BINDING_INBOX), conn=conn)
    with pytest.raises(ValueError):
        _enqueue(q, conn, priority="urgent")
    with pytest.raises(ValueError):
        q.enqueue(
            source_kind="youtube_url",
            item_ref=VIDEO_ID,
            source_ref="x",
            trigger=_trigger(BINDING_INBOX, trigger="webhook"),
            conn=conn,
        )


def test_reset_stale_in_progress_recovers_without_attempt_increment() -> None:
    conn = FakeOutboxConn()
    q = _queue()
    row = _enqueue(q, conn)
    q.claim_batch(1, conn=conn)
    assert q.get(row.request_id).status == "in_progress"
    assert q.get(row.request_id).attempts == 1

    # Not yet stale: nothing resets.
    assert q.reset_stale_in_progress(older_than_seconds=3600) == 0
    assert q.get(row.request_id).status == "in_progress"

    # Past the threshold (clock injected): reset to pending, attempts untouched.
    future = datetime.now(timezone.utc) + timedelta(hours=2)
    assert q.reset_stale_in_progress(older_than_seconds=3600, now=future) == 1
    recovered = q.get(row.request_id)
    assert recovered.status == "pending"
    assert recovered.attempts == 1


def test_memory_backend_passes_shared_contract() -> None:
    """AC7 counterpart: the SAME contract suite the pg test runs, on memory."""
    from tests.knowledge_acquisition._acquisition_requests_contract import ALL_CONTRACT_ASSERTIONS

    for assertion in ALL_CONTRACT_ASSERTIONS:
        assertion(_queue)


def test_explicit_dead_letter_is_terminal() -> None:
    conn = FakeOutboxConn()
    q = _queue()
    row = _enqueue(q, conn)
    q.claim_batch(1, conn=conn)
    q.dead_letter(row.request_id, reason_code="pipeline_dead_letter", error="stage dead-letter", conn=conn)
    final = q.get(row.request_id)
    assert final.status == "dead_lettered"
    assert final.last_failure["reason_code"] == "pipeline_dead_letter"
    failed = conn.payloads_for(ACQUISITION_FAILED_TOPIC)
    assert failed[-1]["terminal"] is True


# --- Review-gate regressions -------------------------------------------------


def test_terminal_request_not_reopened_by_stale_drainer_fail() -> None:
    """INV-YSS-3: the stale-reset race (drainer A hangs past the threshold,
    drainer B completes the row, A's late fail lands) must not reopen the
    completed request nor emit a failure event."""
    from app.knowledge_acquisition.acquisition_requests import ACQUISITION_STARTED_TOPIC as _started

    conn = FakeOutboxConn()
    q = _queue()
    row = _enqueue(q, conn)
    q.claim_batch(1, conn=conn)  # drainer A claims
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert q.reset_stale_in_progress(older_than_seconds=900, now=future) == 1
    q.claim_batch(1, now=future, conn=conn)  # drainer B claims (attempt 2)
    q.complete(row.request_id, content_identity="cid-b", conn=conn)

    failed_before = len(conn.rows_for(ACQUISITION_FAILED_TOPIC))
    late = q.fail(row.request_id, reason_code="network_error", error="drainer A woke up", conn=conn)
    assert late.status == "completed"
    assert late.content_identity == "cid-b"
    assert len(conn.rows_for(ACQUISITION_FAILED_TOPIC)) == failed_before
    # Both attempts left their started lineage; the completion is attempt 2's.
    assert {p["attempt"] for p in conn.payloads_for(_started)} == {1, 2}


def test_dead_letter_after_retryable_fail_same_attempt_keeps_terminal_event() -> None:
    """The terminal acquisition.failed of attempt N must not be key-swallowed by
    the earlier retryable failure of the same attempt."""
    conn = FakeOutboxConn()
    q = _queue()
    row = _enqueue(q, conn)
    q.claim_batch(1, conn=conn)
    q.fail(row.request_id, reason_code="network_error", error="transient", conn=conn)
    # Stage dead-letter surfaces before any new claim: explicit terminal outcome.
    q.dead_letter(row.request_id, reason_code="pipeline_dead_letter", error="stage", conn=conn)
    failed = conn.payloads_for(ACQUISITION_FAILED_TOPIC)
    assert len(failed) == 2
    assert [p["terminal"] for p in failed] == [False, True]
    assert q.get(row.request_id).status == "dead_lettered"


def test_transitions_on_unclaimed_row_are_loud() -> None:
    from app.knowledge_acquisition.acquisition_requests import AcquisitionRequestValidationError

    conn = FakeOutboxConn()
    q = _queue()
    row = _enqueue(q, conn)  # pending, never claimed
    with pytest.raises(AcquisitionRequestValidationError):
        q.complete(row.request_id, content_identity="cid-x", conn=conn)
    with pytest.raises(AcquisitionRequestValidationError):
        q.fail(row.request_id, reason_code="network_error", conn=conn)
    assert q.get(row.request_id).status == "pending"
    assert conn.payloads_for(ACQUISITION_FAILED_TOPIC) == []


def test_naive_injected_clock_is_treated_as_utc() -> None:
    conn = FakeOutboxConn()
    q = _queue()
    row = _enqueue(q, conn)
    q.claim_batch(1, conn=conn)
    q.fail(row.request_id, reason_code="network_error", error="t", conn=conn)
    naive_future = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=7)
    claimed = q.claim_batch(1, now=naive_future, conn=conn)  # must not TypeError
    assert [c.request_id for c in claimed] == [row.request_id]


def test_trigger_append_does_not_touch_updated_at() -> None:
    """Contract: a duplicate discovery 'appends the new discovery trigger ...
    and touches nothing else' — updated_at is the stale-recovery clock and a
    re-discovery must never defer a crashed attempt's reset."""
    conn = FakeOutboxConn()
    q = _queue()
    row = _enqueue(q, conn)
    q.claim_batch(1, conn=conn)  # in_progress; drainer then "crashes"
    stamp_before = q.get(row.request_id).updated_at
    _enqueue(q, conn, binding=str(uuid.uuid4()), kind="owned_playlist")  # novel trigger
    refreshed = q.get(row.request_id)
    assert len(refreshed.discovery_triggers) == 2
    assert refreshed.updated_at == stamp_before
    future = datetime.now(timezone.utc) + timedelta(hours=1)
    assert q.reset_stale_in_progress(older_than_seconds=900, now=future) == 1


def test_trigger_novelty_is_arrival_order_independent() -> None:
    conn = FakeOutboxConn()
    q = _queue()
    binding = str(uuid.uuid4())
    bare = _trigger(binding, "owned_playlist")
    with_item = _trigger(binding, "owned_playlist", playlist_item_id="pli-1")
    r1 = q.enqueue(
        source_kind="youtube_url", item_ref=VIDEO_ID,
        source_ref=f"https://www.youtube.com/watch?v={VIDEO_ID}", trigger=with_item, conn=conn,
    )
    r2 = q.enqueue(
        source_kind="youtube_url", item_ref=VIDEO_ID,
        source_ref=f"https://www.youtube.com/watch?v={VIDEO_ID}", trigger=bare, conn=conn,
    )
    assert r1.request_id == r2.request_id
    # Both provenance entries survive regardless of which arrived first.
    assert len(r2.discovery_triggers) == 2


def test_youtube_source_kind_matches_plugin_constant() -> None:
    from app.knowledge_acquisition.acquisition_requests import YOUTUBE_SOURCE_KIND

    assert YOUTUBE_SOURCE_KIND == plugin.SOURCE_KIND


def test_enqueue_rejects_string_extractor_ids() -> None:
    from app.knowledge_acquisition.acquisition_requests import AcquisitionRequestValidationError

    conn = FakeOutboxConn()
    q = _queue()
    with pytest.raises(AcquisitionRequestValidationError):
        _enqueue(q, conn, policy_snapshot={"policy_version": 1, "extractor_ids": "summary"})


def test_drain_one_dead_letters_unknown_source_kind() -> None:
    conn = FakeOutboxConn()
    q = _queue()
    row = q.enqueue(
        source_kind="podcast_rss",
        item_ref="ep-001",
        source_ref="https://example.com/feed/ep-001",
        trigger=_trigger(str(uuid.uuid4())),
        conn=conn,
    )
    q.claim_batch(1, conn=conn)
    result = drain_one(q.get(row.request_id), vault_context=None, queue=q, conn=conn)
    assert result.status == "dead_lettered"
    assert result.last_failure["reason_code"] == "source_unsupported"


def test_drain_candidate_metadata_only_does_not_run_transcript_acquisition() -> None:
    """The drain boundary must not turn a shallow request into a full fetch."""
    conn = FakeOutboxConn()
    q = _queue()
    _enqueue(
        q,
        conn,
        policy_snapshot={"policy_version": 1, "mode": "candidate_metadata_only"},
    )
    claimed = q.claim_batch(1, conn=conn)
    calls: list[dict[str, Any]] = []

    def acquire_must_not_run(*args: Any, **kwargs: Any) -> None:
        calls.append(kwargs)
        raise AssertionError("metadata-only requests must not enter the transcript pipeline")

    result = drain_one(
        claimed[0], vault_context=None, queue=q, conn=conn, acquire_fn=acquire_must_not_run
    )

    assert calls == []
    assert result.status == "dead_lettered"
    assert result.completed_at is None
    assert result.last_failure is not None
    assert result.last_failure["reason_code"] == "policy_unsupported"
    assert "candidate_metadata_only" in result.last_failure["error"]


def test_drain_honors_captions_false_before_acquire_youtube() -> None:
    """A disabled-caption policy cannot silently use the current full pipeline."""
    conn = FakeOutboxConn()
    q = _queue()
    _enqueue(
        q,
        conn,
        policy_snapshot={"policy_version": 1, "mode": "acquire_transcript", "captions": False},
    )
    claimed = q.claim_batch(1, conn=conn)
    calls: list[dict[str, Any]] = []

    def acquire_must_not_run(*args: Any, **kwargs: Any) -> None:
        calls.append(kwargs)
        raise AssertionError("captions=false requests must not enter acquire_youtube")

    result = drain_one(
        claimed[0], vault_context=None, queue=q, conn=conn, acquire_fn=acquire_must_not_run
    )

    assert calls == []
    assert result.status == "dead_lettered"
    assert result.completed_at is None
    assert result.last_failure is not None
    assert result.last_failure["reason_code"] == "policy_unsupported"
    assert "captions=false" in result.last_failure["error"]


def test_drain_unsupported_policy_depth_is_legible_non_completed() -> None:
    conn = FakeOutboxConn()
    q = _queue()
    _enqueue(
        q,
        conn,
        policy_snapshot={"policy_version": 1, "mode": "discover_only"},
    )
    claimed = q.claim_batch(1, conn=conn)

    def acquire_must_not_run(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("unsupported policies must stop before acquire_youtube")

    result = drain_one(
        claimed[0],
        vault_context=None,
        queue=q,
        conn=conn,
        acquire_fn=acquire_must_not_run,
    )

    assert result.status == "dead_lettered"
    assert result.completed_at is None
    assert result.last_failure is not None
    assert result.last_failure["reason_code"] == "policy_unsupported"
    assert "discover_only" in result.last_failure["error"]
