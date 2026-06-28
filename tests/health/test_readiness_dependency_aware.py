"""Readiness reflects real dependency health (OBSSTAB-01 / #2598).

A live `ping_postgres()` is folded into `HealthContract.evaluate()` so a
Postgres outage forces state to `unhealthy` when `STORE_BACKEND=pg`. Because
`unhealthy` is in `WRITE_BLOCKED_STATES` and *not* in `READY_STATES`, `/readyz`
flips to 503 on DB-down (the false-green this slice exists to kill), while
`/healthz` stays an unconditional liveness probe.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.health_contract import HealthContract, HealthStateMachine

REPO_ROOT = Path(__file__).resolve().parents[2]


def _mock_index_doctor() -> dict[str, object]:
    return {
        "backend": "mock",
        "expected_identity": None,
        "stored_identity": None,
        "issues": [],
        "warnings": [],
    }


def _contract_with_ping(
    monkeypatch: pytest.MonkeyPatch,
    ping_result: tuple[bool, str],
    *,
    ping_calls: list[dict[str, object]] | None = None,
) -> HealthContract:
    """Build a contract whose DB ping is mocked and whose outbox state is healthy.

    `vault_root_fn` returns None (no vault selected) so settings load from
    defaults; with an empty outbox the state machine settles on `running`, which
    isolates the DB-ping short-circuit as the only thing that can flip readiness.
    The index doctor is stubbed so STORE_BACKEND=pg does not pull in a real
    Postgres connection via the unrelated index-diagnosis path.
    """
    monkeypatch.setattr("app.health_contract.diagnose_index", _mock_index_doctor)

    def fake_ping(*, timeout: float = 1.0, conninfo: object | None = None) -> tuple[bool, str]:
        if ping_calls is not None:
            ping_calls.append({"timeout": timeout, "conninfo": conninfo})
        return ping_result

    return HealthContract(
        state_machine=HealthStateMachine(),
        vault_root_fn=lambda: None,
        db_ping_fn=fake_ping,
    )


def _exploding_index_doctor(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Stub diagnose_index to RAISE and count calls (mimics the real pg-down path).

    On a real DB-down stack, diagnose_index() opens a second psycopg connection
    that raises/hangs. Stubbing it to raise — rather than to a no-op success —
    exercises the production path: it proves evaluate() short-circuits BEFORE the
    index diagnostic runs and that no exception escapes to turn 503 into 500.
    Returns a one-element call counter.
    """
    calls = [0]

    def boom() -> dict[str, object]:
        calls[0] += 1
        raise RuntimeError("DATABASE_URL is required for postgres store access")

    monkeypatch.setattr("app.health_contract.diagnose_index", boom)
    return calls


def test_readyz_flips_red_when_db_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """When Postgres is unreachable under STORE_BACKEND=pg, /readyz returns 503.

    Uses the production path: the index doctor (which itself hits the DB) is
    stubbed to raise, so a fall-through would 500 instead of 503.
    """
    monkeypatch.setenv("STORE_BACKEND", "pg")
    index_calls = _exploding_index_doctor(monkeypatch)

    def fake_ping(*, timeout: float = 1.0, conninfo: object | None = None) -> tuple[bool, str]:
        return False, "postgres unreachable (OperationalError)"

    contract = HealthContract(
        state_machine=HealthStateMachine(),
        vault_root_fn=lambda: None,
        db_ping_fn=fake_ping,
    )

    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.routes.health_contract.DEFAULT_CONTRACT.evaluate",
        contract.evaluate,
    )

    resp = client.get("/readyz")
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    # Must be unhealthy (write-blocked), NOT degraded (degraded is a READY state).
    assert detail["state"] == "unhealthy"
    assert "postgres" in detail["reason"].lower()

    # The snapshot itself must report the write-blocked, non-ready state.
    snapshot = contract.evaluate()
    assert snapshot["state"] == "unhealthy"
    assert snapshot["writes_allowed"] is False
    # Short-circuit proof: the DB-backed index diagnostic was never reached.
    assert index_calls[0] == 0, "evaluate() ran diagnose_index() after the DB ping failed"


