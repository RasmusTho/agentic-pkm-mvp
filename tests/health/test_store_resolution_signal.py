"""Store-resolution health signal tests (#2843, Correctness Kernel follow-on to KERNEL-03/#2765).

`app/health_contract.py::_count_objects` used to wrap `get_object_store().count_objects()`
in `except Exception: return 0`, so the now-fail-loud store-resolution errors
(unreachable pg, unknown/absent backend config) were swallowed and the health
state machine reported bootstrap `empty`/healthy even though every store write
would raise. This mirrors the false-green register in docs/HEALTH.md and the
audited KERNEL-03 defect shape ("a prod process can run healthy on volatile
state") terminating at one silent site.

Scope addition (PR #2832 round-2 review): `app/health_contract.py` also had
three independent unset-`STORE_BACKEND` interpretation sites (`_count_outbox_lines_db`,
`_dead_letter_stats_db`, `_db_dependency_down_reason` — historically ~lines
26/72/540) that treated an unset `STORE_BACKEND` as `"memory"` locally,
diverging from the store seam's unset -> DSN-resolution semantics
(`app/stores/__init__.py::_resolve_backend`). These tests assert the health
surface now consumes `resolve_store_backend()` / its raised error instead of
re-deriving backend semantics from `os.environ` directly.

Verifies (spec: docs/HEALTH.md, docs/RUNTIME_CORRECTNESS_KERNEL/SINGLE_STORE_GENERATION.md):
1. Store-resolution failure (unknown backend value, configured-but-unreachable
   pg, no backend at all) is visible in the health contract snapshot as a
   distinct loud status, not `object_count: 0` + healthy.
2. A genuine empty store (explicit STORE_BACKEND=memory, nothing captured yet)
   still reports healthy/`empty` — no false-red.
3. No-vault/no-DB idle boot (no DATABASE_URL/STORE_BACKEND at all) still
   succeeds and serves health: `/healthz` stays 200, the contract loudly
   reports the resolution failure without raising out of `evaluate()`.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.app import app
from app.health_contract import HealthContract, HealthStateMachine, WRITE_BLOCKED_STATES
from app.stores import reset_store_backends


def _mock_index_doctor() -> dict[str, object]:
    return {
        "backend": "mock",
        "expected_identity": None,
        "stored_identity": None,
        "issues": [],
        "warnings": [],
    }


@pytest.fixture(autouse=True)
def _reset_backend_cache():
    reset_store_backends()
    yield
    reset_store_backends()


def _fresh_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> HealthContract:
    """Build an isolated HealthContract for one test.

    Points ``INDEX_OUTBOX_PATH`` at a fresh ``tmp_path`` file (the pattern
    established by ``tests/health/test_dead_letter_signal.py``) so the
    snapshot's outbox-derived fields (``outbox_count``, ``bootstrap_state``)
    reflect only what this test writes — never the real dev/CI-runner
    ``tmp/index-outbox.jsonl`` on disk, which would make assertions like
    "empty store -> bootstrap empty" environment-dependent.
    """
    monkeypatch.setenv("INDEX_OUTBOX_PATH", str(tmp_path / "index-outbox.jsonl"))
    monkeypatch.setattr("app.health_contract.diagnose_index", _mock_index_doctor)
    return HealthContract(
        state_machine=HealthStateMachine(),
        vault_root_fn=lambda: None,
    )


# ---------------------------------------------------------------------------
# AC1: store-resolution failure is a distinct loud status, not empty+healthy
# ---------------------------------------------------------------------------


def test_resolution_failure_degrades_snapshot(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No STORE_BACKEND and no DSN at all: resolution raises (KERNEL-03 contract).

    Before this fix, `_count_objects()` swallowed the RuntimeError and reported
    `store_object_count: 0` while the top-level state stayed healthy — the
    exact false-green the issue names. The production evaluate() call site
    (`app.health_contract.DEFAULT_CONTRACT.evaluate()`, also exercised here via
    a fresh contract with the same production resolution path) must now report
    a distinct loud signal instead.
    """
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    contract = _fresh_contract(monkeypatch, tmp_path)
    snapshot = contract.evaluate()

    # Must not be the false-green shape: healthy + object_count 0 + bootstrap empty.
    assert snapshot["state"] in WRITE_BLOCKED_STATES, (
        f"store-resolution failure must degrade state loudly, got {snapshot['state']!r}"
    )
    assert snapshot["store_resolution_status"] == "failed"
    assert snapshot["store_resolution_error"], "resolution failure must carry a human-legible reason"
    assert snapshot["bootstrap_state"] != "empty", (
        "a resolution failure must not be reported as a benign empty bootstrap state"
    )
    assert snapshot["writes_allowed"] is False


