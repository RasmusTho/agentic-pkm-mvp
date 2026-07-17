"""Drift enforcement for scripts/prod_deploy_retry_preflight.py (#3903).

The PROD deploy preflight deliberately duplicates the worker's retry-budget
constants and threshold-resolution/counter-reading behavior instead of
importing ``app.workers.outbox_worker`` at runtime: the worker module pulls
httpx/yaml/pydantic plus module-level side effects, and deploy hosts may run
a bare ``python3`` without the venv. That import-light posture is correct --
but copies drift. This test (DB-free; mirrors the parity pattern of
``tests/migrations/test_outbox_schema_parity.py``) imports BOTH modules at
test time and pins them together, so any change to the worker's budgets or
semantics fails here until the preflight copy is updated.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from app.workers import outbox_worker
from scripts import prod_deploy_retry_preflight as preflight


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_retry_budget_constants_match_worker() -> None:
    assert preflight.MAX_TRANSIENT_RETRY_ATTEMPTS == outbox_worker._MAX_TRANSIENT_RETRY_ATTEMPTS
    assert preflight.DEFAULT_MAX_DISPATCH_ATTEMPTS == outbox_worker._MAX_DISPATCH_ATTEMPTS


@pytest.mark.parametrize(
    "raw_env",
    [
        None,  # unset -> default
        "7",  # valid override
        "1",  # smallest accepted override
        "abc",  # invalid -> default
        "-2",  # negative -> default
        "0",  # below minimum -> default
        "  ",  # whitespace junk -> default
    ],
)
def test_resolve_max_dispatch_attempts_parity(
    raw_env: str | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    if raw_env is None:
        monkeypatch.delenv("WORKER_MAX_DISPATCH_ATTEMPTS", raising=False)
    else:
        monkeypatch.setenv("WORKER_MAX_DISPATCH_ATTEMPTS", raw_env)

    assert (
        preflight._resolve_max_dispatch_attempts()
        == outbox_worker._resolve_max_dispatch_attempts()
    )


@pytest.mark.parametrize(
    "payload",
    [
        {},  # missing key
        {"_worker_retry_count": 3},  # valid
        {"_worker_retry_count": 0},  # explicit zero
        {"_worker_retry_count": -1},  # negative -> clamped to 0
        {"_worker_retry_count": "abc"},  # non-numeric string -> 0
        {"_worker_retry_count": "3"},  # numeric string -> int() accepts
        {"_worker_retry_count": None},  # explicit null -> 0
        {"_worker_retry_count": 2.9},  # float -> int() truncates identically
    ],
)
def test_payload_retry_count_parity(payload: dict) -> None:
    assert preflight._payload_retry_count(payload) == outbox_worker._payload_retry_count(payload)


def test_envelope_unwrap_reads_the_same_counter_the_worker_reads() -> None:
    """write_outbox_event stores the Event ENVELOPE; the worker coerces it and
    reads _worker_retry_count off the INNER payload. The preflight's unwrap +
    count must agree with the worker's count on that inner payload -- for the
    envelope as a dict, the envelope as a JSON string (driver/text tolerance),
    and the legacy flat shape."""
    inner = {"_worker_retry_count": 3, "note_path": "/x/y.md"}
    envelope = {
        "event_type": "panel.scan.requested",
        "event_id": "e" * 32,
        "payload": inner,
    }

    expected = outbox_worker._payload_retry_count(inner)
    assert (
        preflight._payload_retry_count(preflight._pending_row_inner_payload(envelope)) == expected
    )
    assert (
        preflight._payload_retry_count(preflight._pending_row_inner_payload(json.dumps(envelope)))
        == expected
    )
    # Legacy flat rows: the whole column value IS the payload.
    assert (
        preflight._payload_retry_count(preflight._pending_row_inner_payload(inner)) == expected
    )


class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows
        self.executed: list[tuple[str, dict]] = []

    def execute(self, sql: str, params: dict | None = None) -> None:
        self.executed.append((sql, dict(params or {})))

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FakeConn:
    def __init__(self, rows: list[tuple]) -> None:
        self.cursor_obj = _FakeCursor(rows)

    def cursor(self) -> _FakeCursor:
        return self.cursor_obj


def test_classification_boundary_tracks_live_worker_constants() -> None:
    """The corrected -1 boundary, pinned against the worker's OWN constants:
    the worker bumps attempts then dead-letters+acks in the same consume
    cycle, so a PENDING row at attempts == max - 1 is terminal (next
    non-transient failure dead-letters) while max - 2 still has a full retry
    cycle left. If the worker's budget changes, this test re-derives the
    boundary from the new value and the preflight must follow."""
    max_attempts = outbox_worker._MAX_DISPATCH_ATTEMPTS
    retry_budget = outbox_worker._MAX_TRANSIENT_RETRY_ATTEMPTS
    rows = [
        ("dispatch.terminal", {}, max_attempts - 1),
        ("dispatch.not-terminal", {}, max_attempts - 2),
        (
            "retry.terminal",
            {"event_type": "retry.terminal", "payload": {"_worker_retry_count": retry_budget}},
            0,
        ),
        (
            "retry.not-terminal",
            {
                "event_type": "retry.not-terminal",
                "payload": {"_worker_retry_count": retry_budget - 1},
            },
            0,
        ),
    ]
    conn = _FakeConn(rows)

    receipt = preflight.evaluate(conn, max_dispatch_attempts=max_attempts)

    assert receipt["status"] == "blocked"
    assert receipt["terminal_pending_count"] == 2
    assert receipt["by_topic"] == {"dispatch.terminal": 1, "retry.terminal": 1}
    assert receipt["by_classification"] == {
        "transient_retry_exhausted": 1,
        "dispatch_attempts_exhausted": 1,
    }
    assert receipt["thresholds"]["pending_attempts_threshold"] == max_attempts - 1
    # The server-side pre-filter must be threshold-parameterized the same way.
    sql, params = conn.cursor_obj.executed[0]
    assert "delivered_at is null" in sql
    assert params == {"attempts_threshold": max_attempts - 1}


def test_host_translation_constants_match_docker_compose_yaml_port_mapping() -> None:
    """H3 (#3903 round 6): pin _COMPOSE_INTERNAL_DB_HOST/_PROD_DB_HOST_PUBLISHED_PORT
    against the REAL docker-compose.yaml db service port mapping -- a
    source-of-truth pin, not a hand-duplicated constant. Without this, if the
    compose file's port mapping ever changed, the preflight would silently
    resolve a wrong host:port, hit a connection error, and fall into the SAME
    exit-0 skipped:db_unreachable path as an ordinary transient DB outage --
    nothing would distinguish "the gate is broken" from "the DB had a blip."

    docker-compose.yaml carries no !override/!reset tags (confirmed: those
    only appear in channel overlays), so a bare yaml.safe_load is faithful
    here without needing channel_isolation_preflight's tolerant loader.
    """
    compose_path = REPO_ROOT / "docker-compose.yaml"
    data = yaml.safe_load(compose_path.read_text(encoding="utf-8"))
    services = data.get("services") or {}

    db_service = services.get(preflight._COMPOSE_INTERNAL_DB_HOST)
    assert db_service is not None, (
        f"docker-compose.yaml has no service named "
        f"{preflight._COMPOSE_INTERNAL_DB_HOST!r} -- update "
        "_COMPOSE_INTERNAL_DB_HOST in scripts/prod_deploy_retry_preflight.py"
    )

    host_ports_for_5432: list[str] = []
    for entry in db_service.get("ports") or []:
        if isinstance(entry, str):
            # "HOST:CONTAINER" short syntax -- the only form this file uses today.
            host_part, sep, container_part = entry.rpartition(":")
            if sep and container_part.split("/")[0] == "5432" and host_part:
                host_ports_for_5432.append(host_part)
        elif isinstance(entry, dict) and str(entry.get("target")) == "5432":
            # Long mapping form, tolerated even though unused today.
            published = entry.get("published")
            if published is not None:
                host_ports_for_5432.append(str(published))

    assert host_ports_for_5432, (
        "docker-compose.yaml's db service no longer publishes container port "
        "5432 -- update _PROD_DB_HOST_PUBLISHED_PORT (or the whole host-"
        "translation approach) in scripts/prod_deploy_retry_preflight.py"
    )
    assert preflight._PROD_DB_HOST_PUBLISHED_PORT in host_ports_for_5432, (
        f"scripts/prod_deploy_retry_preflight.py's _PROD_DB_HOST_PUBLISHED_PORT "
        f"({preflight._PROD_DB_HOST_PUBLISHED_PORT!r}) no longer matches "
        f"docker-compose.yaml's actual db port mapping {host_ports_for_5432!r} "
        "-- update the constant to match."
    )


def test_host_reachable_dsn_uses_the_pinned_published_port() -> None:
    """_host_reachable_dsn's output must actually USE the pinned constants
    (not just have them defined) -- proves the translation function and the
    source-of-truth-pinned constant above stay wired together."""
    internal_dsn = (
        f"postgresql+psycopg://app:app@{preflight._COMPOSE_INTERNAL_DB_HOST}:5432/app"
    )

    translated = preflight._host_reachable_dsn(internal_dsn)

    assert f"127.0.0.1:{preflight._PROD_DB_HOST_PUBLISHED_PORT}" in translated
    assert preflight._COMPOSE_INTERNAL_DB_HOST + ":5432" not in translated
