"""Architecture map — CRE pull path (diagram arrows 1 + 2; issue #1958, merged via PR #1963).

These tests pin the part of the v6.1 map that is *already wired*: the watcher
context tick computes moments from vault data (arrow 1) and the read-only glance
route surfaces them (arrow 2). They are expected to PASS — that is the proof the
pull path is not dormant.

The deep end-to-end (tick -> moment artifact -> ``GET /api/companion/now``) is
already covered by ``tests/relevance/test_runtime_tick.py``; here we pin the
*wiring contract* around it so it cannot silently regress to dormancy.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import app.watcher.watcher as watcher_mod
from app.api.app import app as fastapi_app
from app.relevance import materialize_moment
from app.watcher.relevance_tick import relevance_tick_enabled, run_relevance_tick


def test_relevance_tick_is_on_by_default_and_flag_disables(monkeypatch) -> None:
    """The tick runs by default; an operator can turn it off with the flag."""

    monkeypatch.delenv("RELEVANCE_TICK_ENABLED", raising=False)
    assert relevance_tick_enabled() is True
    monkeypatch.setenv("RELEVANCE_TICK_ENABLED", "0")
    assert relevance_tick_enabled() is False


def test_relevance_tick_is_fault_isolated_for_a_non_vault(tmp_path: Path) -> None:
    """The tick must never raise for an unselected/garbage vault — it skips.

    This is what lets the watcher core call it without the relevance engine
    being able to break the main loop.
    """

    summary = run_relevance_tick(tmp_path)
    assert summary["materialized"] == 0
    assert summary.get("skipped")


def test_watcher_loop_invokes_the_relevance_tick() -> None:
    """Arrow 1 is real: the watcher loop calls the tick, guarded by the flag and
    isolated behind try/except so a relevance failure cannot stop the watcher."""

    src = inspect.getsource(watcher_mod)
    assert "run_relevance_tick" in src, "watcher must invoke the relevance tick"
    assert "relevance_tick_enabled" in src, "the tick must be flag-gated in the loop"
    assert "relevance_tick_error" in src, "the tick call must be fault-isolated"


def test_moment_materialization_is_governed() -> None:
    """Spine: materializing a moment routes through the WriteGuard (governed write)."""

    assert "assert_writes_allowed" in inspect.getsource(materialize_moment)


def test_glance_now_surface_is_read_only_pull() -> None:
    """Arrow 2 is pull-only: ``/api/companion/now`` exposes GET, never a write verb."""

    methods: set[str] = set()
    for route in fastapi_app.routes:
        if getattr(route, "path", None) == "/api/companion/now":
            methods |= set(getattr(route, "methods", set()) or set())
    assert methods, "the glance /now route must be registered"
    assert methods <= {"GET", "HEAD", "OPTIONS"}, f"glance must be read-only, got {methods}"
