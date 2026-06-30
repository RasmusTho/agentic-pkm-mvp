"""Ambient health glyph regressions for worker and watcher liveness mapping."""

from __future__ import annotations

import re
from typing import Any

from companion_ui.workspace.serve_dev_page import render_index_html


def _orientation_payload() -> dict[str, Any]:
    return {
        "scope": {"kind": "workspace", "vault_id": "test-vault", "channel": "test"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": "2026-06-30T12:00:00+00:00",
            "trace_id": "trace-test-1",
            "freshness": "fresh",
            "stale_after": "2026-06-30T12:05:00+00:00",
            "degraded_reasons": [],
        },
        "leave_point": None,
        "open_loops": [],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "governance": {
            "pending_proposal_count": 0,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": "logged",
        },
        "guards": {"degraded": False, "runtime_posture": "ok"},
    }


def _health_payload(
    *,
    worker_status: str = "ok",
    worker_ok: bool = True,
    watcher_status: str = "ok",
    watcher_ok: bool = True,
    db_ok: bool = True,
    llm_ok: bool = True,
) -> dict[str, Any]:
    write_guard_ok = True
    required_ok = worker_ok and watcher_ok and db_ok and llm_ok
    return {
        "required_ok": required_ok,
        "ok": required_ok and write_guard_ok,
        "checks": {},
        "authority_spine": {"write_guard": "active"},
        "runtime": {
            "worker": {"status": worker_status, "ok": worker_ok},
            "watcher": {"status": watcher_status, "ok": watcher_ok},
            "db": {"status": "ok" if db_ok else "fail", "ok": db_ok},
            "llm": {"status": "ok" if llm_ok else "fail", "ok": llm_ok},
        },
        "suggested_actions": [],
    }


def _render_entry(health: dict[str, Any]) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(),
        health=health,
    )


def _glyph_state(html: str) -> str:
    match = re.search(r'data-health-state="([^"]+)"', html)
    assert match, "operator-health-glyph state must be present in HTML"
    return match.group(1)


def test_stalled_worker_renders_attention_not_down() -> None:
    html = _render_entry(
        _health_payload(worker_status="stalled", worker_ok=False),
    )

    assert _glyph_state(html) == "uppmärksamhet"
    assert 'data-health-state="nere"' not in html


def test_dead_watcher_never_renders_healthy() -> None:
    for watcher_status in ("dead", "stale"):
        html = _render_entry(
            _health_payload(
                worker_status="ok",
                worker_ok=True,
                watcher_status=watcher_status,
                watcher_ok=False,
            ),
        )

        assert _glyph_state(html) == "uppmärksamhet"
        assert 'data-health-state="frisk"' not in html


def test_core_dependency_failure_still_renders_down() -> None:
    html = _render_entry(
        _health_payload(
            worker_status="ok",
            worker_ok=True,
            watcher_status="ok",
            watcher_ok=True,
            db_ok=False,
        ),
    )

    assert _glyph_state(html) == "nere"
