"""Tests for Operator diagnostics overlay pure render function (issue #1758).

These tests exercise render_operator_overlay_html as a pure function over
fixture payloads — no network calls, no live runtime, no vault reads.

Constraints verified:
- Document-first / overlay-first: overlay is a drawer that dims workspace.
- Server declares, UI renders: render function is pure over payloads.
- No hidden semantic state: unreachable/degraded renders explicitly (amber).
- Operator-badged: overlay carries the Operator badge marker.
"""

from __future__ import annotations

from companion_ui.workspace.serve_dev_page import render_operator_overlay_html


# ---------------------------------------------------------------------------
# Fixture payloads
# ---------------------------------------------------------------------------

_STATUS_PAYLOAD = {
    "sot_version": "v5.5",
    "timestamp": "2026-06-09T10:00:00Z",
    "stores": [
        {
            "name": "chroma",
            "object_count": 42,
            "last_ingest_at": "2026-06-09T09:55:00Z",
            "last_error_at": None,
        }
    ],
    "ingestion": {
        "last_run_at": "2026-06-09T09:55:00Z",
        "last_run_ok": True,
        "last_error_at": None,
    },
    "ask": {
        "total_queries_24h": 7,
        "avg_latency_ms_24h": 230.5,
        "error_count_24h": 0,
    },
}

_HEALTH_PAYLOAD = {
    "ok": True,
    "checks": {
        "db": {"ok": True, "detail": "connected"},
        "vault": {"ok": True, "detail": "mounted"},
    },
}

_SETTINGS_PAYLOAD = {
    "ok": True,
    "issues": [],
}

_EVENTS_PAYLOAD = {
    "events": [
        {
            "timestamp": "2026-06-09T10:00:00Z",
            "event_type": "watcher.tick",
            "trace_id": "abc123def456",
        }
    ]
}


# ---------------------------------------------------------------------------
# test_operator_overlay_renders_all_panels
# ---------------------------------------------------------------------------


def test_operator_overlay_renders_all_panels() -> None:
    """Overlay renders Status, Health, Settings validation, Recent events panels
    and the Ask input from fixture payloads via the pure render function."""
    html = render_operator_overlay_html(
        status_payload=_STATUS_PAYLOAD,
        health_payload=_HEALTH_PAYLOAD,
        settings_payload=_SETTINGS_PAYLOAD,
        events_payload=_EVENTS_PAYLOAD,
    )

    # All four panels present
    assert 'data-testid="operator-panel-status"' in html
    assert 'data-testid="operator-panel-health"' in html
    assert 'data-testid="operator-panel-settings"' in html
    assert 'data-testid="operator-panel-events"' in html

    # Ask input present
    assert 'data-testid="operator-ask-input"' in html
    assert 'data-testid="operator-ask-btn"' in html
    assert 'data-testid="operator-ask-answer"' in html
    assert 'data-testid="operator-panel-ask"' in html

    # Status data rendered
    assert "v5.5" in html  # sot_version
    assert "chroma" in html  # store name
    assert "42" in html  # object_count

    # Health data rendered
    assert "db" in html
    assert "vault" in html
    assert "connected" in html

    # Events data rendered
    assert "watcher.tick" in html
    assert "abc123def4" in html  # trace truncated to 12 chars

    # Ask JS wires to same-origin /api/operator/ask
    assert "/api/operator/ask" in html


def test_operator_overlay_renders_event_field_across_shapes() -> None:
    """The Event column falls back across `event`, `event_type`, and `topic`.

    Regression guard for PR #1770 Codex P2: the events-tail JSONL shape is not
    uniform — the common record uses `event`, some use `event_type`, and the
    outbox uses `topic`. A populated tail must never render a blank Event column.
    """
    payload = {
        "events": [
            {"timestamp": "t1", "event": "panel.confirm", "trace_id": "aaa"},
            {"timestamp": "t2", "event_type": "watcher.tick", "trace_id": "bbb"},
            {"timestamp": "t3", "topic": "outbox.flush", "trace_id": "ccc"},
        ]
    }

    html = render_operator_overlay_html(
        status_payload=_STATUS_PAYLOAD,
        health_payload=_HEALTH_PAYLOAD,
        settings_payload=_SETTINGS_PAYLOAD,
        events_payload=payload,
    )

    assert "panel.confirm" in html  # `event`
    assert "watcher.tick" in html   # `event_type`
    assert "outbox.flush" in html   # `topic`


# ---------------------------------------------------------------------------
# test_operator_overlay_is_operator_badged_and_dims_workspace
# ---------------------------------------------------------------------------


def test_operator_overlay_is_operator_badged_and_dims_workspace() -> None:
    """Overlay carries Operator badge and the drawer dims the workspace.

    The render function must include:
    - An Operator badge marker (data-testid=operator-badge)
    - The operator-panels container (no entry point inside the document flow)
    """
    html = render_operator_overlay_html(
        status_payload=_STATUS_PAYLOAD,
        health_payload=_HEALTH_PAYLOAD,
        settings_payload=_SETTINGS_PAYLOAD,
        events_payload=_EVENTS_PAYLOAD,
    )

    # Operator badge present
    assert 'data-testid="operator-badge"' in html
    assert "Operator" in html

    # Panels container present (drawer entry point)
    assert 'data-testid="operator-overlay-panels"' in html

    # Amber/operator color class used (not cyan/vault/agent which are daily-use)
    assert "op-badge" in html