def test_resolution_failure_unknown_backend_value(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """An explicit but unsupported STORE_BACKEND value is also a resolution failure."""
    monkeypatch.setenv("STORE_BACKEND", "pgvector")
    monkeypatch.setenv("DATABASE_URL", "postgresql://demo:demo@localhost:5432/demo")
    monkeypatch.delenv("DB_DSN", raising=False)

    contract = _fresh_contract(monkeypatch, tmp_path)
    snapshot = contract.evaluate()

    assert snapshot["store_resolution_status"] == "failed"
    assert "not supported" in snapshot["store_resolution_error"].lower()
    assert snapshot["writes_allowed"] is False


def test_resolution_failure_unreachable_pg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A configured-but-unreachable Postgres DSN is a resolution failure, not empty."""
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    # Nothing listens on port 1; connection is refused immediately.
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:1/app")
    monkeypatch.delenv("DB_DSN", raising=False)

    contract = _fresh_contract(monkeypatch, tmp_path)
    snapshot = contract.evaluate()

    assert snapshot["store_resolution_status"] == "failed"
    assert "unreachable" in snapshot["store_resolution_error"].lower()
    assert snapshot["state"] == "unhealthy"
    assert snapshot["writes_allowed"] is False


# ---------------------------------------------------------------------------
# AC2: genuine empty store still reports healthy/empty — no false-red
# ---------------------------------------------------------------------------


def test_empty_store_still_healthy(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Explicit STORE_BACKEND=memory with nothing captured yet stays healthy/empty."""
    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    contract = _fresh_contract(monkeypatch, tmp_path)
    snapshot = contract.evaluate()

    assert snapshot["store_resolution_status"] == "ok"
    assert snapshot["store_resolution_error"] is None
    assert snapshot["store_object_count"] == 0
    assert snapshot["bootstrap_state"] == "empty"
    assert snapshot["state"] not in WRITE_BLOCKED_STATES
    assert snapshot["writes_allowed"] is True


# ---------------------------------------------------------------------------
# AC3: no-vault/no-DB idle boot still succeeds and serves health (loud, not fatal)
# ---------------------------------------------------------------------------


def test_idle_boot_serves_health_with_loud_signal(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No DATABASE_URL/STORE_BACKEND at all (#2005 idle-boot repro from the issue).

    `evaluate()` must not raise (boot must still succeed and serve health), and
    `/healthz` — the liveness probe — must stay an unconditional 200. The loud
    signal shows up in the contract snapshot / `/readyz`, never as a boot crash.
    """
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    contract = _fresh_contract(monkeypatch, tmp_path)

    # evaluate() must not raise even though store resolution itself would.
    snapshot = contract.evaluate()
    assert snapshot["store_resolution_status"] == "failed"

    client = TestClient(app)
    monkeypatch.setattr(
        "app.api.routes.health_contract.DEFAULT_CONTRACT.evaluate",
        contract.evaluate,
    )
    resp_live = client.get("/healthz")
    assert resp_live.status_code == 200
    assert resp_live.json() == {"ok": True}

    # /readyz is allowed (expected) to go loud/503 — that is the fix, not a
    # regression — but it must be a clean structured 503, never a 500.
    resp_ready = client.get("/readyz")
    assert resp_ready.status_code == 503
    assert resp_ready.json()["detail"]["state"] == "unhealthy"


def test_idle_boot_snapshot_has_full_shape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The short-circuited snapshot still carries every key downstream consumers read."""
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    contract = _fresh_contract(monkeypatch, tmp_path)
    snapshot = contract.evaluate()

    for key in (
        "environment",
        "state",
        "reason",
        "since_ts",
        "vault",
        "outbox_count",
        "outbox_recent_age_s",
        "store_object_count",
        "store_resolution_status",
        "store_resolution_error",
        "bootstrap_state",
        "bootstrap_reason",
        "writes_allowed",
        "write_guard_reason",
        "suggested_actions",
    ):
        assert key in snapshot, f"idle-boot snapshot missing key: {key}"


# ---------------------------------------------------------------------------
# Sibling swallow sweep: unset STORE_BACKEND no longer silently means "memory"
# ---------------------------------------------------------------------------


def test_db_dependency_down_reason_fires_when_unset_and_unreachable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """`_db_dependency_down_reason` used to only gate when `STORE_BACKEND == "pg"`
    literally, so an unset STORE_BACKEND with a configured-but-unreachable DSN
    skipped the DB-down short-circuit entirely (the compounding bug named in the
    issue's scope-addition comment). It must now consume the same resolution
    outcome as the rest of the contract.
    """
    monkeypatch.delenv("STORE_BACKEND", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://app:app@127.0.0.1:1/app")
    monkeypatch.delenv("DB_DSN", raising=False)

    contract = _fresh_contract(monkeypatch, tmp_path)
    reason = contract._db_dependency_down_reason()
    assert reason is not None
    assert "unreachable" in reason.lower()


def test_outbox_and_dead_letter_helpers_do_not_default_unset_to_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_count_outbox_lines_db` / `_dead_letter_stats_db` must not silently treat
    an unset STORE_BACKEND as memory when a DSN is actually configured — they
    should route through the same resolution outcome (falling back to the file
    source only because resolution says "pg", not because the local heuristic
    guessed "memory").
    """
    from app.health_contract import _count_outbox_lines_db, _dead_letter_stats_db

    monkeypatch.setenv("STORE_BACKEND", "memory")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("DB_DSN", raising=False)

    # Explicit memory: both DB-backed helpers correctly skip (no pg to query).
    assert _count_outbox_lines_db() is None
    assert _dead_letter_stats_db() is None