def test_evaluate_short_circuits_before_db_diagnostics_on_db_down(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On a failed ping, evaluate() returns a full unhealthy snapshot and runs NO
    DB-backed diagnostic — no exception escapes (503 stays 503, never 500).

    This is the regression test for the P1: previously evaluate() set state to
    unhealthy but fell through into diagnose_index(), which opens a second psycopg
    connection that raises/hangs on a real DB-down stack.
    """
    monkeypatch.setenv("STORE_BACKEND", "pg")
    index_calls = _exploding_index_doctor(monkeypatch)

    def fake_ping(*, timeout: float = 1.0, conninfo: object | None = None) -> tuple[bool, str]:
        return False, "postgres unreachable (OperationalError)"

    contract = HealthContract(
        state_machine=HealthStateMachine(),
        vault_root_fn=lambda: None,
        db_ping_fn=fake_ping,
    )

    # Must NOT raise even though diagnose_index would.
    snapshot = contract.evaluate()

    assert index_calls[0] == 0, "diagnose_index() ran despite a failed DB ping"
    assert snapshot["state"] == "unhealthy"
    assert snapshot["writes_allowed"] is False
    assert snapshot["write_guard_reason"] and "postgres" in snapshot["write_guard_reason"].lower()
    assert "postgres" in snapshot["reason"].lower()
    # Full-shape parity: the keys /readyz, /status, and CLI consumers read are all
    # present so nothing downstream KeyErrors on the short-circuit snapshot.
    for key in (
        "environment",
        "state",
        "reason",
        "since_ts",
        "vault",
        "outbox_count",
        "outbox_recent_age_s",
        "store_object_count",
        "bootstrap_state",
        "bootstrap_reason",
        "embedding_identity",
        "index_doctor_status",
        "events_doctor_status",
        "errors_last_10m",
        "settings_status",
        "settings_source",
        "settings_errors",
        "thresholds",
        "writes_allowed",
        "write_guard_reason",
        "catch_up_progress",
        "suggested_actions",
    ):
        assert key in snapshot, f"short-circuit snapshot missing key: {key}"


def test_container_healthcheck_targets_readyz() -> None:
    """All three API_HEALTHCHECK_URL sources point at /readyz, not /healthz."""
    sources = [
        REPO_ROOT / "config" / "runtime.defaults.env",
        REPO_ROOT / "docker-compose.test.yml",
        REPO_ROOT / "docker-compose.prod.yml",
    ]
    pattern = re.compile(r"API_HEALTHCHECK_URL\s*[:=]\s*(\S+)")
    found = 0
    for source in sources:
        text = source.read_text(encoding="utf-8")
        matches = pattern.findall(text)
        assert matches, f"no API_HEALTHCHECK_URL definition found in {source}"
        for url in matches:
            found += 1
            assert url.rstrip().endswith("/readyz"), (
                f"{source} still targets {url!r}; must end with /readyz"
            )
    assert found >= 3, f"expected at least 3 API_HEALTHCHECK_URL definitions, found {found}"


def test_evaluate_db_ping_bounded_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """evaluate() pings the DB with a bounded (<=1 s) timeout and never hangs."""
    monkeypatch.setenv("STORE_BACKEND", "pg")
    ping_calls: list[dict[str, object]] = []
    contract = _contract_with_ping(monkeypatch, (True, "postgres reachable"), ping_calls=ping_calls)

    start = time.monotonic()
    snapshot = contract.evaluate()
    elapsed = time.monotonic() - start

    # The ping ran with a bounded timeout.
    assert ping_calls, "evaluate() did not invoke the DB ping under STORE_BACKEND=pg"
    assert all(call["timeout"] <= 1.0 for call in ping_calls), (
        f"DB ping timeout exceeds 1.0s bound: {ping_calls}"
    )
    # The probe returned promptly (mocked ping is instant; the wall-clock proves
    # evaluate() does not block on a slow path around the ping).
    assert elapsed < 5.0, f"evaluate() took {elapsed:.2f}s; probe must not hang"
    # A healthy ping leaves the outbox-derived state intact (not forced unhealthy).
    assert snapshot["state"] != "unhealthy"


def test_evaluate_db_ping_skipped_when_backend_not_pg(monkeypatch: pytest.MonkeyPatch) -> None:
    """The DB ping only gates readiness when STORE_BACKEND=pg (memory backend unaffected)."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    ping_calls: list[dict[str, object]] = []
    contract = _contract_with_ping(monkeypatch, (False, "postgres unreachable"), ping_calls=ping_calls)

    snapshot = contract.evaluate()
    assert ping_calls == [], "DB ping must not run when STORE_BACKEND != pg"
    assert snapshot["state"] != "unhealthy"


def test_healthz_still_liveness_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """/healthz stays an unconditional {'ok': true} liveness probe regardless of DB state."""
    monkeypatch.setenv("STORE_BACKEND", "pg")
    contract = _contract_with_ping(monkeypatch, (False, "postgres unreachable (OperationalError)"))

    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.routes.health_contract.DEFAULT_CONTRACT.evaluate",
        contract.evaluate,
    )

    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
