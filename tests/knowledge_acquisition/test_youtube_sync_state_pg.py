"""YSS-06 scheduler state against the real migration-owned Postgres table.

This suite exists because its absence shipped a P0. Every other scheduler test
runs `not_pg` against `MemorySyncStateStore`, whose genuine string-keyed dicts
make row-shape mistakes structurally unobservable, and `mypy` cannot help
because `app.db.db.conn_rw` is untyped. An earlier revision indexed
`conn_rw`'s `dict_row` results positionally (`row[0]`), so `for_runtime()`
raised `KeyError(0)` on every tick *with the table fully present* — the whole
capability was inert in production and surfaced only as `error: "0"`.

So: construct the production store against real Postgres, and exercise the two
read paths plus the lease semantics the exclusion invariant depends on.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from sqlalchemy.engine import URL

from app.knowledge_acquisition.acquisition_requests import (
    AcquisitionRequests,
    DiscoveryTrigger,
)
from app.knowledge_acquisition.source_registry import SourceBinding, SourceRegistry
from app.knowledge_acquisition.sync_scheduler import LEASE_KEY, LEASE_TTL_SECONDS
from app.knowledge_acquisition.sync_state import (
    SyncLeaseLostError,
    SyncStateSchemaMissingError,
    for_runtime,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
YSS06_HEAD = "c9d0e1f2a3b4"
PRE_YSS06_HEAD = "b7e3c9d5a1f2"

NOW = datetime(2026, 9, 22, 12, 0, 0, tzinfo=timezone.utc)


def _alembic_config() -> Config:
    config = Config(str(REPO_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(REPO_ROOT / "app" / "alembic"))
    return config


@pytest.fixture
def scratch_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[Config]:
    from app.db.dsn import resolve_dsn

    explicit_dsn = os.getenv("DATABASE_URL") or os.getenv("DB_DSN")
    if not explicit_dsn:
        pytest.skip("DATABASE_URL/DB_DSN not configured")
    admin_dsn = resolve_dsn(explicit_dsn)
    admin_database = conninfo_to_dict(admin_dsn).get("dbname", "")
    if admin_database != "app_test" and not admin_database.startswith("scratch_"):
        pytest.skip("YSS-06 Postgres tests require an explicit app_test or scratch admin database")
    try:
        with psycopg.connect(admin_dsn, connect_timeout=2):
            pass
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"Postgres unavailable: {exc}")

    database_name = f"scratch_yss06_state_{uuid.uuid4().hex[:12]}"
    scratch_params = conninfo_to_dict(admin_dsn)
    scratch_params["dbname"] = database_name
    scratch_conninfo = make_conninfo(**scratch_params)
    scratch_url = URL.create(
        "postgresql",
        username=scratch_params.get("user"),
        password=scratch_params.get("password"),
        host=scratch_params.get("host"),
        port=int(scratch_params["port"]) if scratch_params.get("port") else None,
        database=database_name,
    ).render_as_string(hide_password=False)

    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        conn.execute(f'CREATE DATABASE "{database_name}"')
    try:
        with psycopg.connect(scratch_conninfo, autocommit=True) as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        monkeypatch.setenv("DATABASE_URL", scratch_url)
        monkeypatch.delenv("DB_DSN", raising=False)
        monkeypatch.delenv("STORE_SCHEMA_AUTOCREATE", raising=False)
        monkeypatch.delenv("STORE_BACKEND", raising=False)
        yield _alembic_config()
    finally:
        with psycopg.connect(admin_dsn, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')


@pytest.mark.pg
def test_pg_state_store_reads_its_own_rows(scratch_database: Config) -> None:
    # The regression this file exists for: constructing the store runs the
    # schema preflight, and reading a row goes through the other dict_row site.
    command.upgrade(scratch_database, YSS06_HEAD)

    store = for_runtime()  # raised KeyError(0) here before the fix

    assert store.get("absent") is None

    store.set("backoff:inbox", {"consecutive_failures": 3, "last_attempt_at": NOW.isoformat()})
    row = store.get("backoff:inbox")
    assert row is not None
    assert row["consecutive_failures"] == 3
    assert row["last_attempt_at"] == NOW.isoformat()

    store.set("backoff:inbox", {"consecutive_failures": 0})
    replaced = store.get("backoff:inbox")
    assert replaced is not None
    assert replaced["consecutive_failures"] == 0
    assert "last_attempt_at" not in replaced, "set replaces the row rather than merging"


@pytest.mark.pg
def test_pg_lease_excludes_a_second_runner_and_expires(scratch_database: Config) -> None:
    command.upgrade(scratch_database, YSS06_HEAD)
    store = for_runtime()

    first = "host-a:101:aaaaaaaa"
    second = "host-b:202:bbbbbbbb"

    assert store.acquire_lease(
        key=LEASE_KEY, holder=first, ttl_seconds=LEASE_TTL_SECONDS, now=NOW
    ) is True
    assert store.acquire_lease(
        key=LEASE_KEY, holder=second, ttl_seconds=LEASE_TTL_SECONDS, now=NOW
    ) is False, "a live lease must exclude a different runner"

    # The holder may re-acquire: that is what makes a retry and a heartbeat work.
    assert store.acquire_lease(
        key=LEASE_KEY, holder=first, ttl_seconds=LEASE_TTL_SECONDS, now=NOW
    ) is True

    # Releasing is holder-scoped, so a stale runner cannot delete a live lease.
    store.release_lease(key=LEASE_KEY, holder=second)
    assert store.get(LEASE_KEY) is not None, "release by a non-holder must be a no-op"

    # An expired lease is taken over rather than honoured forever.
    later = NOW + timedelta(seconds=LEASE_TTL_SECONDS + 1)
    assert store.acquire_lease(
        key=LEASE_KEY, holder=second, ttl_seconds=LEASE_TTL_SECONDS, now=later
    ) is True

    held = store.get(LEASE_KEY)
    assert held is not None and held["holder"] == second

    store.release_lease(key=LEASE_KEY, holder=second)
    assert store.get(LEASE_KEY) is None


@pytest.mark.pg
def test_pg_schema_preflight_fails_loud_before_the_migration(
    scratch_database: Config,
) -> None:
    # Fail-loud rather than a raw UndefinedTable from inside a later query.
    command.upgrade(scratch_database, PRE_YSS06_HEAD)

    with pytest.raises(SyncStateSchemaMissingError) as excinfo:
        for_runtime()

    assert "alembic upgrade head" in str(excinfo.value)


def _scratch_connection() -> psycopg.Connection:
    """A real independent observer, restricted to this fixture's isolated DB."""
    dsn = os.environ["DATABASE_URL"]
    assert conninfo_to_dict(dsn)["dbname"].startswith("scratch_yss06_state_")
    return psycopg.connect(dsn, autocommit=True, connect_timeout=2)


