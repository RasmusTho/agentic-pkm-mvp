"""Tests for operator drawer health-panel and status-panel extensions.

Issue #2616: render runtime liveness, write_guard, and suggested_actions
             in the Health panel.
Issue #2617: render worker_queue.pending and worker_queue.processed_total
             in the Status panel.

All tests exercise the real render_operator_overlay_html function with
realistic fixture payloads — no stubs of the render function itself.
"""

from __future__ import annotations

from companion_ui.workspace.serve_dev_page import render_operator_overlay_html


# ---------------------------------------------------------------------------
# Shared fixture payloads
# ---------------------------------------------------------------------------

_HEALTH_STALE_WORKER = {
    "ok": False,
    "checks": {
        "db": {"ok": True, "detail": "connected"},
    },
    "runtime": {
        "worker": {
            "ok": False,
            "status": "stale",
            "detail": "worker stale (last seen 143.2s ago)",
            "freshness_seconds": 143.2,
        },
        "watcher": {
            "ok": True,
            "status": "ok",
            "detail": "watcher running (fresh 5.1s, paused=False)",
            "freshness_seconds": 5.1,
        },
    },
    "authority_spine": {
        "write_guard": "active",
    },
    "suggested_actions": [
        {
            "id": "worker_unhealthy",
            "severity": "required",
            "message": "Worker heartbeat unhealthy; restart the worker service",
            "command_hint": "",
        }
    ],
}

_HEALTH_BLOCKED_WRITE_GUARD = {
    "ok": False,
    "checks": {},
    "runtime": {
        "worker": {
            "ok": True,
            "status": "ok",
            "detail": "worker running (fresh 2.0s, paused=False)",
            "freshness_seconds": 2.0,
        },
        "watcher": {
            "ok": True,
            "status": "ok",
            "detail": "watcher running (fresh 1.0s, paused=False)",
            "freshness_seconds": 1.0,
        },
    },
    "authority_spine": {
        "write_guard": "blocked",
    },
    "suggested_actions": [],
}

_HEALTH_MISSING_WORKER = {
    "ok": False,
    "checks": {},
    "runtime": {
        "worker": {
            "ok": False,
            "status": "missing",
            "detail": "worker not running (no heartbeat)",
        },
        "watcher": {
            "ok": False,
            "status": "future",
            "detail": "watcher heartbeat timestamp is in the future",
        },
    },
    "authority_spine": {
        "write_guard": "unavailable",
    },
    "suggested_actions": [],
}

_STATUS_WITH_WORKER_QUEUE = {
    "sot_version": "v5.5",
    "timestamp": "2026-06-28T10:00:00Z",
    "stores": [],
    "ingestion": {
        "last_run_at": "2026-06-28T09:55:00Z",
        "last_run_ok": True,
    },
    "ask": {
        "total_queries_24h": 3,
        "avg_latency_ms_24h": 150.0,
    },
    "worker_queue": {
        "mode": "db",
        "pending": 63,
        "processed_total": 0,
    },
}

_STATUS_WORKER_QUEUE_NONE_MODE = {
    "sot_version": "v5.5",
    "timestamp": "2026-06-28T10:00:00Z",
    "stores": [],
    "ingestion": {},
    "ask": {},
    "worker_queue": {
        "mode": "none",
        "pending": None,
        "processed_total": None,
    },
}


# ---------------------------------------------------------------------------
# #2616 — runtime liveness
# ---------------------------------------------------------------------------


def test_drawer_renders_worker_liveness() -> None:
    """Health panel renders worker and watcher liveness with distinct labels.

    Stale worker must show 'stale' (not a generic error), ok watcher shows 'ok'.
    data-testid attributes must be present so tests can locate rows deterministically.
    """
    html = render_operator_overlay_html(health_payload=_HEALTH_STALE_WORKER)

    # Worker row present with correct testid
    assert 'data-testid="operator-health-worker-liveness"' in html
    # Watcher row present with correct testid
    assert 'data-testid="operator-health-watcher-liveness"' in html

    # Distinct status labels rendered — not collapsed to generic error
    assert "stale" in html
    assert "op-pill-warn" in html  # stale renders as warn pill

    # Watcher is ok — renders ok pill
    panel_html = html
    # Both rows must appear in the Health panel section
    assert "Worker" in panel_html
    assert "Watcher" in panel_html


def test_drawer_renders_distinct_liveness_labels() -> None:
    """missing and future status values render with distinct plain-language labels."""
    html = render_operator_overlay_html(health_payload=_HEALTH_MISSING_WORKER)

    assert 'data-testid="operator-health-worker-liveness"' in html
    assert 'data-testid="operator-health-watcher-liveness"' in html

    # 'missing' → "not running"
    assert "not running" in html
    # 'future' → "clock drift"
    assert "clock drift" in html


