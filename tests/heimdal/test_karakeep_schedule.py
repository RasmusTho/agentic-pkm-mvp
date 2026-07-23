"""Coordinated Karakeep producer/consumer scheduling (KMA-05, #3377).

Exercises the scheduler's lease independence, health gating, cursor preservation,
and truthful secret-safe receipts. The Mimer consumer runs against the real
``project_pending_candidates`` over a temp vault and real published evidence, so
"health gates the producer, not the consumer" is proven end to end.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from app.events.types import HEIMDAL_OBSERVATION_PUBLISHED
from app.heimdal import karakeep_schedule
from app.heimdal.candidate_projection import CANDIDATE_CONSUMER_ID, project_pending_candidates
from app.heimdal.cursor_store import get_cursor, reset_memory_cursor_store
from app.heimdal.karakeep_schedule import (
    CONSUMER_LEASE,
    PRODUCER_LEASE,
    LeaseStore,
    run_boundary_cycle,
    run_consumer,
    run_producer,
    source_health_gate,
)
from app.heimdal.observation_log import reset_memory_observation_log
from app.heimdal.publish import publish_observation
from app.vault.manager import VaultContext
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg

_SECRET_BASE_URL = "https://karakeep.secret.example"


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_memory_observation_log()
    reset_memory_cursor_store()
    karakeep_schedule.reset_lease_store()
    yield
    reset_memory_observation_log()
    reset_memory_cursor_store()
    karakeep_schedule.reset_lease_store()


def _vault(root: Path) -> VaultContext:
    root.mkdir(parents=True, exist_ok=True)
    return VaultContext(status="selected", active_vault_id="v", active_vault_name="V", active_vault_path=str(root))


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _publish_karakeep(item_id: str, seed: str) -> str:
    content_hex = (seed * 64)[:64]
    observation_id = f"karakeep:{item_id}:{content_hex}:{'c' * 64}"
    publish_observation(
        topic=HEIMDAL_OBSERVATION_PUBLISHED,
        observation_id=observation_id,
        payload={
            "observation_id": observation_id,
            "episode_id": f"karakeep:{item_id}",
            "sequence": 0,
            "content": "saved reading evidence",
            "content_structure": {"karakeep": {"item_kind": "link", "source_item_identity": f"karakeep:{item_id}", "tombstone": False, "source_url": "https://example.com/x"}},
            "provenance": {"sensor": "karakeep_rest", "capture_chain": ["karakeep", "karakeep_rest", "heimdal_karakeep_adapter"], "content_identity": f"sha256:{content_hex}"},
        },
        source="heimdal_karakeep_adapter",
        stage_versions={"karakeep_adapter": "contract-v1"},
    )
    return observation_id


def _real_consumer(vault: VaultContext):
    def _project():
        return project_pending_candidates(vault_context=vault, write_guard=_allowing_guard())

    return _project


def _read_consumer_cursor() -> int:
    return get_cursor(CANDIDATE_CONSUMER_ID)


# ---------------------------------------------------------------------------
# AC1
# ---------------------------------------------------------------------------


def test_source_health_gates_producer_not_consumer(tmp_path: Path) -> None:
    _publish_karakeep("item-1", "a")
    vault = _vault(tmp_path / "vault")

    fetch_calls: list[int] = []

    def _should_not_fetch():
        fetch_calls.append(1)
        raise AssertionError("producer must not fetch while the source is unhealthy")

    # Real health gate against an unhealthy (503) source with a secret endpoint.
    def _unhealthy(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    env = {"KARAKEEP_BASE_URL": _SECRET_BASE_URL, "KARAKEEP_API_TOKEN": "tok"}
    http = httpx.Client(transport=httpx.MockTransport(_unhealthy))

    receipt = run_boundary_cycle(
        holder="runner-1",
        health_gate=lambda: source_health_gate(env, http=http),
        acquire=_should_not_fetch,
        read_producer_cursor=lambda: None,
        project=_real_consumer(vault),
        read_consumer_cursor=_read_consumer_cursor,
    )

    # Producer is gated: no fetch, no publish.
    assert receipt.producer.gated is True
    assert receipt.producer.gate_reason == "source_unhealthy"
    assert receipt.producer.published == 0
    assert fetch_calls == []
    # Consumer drains the durable handoff regardless of source health.
    assert receipt.consumer.written == 1
    assert receipt.consumer.consumer_cursor == 1


# ---------------------------------------------------------------------------
# AC2
# ---------------------------------------------------------------------------


def test_constituent_leases_are_independent() -> None:
    store = LeaseStore()
    now = 100.0

    # Producer and consumer leases are independent -- one never blocks the other.
    assert store.acquire(PRODUCER_LEASE, "A", ttl_seconds=90, now=now) is not None
    assert store.acquire(CONSUMER_LEASE, "B", ttl_seconds=90, now=now) is not None

    # Same-side overlap is refused (no double producer run) ...
    assert store.acquire(PRODUCER_LEASE, "C", ttl_seconds=90, now=now) is None
    # ... but there is no shared cross-side lock.
    store.release(PRODUCER_LEASE, "A")
    assert store.acquire(PRODUCER_LEASE, "C", ttl_seconds=90, now=now) is not None

    # At the run level: a producer lease held elsewhere blocks a producer run but
    # never the consumer run (independent sides).
    run_store = LeaseStore()
    run_store.acquire(PRODUCER_LEASE, "other-runner", ttl_seconds=90, now=now)
    producer = run_producer(
        holder="me",
        health_gate=lambda: None,
        acquire=lambda: pytest.fail("must not fetch under a lease conflict"),
        read_producer_cursor=lambda: "cursor-x",
        lease_store=run_store,
        clock=lambda: now,
    )
    assert producer.lease_conflict is True and producer.ran is False
    consumer = run_consumer(
        holder="me",
        project=lambda: [],
        read_consumer_cursor=lambda: 0,
        lease_store=run_store,
        clock=lambda: now,
    )
    assert consumer.lease_conflict is False and consumer.ran is True


# ---------------------------------------------------------------------------
# AC3
# ---------------------------------------------------------------------------


def test_failed_or_overlapping_run_preserves_constituent_cursors(tmp_path: Path) -> None:
    _publish_karakeep("item-a", "a")
    vault = _vault(tmp_path / "vault")

    # First consumer run drains one item and advances the consumer cursor.
    first = run_consumer(holder="c1", project=_real_consumer(vault), read_consumer_cursor=_read_consumer_cursor)
    assert first.written == 1
    assert get_cursor(CANDIDATE_CONSUMER_ID) == 1

    # A failed producer run does not regress the producer cursor.
    producer_cursor = {"value": "page:2"}
    failed = run_producer(
        holder="p1",
        health_gate=lambda: None,
        acquire=lambda: (_ for _ in ()).throw(RuntimeError("transient fetch failure")),
        read_producer_cursor=lambda: producer_cursor["value"],
    )
    assert failed.failed is True
    assert failed.producer_cursor == "page:2"  # unchanged by the failure

    # An overlapping consumer run (lease held elsewhere) does not advance/regress
    # the consumer cursor.
    karakeep_schedule.default_lease_store().acquire(CONSUMER_LEASE, "other", ttl_seconds=90, now=0.0)
    overlapped = run_consumer(holder="c2", project=_real_consumer(vault), read_consumer_cursor=_read_consumer_cursor, clock=lambda: 0.0)
    assert overlapped.lease_conflict is True
    assert get_cursor(CANDIDATE_CONSUMER_ID) == 1  # untouched
    karakeep_schedule.default_lease_store().release(CONSUMER_LEASE, "other")

    # Restart / replay is idempotent: nothing new, no duplicate, cursor stable.
    resumed = run_consumer(holder="c3", project=_real_consumer(vault), read_consumer_cursor=_read_consumer_cursor)
    assert resumed.consumed == 0
    assert get_cursor(CANDIDATE_CONSUMER_ID) == 1
    notes = list((tmp_path / "vault" / "Sources/Reading/Karakeep").glob("*.md"))
    assert len(notes) == 1


# ---------------------------------------------------------------------------
# AC4
# ---------------------------------------------------------------------------


def test_boundary_receipt_reports_each_constituent_truthfully(tmp_path: Path) -> None:
    _publish_karakeep("item-x", "a")
    vault = _vault(tmp_path / "vault")

    class _Result:
        fetched = 3
        published = ("karakeep:item-x:aa:cc", "karakeep:item-y:bb:cc")
        noops = 1
        item_errors = ("err",)
        stopped_early = False

    receipt = run_boundary_cycle(
        holder="runner",
        health_gate=lambda: None,
        acquire=lambda: _Result(),
        read_producer_cursor=lambda: "page:5",
        project=_real_consumer(vault),
        read_consumer_cursor=_read_consumer_cursor,
    )

    # Producer's published is reported separately from the consumer's write outcome.
    assert receipt.producer.published == 2
    assert receipt.producer.fetched == 3
    assert receipt.producer.item_errors == 1
    assert receipt.producer.producer_cursor == "page:5"
    assert receipt.consumer.written == 1
    assert receipt.consumer.blocked == 0
    assert receipt.consumer.consumer_cursor == 1
    # The two halves are independent truths.
    assert receipt.producer.constituent == "heimdal"
    assert receipt.consumer.constituent == "mimer"

    # Secret-safe: a gated run reports a code, never the endpoint/token.
    def _unhealthy(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, request=request)

    env = {"KARAKEEP_BASE_URL": _SECRET_BASE_URL, "KARAKEEP_API_TOKEN": "super-secret-token"}
    http = httpx.Client(transport=httpx.MockTransport(_unhealthy))
    gated = run_producer(
        holder="runner",
        health_gate=lambda: source_health_gate(env, http=http),
        acquire=lambda: pytest.fail("gated run must not fetch"),
        read_producer_cursor=lambda: None,
    )
    assert gated.gate_reason == "source_unhealthy"
    text = repr(gated)
    assert _SECRET_BASE_URL not in text
    assert "super-secret-token" not in text