def _source_registry() -> tuple[SourceRegistry, SourceBinding]:
    registry = SourceRegistry.for_runtime()
    source = registry.register(
        collection_kind="inbox_playlist",
        collection_ref="PL__test__atomic_sync",
        title="Synthetic scheduler transaction source",
        account_binding_id=str(uuid.uuid4()),
    )
    assert source.account_binding_id is not None
    source = registry.set_inbox(source.account_binding_id, source.binding_id)
    return registry, source


def _trigger(source: SourceBinding) -> DiscoveryTrigger:
    return DiscoveryTrigger(
        binding_id=source.binding_id,
        collection_kind=source.collection_kind,
        collection_ref=source.collection_ref,
        trigger="poll",
    )


@pytest.mark.pg
def test_pg_owned_effect_fences_cursor_and_state_after_takeover(
    scratch_database: Config,
) -> None:
    command.upgrade(scratch_database, YSS06_HEAD)
    store = for_runtime()
    registry, source = _source_registry()
    first, second = "old-runner", "new-runner"
    later = NOW + timedelta(seconds=LEASE_TTL_SECONDS + 1)
    state_key = f"backoff:{source.binding_id}"
    assert store.acquire_lease(
        key=LEASE_KEY, holder=first, ttl_seconds=LEASE_TTL_SECONDS, now=NOW
    )
    paused_before_effect = threading.Event()
    resume_old_runner = threading.Event()

    def old_writer() -> None:
        paused_before_effect.set()
        assert resume_old_runner.wait(timeout=5)
        with pytest.raises(SyncLeaseLostError):
            with store.owned_effect(key=LEASE_KEY, holder=first, now=later) as conn:
                registry.record_poll_success(
                    source.binding_id, cursor={"owner": first}, transaction_conn=conn
                )
                registry.record_poll_failure(
                    source.binding_id, reason_code="network_error", transaction_conn=conn
                )
                store.set(state_key, {"owner": first}, transaction_conn=conn)

    with ThreadPoolExecutor(max_workers=1) as workers:
        stale_write = workers.submit(old_writer)
        try:
            assert paused_before_effect.wait(timeout=5)
            assert store.acquire_lease(
                key=LEASE_KEY, holder=second, ttl_seconds=LEASE_TTL_SECONDS, now=later
            )
            with store.owned_effect(key=LEASE_KEY, holder=second, now=later) as conn:
                registry.record_poll_success(
                    source.binding_id, cursor={"owner": second}, transaction_conn=conn
                )
                store.set(state_key, {"owner": second}, transaction_conn=conn)
        finally:
            resume_old_runner.set()
        stale_write.result(timeout=5)

    current = registry.get(source.binding_id)
    assert current is not None
    assert current.cursor == {"owner": second}
    assert current.last_error is None
    assert store.get(state_key) == {"owner": second}
    store.release_lease(key=LEASE_KEY, holder=first)
    lease = store.get(LEASE_KEY)
    assert lease is not None and lease["holder"] == second