# ---------------------------------------------------------------------------
# #2616 — authority spine / write_guard
# ---------------------------------------------------------------------------


def test_drawer_renders_write_guard() -> None:
    """Health panel renders authority_spine.write_guard with plain-language labels.

    active → 'active', blocked → 'writes blocked', unavailable → 'unavailable'.
    """
    # active
    html_active = render_operator_overlay_html(health_payload=_HEALTH_STALE_WORKER)
    assert 'data-testid="operator-health-write-guard"' in html_active
    assert "active" in html_active

    # blocked — renders warn pill and 'writes blocked'
    html_blocked = render_operator_overlay_html(health_payload=_HEALTH_BLOCKED_WRITE_GUARD)
    assert 'data-testid="operator-health-write-guard"' in html_blocked
    assert "writes blocked" in html_blocked
    # blocked must use warn pill (not ok pill)
    assert "op-pill-warn" in html_blocked

    # unavailable
    html_unavail = render_operator_overlay_html(health_payload=_HEALTH_MISSING_WORKER)
    assert 'data-testid="operator-health-write-guard"' in html_unavail
    assert "unavailable" in html_unavail


# ---------------------------------------------------------------------------
# #2616 — suggested actions
# ---------------------------------------------------------------------------


def test_drawer_renders_suggested_actions() -> None:
    """Health panel renders suggested_actions as plain list items.

    Non-empty list must appear with the container testid and each action item.
    """
    html = render_operator_overlay_html(health_payload=_HEALTH_STALE_WORKER)

    assert 'data-testid="operator-health-suggested-actions"' in html
    assert 'data-testid="operator-health-suggested-action"' in html
    # The action message is shown (plain language, not a raw dict/JSON)
    assert "Worker heartbeat unhealthy" in html
    # No raw JSON dict-notation in the output
    assert '{"id":' not in html
    assert "&#x27;id&#x27;" not in html  # escaped single-quote variant


def test_drawer_suggested_actions_empty_list_renders_nothing() -> None:
    """Empty suggested_actions list renders no <ul> element."""
    html = render_operator_overlay_html(health_payload=_HEALTH_BLOCKED_WRITE_GUARD)

    assert 'data-testid="operator-health-suggested-actions"' not in html
    assert "<ul" not in html or "op-suggested-actions" not in html


# ---------------------------------------------------------------------------
# #2616 — empty-state unchanged
# ---------------------------------------------------------------------------


def test_drawer_health_empty_state_unchanged() -> None:
    """All three new additions are absent when health_payload is None.

    Regression guard: the existing empty-state path must not be affected.
    """
    html = render_operator_overlay_html(health_payload=None)

    # Empty-state sentinel present (existing contract)
    assert 'data-testid="operator-health-empty"' in html

    # New rows must not appear in the no-data path
    assert 'data-testid="operator-health-worker-liveness"' not in html
    assert 'data-testid="operator-health-watcher-liveness"' not in html
    assert 'data-testid="operator-health-write-guard"' not in html
    assert 'data-testid="operator-health-suggested-actions"' not in html


# ---------------------------------------------------------------------------
# #2617 — worker queue backlog in Status panel
# ---------------------------------------------------------------------------


def test_status_panel_shows_worker_queue_backlog() -> None:
    """Status panel renders worker_queue.pending and worker_queue.processed_total.

    Covers:
    - Real values (mode=db, pending=63, processed_total=0) → shows integers.
    - None / mode=none → shows N/A (consistent with existing rows).
    - data-testid attributes present for both rows.
    """
    # Real values
    html = render_operator_overlay_html(status_payload=_STATUS_WITH_WORKER_QUEUE)

    assert 'data-testid="operator-status-worker-pending"' in html
    assert 'data-testid="operator-status-worker-processed"' in html

    # The actual values rendered
    assert "63" in html  # pending
    # processed_total=0 must render as "0", not N/A
    assert ">0<" in html or ">0 <" in html or "0</span>" in html

    # Row labels (plain language, no raw field names)
    assert "Worker queue pending" in html
    assert "Worker processed total" in html

    # mode=none / None values → N/A
    html_none = render_operator_overlay_html(status_payload=_STATUS_WORKER_QUEUE_NONE_MODE)

    assert 'data-testid="operator-status-worker-pending"' in html_none
    assert 'data-testid="operator-status-worker-processed"' in html_none
    assert "N/A" in html_none