def test_operator_layer_and_drawer_in_shell_html() -> None:
    """The full shell HTML (render_index_html) must contain the Operator drawer
    (the operator layer) reachable via the System Map operator node in both note
    view and production profile — no dev/prod split.

    CUIDR-04 (#2447): the floating Operator pill is removed from the front edge;
    the operator layer is reached one level deeper, from the System Map's
    operator node (operator.open). The drawer/host/badge must still be present.
    """
    import re

    from companion_ui.workspace.serve_dev_page import render_index_html

    def _operator_node(html: str) -> str:
        m = re.search(r'<button[^>]*data-surface-id="operator"[^>]*>', html)
        assert m, "operator must be reachable via the System Map operator node"
        return m.group(0)

    # Note view
    html_note = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        fields={
            "title": "Test Note",
            "note_path": "Notes/test.md",
            "artifact_id": "art-1",
            "content_hash": "hash-1",
            "body": "# Test",
            "runtime_environment_label": "dev",
            "runtime_api_base_url_label": "local-dev",
            "guard_writeguard_status": "ok",
            "guard_canvas_enabled": False,
            "guard_degraded": False,
        },
    )
    # The floating front-edge operator pill is gone; the operator layer is
    # reached from the System Map operator node instead.
    assert 'class="operator-toggle"' not in html_note
    assert 'data-intent="operator.open"' in _operator_node(html_note)
    assert 'data-testid="workspace-operator-host"' in html_note
    assert 'data-testid="workspace-operator-drawer"' in html_note
    assert 'data-testid="workspace-operator-badge"' in html_note

    # Production profile — same operator layer present (no dev/prod split)
    html_prod = render_index_html(
        api_base_url="http://127.0.0.1:18000",
        production_profile=True,
        fields={
            "title": "Prod Note",
            "note_path": "Notes/prod.md",
            "artifact_id": "art-p",
            "content_hash": "hash-p",
            "body": "# Prod",
            "runtime_environment_label": "prod",
            "runtime_api_base_url_label": "local-prod",
            "guard_writeguard_status": "ok",
            "guard_canvas_enabled": False,
            "guard_degraded": False,
        },
    )
    assert 'class="operator-toggle"' not in html_prod
    assert 'data-intent="operator.open"' in _operator_node(html_prod)
    assert 'data-testid="workspace-operator-host"' in html_prod


# ---------------------------------------------------------------------------
# test_unreachable_runtime_renders_explicit_degraded_state
# ---------------------------------------------------------------------------


def test_unreachable_runtime_renders_explicit_degraded_state() -> None:
    """An unreachable runtime (all sub-endpoints fail) renders an explicit
    degraded state banner for each panel — not a blank or stale panel."""
    error_msg = "Runtime endpoint unreachable — diagnostics unavailable."
    html = render_operator_overlay_html(
        status_error=error_msg,
        health_error=error_msg,
        settings_error=error_msg,
        events_error=error_msg,
    )

    # All four panels still render their containers
    assert 'data-testid="operator-panel-status"' in html
    assert 'data-testid="operator-panel-health"' in html
    assert 'data-testid="operator-panel-settings"' in html
    assert 'data-testid="operator-panel-events"' in html

    # Each degraded panel shows an explicit amber degraded banner
    # (data-state=degraded, data-testid=operator-degraded-banner)
    degraded_count = html.count('data-state="degraded"')
    assert degraded_count >= 4, (
        f"Expected at least 4 degraded banners (one per panel), got {degraded_count}"
    )
    assert html.count('data-testid="operator-degraded-banner"') >= 4

    # Error message text is rendered (escaped)
    assert "unreachable" in html

    # No silent blank: panels do NOT render empty-data placeholders
    assert 'data-testid="operator-status-empty"' not in html
    assert 'data-testid="operator-health-empty"' not in html
    assert 'data-testid="operator-settings-empty"' not in html
    assert 'data-testid="operator-events-empty"' not in html


def test_partial_unreachable_renders_degraded_only_for_failed_panels() -> None:
    """Only the failed sub-endpoint renders degraded; others render normally."""
    html = render_operator_overlay_html(
        status_error="status endpoint down",
        health_payload=_HEALTH_PAYLOAD,
        settings_payload=_SETTINGS_PAYLOAD,
        events_payload=_EVENTS_PAYLOAD,
    )

    # Status panel: degraded
    assert 'data-state="degraded"' in html
    assert "status endpoint down" in html

    # Health/settings/events panels: render data normally (no degraded banner from them)
    assert "db" in html  # health check
    assert "watcher.tick" in html  # event


def test_operator_drawer_retry_safe_on_transient_failure() -> None:
    # ST-1 (ui-audit): a transient /operator fetch failure must not pin the
    # error state. `loaded` is set only on success (with an in-flight guard) so
    # reopening retries; the visible message is calm, raw error kept in data-*.
    from companion_ui.workspace.serve_dev_page import render_index_html

    html = render_index_html(
        api_base_url="http://127.0.0.1:18001",
        fields={
            "title": "Op",
            "note_path": "Notes/op.md",
            "artifact_id": "art-1",
            "content_hash": "h",
            "body": "# Op",
            "runtime_environment_label": "dev",
            "runtime_api_base_url_label": "local-dev",
            "guard_writeguard_status": "ok",
            "guard_canvas_enabled": False,
            "guard_degraded": False,
        },
    )
    assert "if (loaded || loading) { return; }" in html
    assert "var loading = false;" in html
    assert "Reopen to retry." in html
    assert 'data-error="' in html