@pytest.mark.pg
def test_pg_owned_effect_blocks_takeover_until_admitted_effect_commits(
    scratch_database: Config,
) -> None:
    command.upgrade(scratch_database, YSS06_HEAD)
    store, contender = for_runtime(), for_runtime()
    registry, source = _source_registry()
    later = NOW + timedelta(seconds=LEASE_TTL_SECONDS + 1)
    assert store.acquire_lease(
        key=LEASE_KEY, holder="admitted", ttl_seconds=LEASE_TTL_SECONDS, now=NOW
    )

    # The first runner pauses inside the real owned transaction. The second
    # connection sees an expired TTL, but cannot take over the row being used
    # by the admitted writer. No Python lock or mocked connection decides this.
    with ThreadPoolExecutor(max_workers=1) as workers:
        with store.owned_effect(key=LEASE_KEY, holder="admitted", now=NOW) as conn:
            attempted_takeover = workers.submit(
                contender.acquire_lease,
                key=LEASE_KEY,
                holder="contender",
                ttl_seconds=LEASE_TTL_SECONDS,
                now=later,
            )
            assert attempted_takeover.result(timeout=5) is False
            registry.record_poll_success(
                source.binding_id, cursor={"committed": True}, transaction_conn=conn
            )
            store.set("last_tick", {"owner": "admitted"}, transaction_conn=conn)

    current = registry.get(source.binding_id)
    assert current is not None and current.cursor == {"committed": True}
    assert store.get("last_tick") == {"owner": "admitted"}
    assert contender.acquire_lease(
        key=LEASE_KEY, holder="contender", ttl_seconds=LEASE_TTL_SECONDS, now=later
    ), "takeover becomes possible only after the admitted transaction releases its row lock"


@pytest.mark.pg
@pytest.mark.parametrize("poll_outcome", ["success", "failure"])
def test_pg_owned_effect_session_abort_rolls_back_all_protected_writes(
    scratch_database: Config,
    poll_outcome: str,
) -> None:
    command.upgrade(scratch_database, YSS06_HEAD)
    store = for_runtime()
    registry, source = _source_registry()
    queue = AcquisitionRequests.for_runtime()
    initial_cursor = {"frontier": "before-transaction"}
    registry.record_poll_success(source.binding_id, cursor=initial_cursor)
    initial_source = registry.get(source.binding_id)
    state_key = f"backoff:{source.binding_id}"
    store.set(state_key, {"consecutive_failures": 0})
    initial_state = store.get(state_key)

    old = NOW - timedelta(hours=2)
    stale_request = queue.enqueue(
        source_kind="youtube_url", item_ref="aaaaaaaaaaa",
        source_ref="https://www.youtube.com/watch?v=aaaaaaaaaaa",
        trigger=_trigger(source), now=old,
    )
    claimed = queue.claim_batch(1, now=old)
    assert len(claimed) == 1 and claimed[0].request_id == stale_request.request_id
    assert claimed[0].status == "in_progress"
    initial_request = queue.get(stale_request.request_id)

    assert store.acquire_lease(
        key=LEASE_KEY, holder="to-be-aborted", ttl_seconds=LEASE_TTL_SECONDS, now=NOW
    )
    with _scratch_connection() as observer:
        initial_outbox_count = observer.execute("SELECT count(*) FROM outbox").fetchone()[0]
        session_terminated = False
        with pytest.raises(psycopg.Error):
            with store.owned_effect(key=LEASE_KEY, holder="to-be-aborted", now=NOW) as conn:
                # Use the exact connection yielded by the production fence;
                # neither row_factory nor transaction handling is substituted.
                assert conn.info.dbname.startswith("scratch_yss06_state_")
                assert conn.info.backend_pid != observer.info.backend_pid
                if poll_outcome == "success":
                    registry.record_poll_success(
                        source.binding_id, cursor={"frontier": "uncommitted"},
                        transaction_conn=conn,
                    )
                else:
                    registry.record_poll_failure(
                        source.binding_id, reason_code="network_error", transaction_conn=conn
                    )
                store.set(state_key, {"consecutive_failures": 3}, transaction_conn=conn)
                new_request = queue.enqueue(
                    source_kind="youtube_url", item_ref="bbbbbbbbbbb",
                    source_ref="https://www.youtube.com/watch?v=bbbbbbbbbbb",
                    trigger=_trigger(source), now=NOW, transaction_conn=conn,
                )
                assert queue.reset_stale_in_progress(
                    older_than_seconds=3600, now=NOW, transaction_conn=conn
                ) == 1

                # A separate live session cannot see any of the effects before
                # commit. This catches a helper silently opening an autocommit
                # connection, including the queue's canonical outbox emissions.
                assert registry.get(source.binding_id) == initial_source
                assert store.get(state_key) == initial_state
                assert queue.get(new_request.request_id) is None
                assert queue.get(stale_request.request_id) == initial_request
                assert observer.execute("SELECT count(*) FROM outbox").fetchone()[0] == initial_outbox_count

                assert observer.execute(
                    "SELECT pg_terminate_backend(%s)", (conn.info.backend_pid,)
                ).fetchone()[0] is True
                session_terminated = True
                conn.execute("SELECT 1")  # surface the actual terminated-session error

        assert session_terminated, "an earlier SQL failure is not proof of session-abort rollback"
        assert registry.get(source.binding_id) == initial_source
        assert store.get(state_key) == initial_state
        assert queue.get(new_request.request_id) is None
        assert queue.get(stale_request.request_id) == initial_request
        assert observer.execute("SELECT count(*) FROM outbox").fetchone()[0] == initial_outbox_count

    # Session death releases the lock: a later runner can take the expired
    # lease, while none of the aborted writer's source/queue/state effects exist.
    assert store.acquire_lease(
        key=LEASE_KEY, holder="replacement", ttl_seconds=LEASE_TTL_SECONDS,
        now=NOW + timedelta(seconds=LEASE_TTL_SECONDS + 1),
    )


@pytest.mark.pg
def test_pg_auth_disable_returns_updated_source_without_rewinding_cursor(
    scratch_database: Config,
) -> None:
    command.upgrade(scratch_database, YSS06_HEAD)
    registry, source = _source_registry()
    cursor = {"known_playlist_item_ids": ["synthetic-item"]}
    registry.record_poll_success(source.binding_id, cursor=cursor)
    # The existing disconnect route uses the enabled=False branch, without a
    # caller transaction. It must return its row after the autocommit UPDATE.
    disabled = registry.disable_source_for_auth(source.binding_id, reason_code="auth_disconnected")
    assert disabled.enabled is False
    assert disabled.cursor == cursor
    assert disabled.last_error["reason_code"] == "auth_disconnected"
    assert registry.get(source.binding_id) == disabled


@pytest.mark.pg
def test_pg_auth_status_effects_use_ownership_transaction(scratch_database: Config) -> None:
    from app.knowledge_acquisition.youtube_account_binding import AccountBindingStore
    command.upgrade(scratch_database, YSS06_HEAD)
    store = for_runtime()
    registry, source = _source_registry()
    bindings = AccountBindingStore.for_runtime()
    account = bindings.create(provider_channel_id="synthetic-channel", display_label="Fixture",
        scopes=["https://www.googleapis.com/auth/youtube.readonly"],
        account_binding_id=source.account_binding_id)
    assert store.acquire_lease(key=LEASE_KEY, holder="auth", ttl_seconds=LEASE_TTL_SECONDS, now=NOW)
    with store.owned_effect(key=LEASE_KEY, holder="auth", now=NOW) as conn:
        updated = bindings.set_state(account.account_binding_id, state="degraded",
            reason_code="auth_expired", transaction_conn=conn)
        degraded = registry.record_source_degradation(source.binding_id,
            reason_code="auth_expired", transaction_conn=conn)
        assert updated.state == "degraded"
        assert degraded.last_error["reason_code"] == "auth_expired"
        assert bindings.get(account.account_binding_id) == account
        assert registry.get(source.binding_id) == source
    assert bindings.get(account.account_binding_id) == updated
    assert registry.get(source.binding_id) == degraded
