"""Operator health glyph (ambient) — OBSSTAB-08, #2615.

Level-0 ambient health indicator: a single calm glyph present in every entry
state (cold_start / no-vault / orienting) without a note open.

Design contract: docs/OBSERVABILITY_STABILIZATION/HEALTH_ERGONOMICS.md and
OPERATOR_HEALTH_GLYPH_AMBIENT.md.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from companion_ui.workspace.serve_dev_page import (
    _derive_health_glyph_state,
    _render_ambient_health_glyph,
    handle_get,
    render_index_html,
)
from companion_ui.workspace.workspace_http_client import WorkspaceClientError

# ---------------------------------------------------------------------------
# Helpers — orientation / health fixture builders
# ---------------------------------------------------------------------------

_NOW = datetime.now(tz=timezone.utc)
_AS_OF = _NOW - timedelta(minutes=3)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _orientation_payload(
    *,
    leave_status: str | None = "absent",
) -> dict[str, Any]:
    leave_point: dict[str, Any] | None = None
    if leave_status is not None:
        leave_point = {
            "status": leave_status,
            "captured_at": _iso(_AS_OF - timedelta(days=20)),
        }
    return {
        "scope": {"kind": "workspace", "vault_id": "test-vault", "channel": "test"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": _iso(_AS_OF),
            "trace_id": "trace-test-1",
            "freshness": "fresh",
            "stale_after": _iso(_AS_OF + timedelta(minutes=5)),
            "degraded_reasons": [],
        },
        "leave_point": leave_point,
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


def _health_ok() -> dict[str, Any]:
    """A healthy /api/health response."""
    return {
        "required_ok": True,
        "ok": True,
        "checks": {},
        "authority_spine": {"write_guard": "active"},
        "runtime": {
            "worker": {"status": "ok"},
        },
        "suggested_actions": [],
    }


def _health_write_blocked() -> dict[str, Any]:
    """Health response with write_guard blocked."""
    h = _health_ok()
    h["authority_spine"]["write_guard"] = "blocked"
    return h


def _health_worker_stall() -> dict[str, Any]:
    """Health response with worker stale heartbeat."""
    h = _health_ok()
    h["runtime"]["worker"] = {"status": "stale"}
    return h


def _health_worker_missing() -> dict[str, Any]:
    """Health response with worker missing."""
    h = _health_ok()
    h["runtime"]["worker"] = None
    return h


def _render_entry(
    *,
    health: dict[str, Any] | None = None,
    leave_status: str | None = "absent",
) -> str:
    """Render an orientation entry state (cold_start / no-vault) with optional health payload."""
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        orientation=_orientation_payload(leave_status=leave_status),
        health=health,
    )


def _render_cold_start(health: dict[str, Any] | None = None) -> str:
    return _render_entry(health=health, leave_status="absent")


def _render_orienting(health: dict[str, Any] | None = None) -> str:
    """Render orienting state (short-gap return)."""
    return _render_entry(health=health, leave_status="present")


def _render_no_vault(health: dict[str, Any] | None = None) -> str:
    """Render no-vault error page (no orientation payload)."""
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        error="connection refused",
        health=health,
    )


# ---------------------------------------------------------------------------
# AC1: glyph is present in every entry state (cold_start / no-vault / orienting)
# ---------------------------------------------------------------------------


def test_glyph_present_in_entry_states() -> None:
    """The health glyph renders in cold_start, no-vault, and orienting without a note open."""
    health = _health_ok()

    cold = _render_cold_start(health=health)
    assert 'data-testid="operator-health-glyph"' in cold, (
        "glyph must render in cold_start state"
    )

    orienting = _render_orienting(health=health)
    assert 'data-testid="operator-health-glyph"' in orienting, (
        "glyph must render in orienting state"
    )


def test_glyph_renders_without_fields() -> None:
    """Glyph renders when fields is None (no note open), including with None health (endpoint unreachable)."""
    # With no health payload at all (endpoint unreachable → Nere state)
    cold_no_health = _render_cold_start(health=None)
    assert 'data-testid="operator-health-glyph"' in cold_no_health, (
        "glyph must render even when health endpoint unreachable (Nere state)"
    )

    # With healthy payload
    cold_healthy = _render_cold_start(health=_health_ok())
    assert 'data-testid="operator-health-glyph"' in cold_healthy, (
        "glyph must render when health is ok"
    )


# ---------------------------------------------------------------------------
# AC2: write-blocked glyph state
# ---------------------------------------------------------------------------


def test_glyph_shows_write_blocked() -> None:
    """write_guard == 'blocked' → Pausad state with blocked indicator in glyph."""
    state, reason = _derive_health_glyph_state(_health_write_blocked())
    assert state == "pausad", f"expected pausad, got {state!r}"
    assert reason, "blocked state must carry a non-empty reason"
    # Reason must be plain Swedish, no raw field names
    assert "write_guard" not in reason.lower(), (
        "raw field name must not appear in glyph reason"
    )

    # Integration: glyph HTML carries the correct data-health-state
    html = _render_ambient_health_glyph(_health_write_blocked())
    assert 'data-health-state="pausad"' in html, (
        "glyph HTML must declare data-health-state=pausad for blocked write_guard"
    )
    assert 'data-testid="operator-health-glyph"' in html


def test_glyph_shows_write_blocked_in_render() -> None:
    """Full render with write-blocked health shows pausad glyph."""
    html = _render_cold_start(health=_health_write_blocked())
    assert 'data-health-state="pausad"' in html
    # Reason text must appear (plain language, not a raw field name)
    assert 'data-testid="operator-health-glyph-reason"' in html
    reason_match = re.search(
        r'data-testid="operator-health-glyph-reason"[^>]*>([^<]+)<', html
    )
    assert reason_match, "reason element must be present and non-empty"
    reason_text = reason_match.group(1)
    assert "write_guard" not in reason_text.lower(), (
        "raw JSON field name must not reach human"
    )


# ---------------------------------------------------------------------------
# AC3: worker-stall glyph state
# ---------------------------------------------------------------------------


def test_glyph_shows_worker_stall() -> None:
    """health.runtime.worker stale/missing → Uppmärksamhet state."""
    # Stale worker
    state_stale, reason_stale = _derive_health_glyph_state(_health_worker_stall())
    assert state_stale == "uppmärksamhet", (
        f"stale worker → uppmärksamhet, got {state_stale!r}"
    )
    assert reason_stale, "worker stall must carry a non-empty reason"

    # Missing worker
    state_missing, reason_missing = _derive_health_glyph_state(_health_worker_missing())
    assert state_missing == "uppmärksamhet", (
        f"missing worker → uppmärksamhet, got {state_missing!r}"
    )

    # No raw field names in either reason
    for r in (reason_stale, reason_missing):
        assert "runtime" not in r.lower() or "worker" not in r.lower() or "status" not in r.lower(), (
            f"raw field names must not appear in glyph reason: {r!r}"
        )


def test_glyph_shows_worker_stall_in_render() -> None:
    """Full render with stale worker shows uppmärksamhet glyph."""
    html = _render_cold_start(health=_health_worker_stall())
    assert 'data-health-state="uppmärksamhet"' in html, (
        "stale worker must render uppmärksamhet state in cold_start"
    )


# ---------------------------------------------------------------------------
# AC4: clicking/expanding routes to operator drawer
# ---------------------------------------------------------------------------


def test_glyph_drills_into_operator_drawer() -> None:
    """Expanding / clicking the glyph routes to the operator drawer."""
    html = _render_cold_start(health=_health_ok())

    # The glyph's opening tag must carry data-intent="operator.open" and an
    # onclick that mounts the operator overlay.
    glyph_tag = _glyph_open_tag(html)
    assert 'data-intent="operator.open"' in glyph_tag, (
        "glyph must carry data-intent=operator.open to route to the operator drawer"
    )
    assert "overlayHost.mount('operator')" in glyph_tag, (
        "glyph onclick must mount the operator overlay"
    )


# ---------------------------------------------------------------------------
# P1 (#2615 Codex): the REAL handle_get serving path must fetch /api/health
# and pass it through — direct injection alone would not catch a missing fetch.
# ---------------------------------------------------------------------------


class _EntryStateClient:
    """Stub WorkspaceHttpClient for the entry-state handle_get path.

    Returns a cold_start orientation + an injectable /api/health payload
    (or raises WorkspaceClientError when ``health_raises`` is set, to model a
    genuine fetch failure/timeout).
    """

    def __init__(
        self,
        *,
        health_payload: dict[str, Any] | None,
        health_raises: bool = False,
    ) -> None:
        self._health_payload = health_payload
        self._health_raises = health_raises
        self.get_calls: list[str] = []

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        self.get_calls.append(url)
        if url == "/api/health":
            if self._health_raises:
                raise WorkspaceClientError("health endpoint unreachable")
            return self._health_payload or {}
        if url == "/api/companion/orientation":
            return _orientation_payload(leave_status="absent")
        if url == "/api/companion/vault-browser":
            return {
                "identity": {"vault_id": "test-vault", "channel": "test"},
                "notes": {"items": []},
                "pagination": {},
            }
        return {}

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        return {}


def test_handle_get_fetches_health_and_renders_green_when_healthy() -> None:
    """The served entry page (real handle_get path) shows Frisk when runtime is healthy.

    Regression guard for the Codex P1 finding: handle_get previously did not
    fetch /api/health, so a healthy runtime rendered "Nere" on the real page.
    """
    client = _EntryStateClient(health_payload=_health_ok())
    html = handle_get(
        query_string="",
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )
    # handle_get must actually fetch /api/health on the entry-state path.
    assert "/api/health" in client.get_calls, (
        "handle_get must fetch /api/health on the entry-state path"
    )
    # A healthy runtime must yield the green Frisk glyph — NOT Nere.
    glyph_tag = _glyph_open_tag(html)
    assert 'data-health-state="frisk"' in glyph_tag, (
        "served entry page must show Frisk (green) for a healthy runtime, not Nere"
    )
    assert 'data-health-state="nere"' not in glyph_tag


def test_handle_get_health_fetch_failure_renders_nere() -> None:
    """When the health fetch genuinely fails, the served page shows Nere (honest)."""
    client = _EntryStateClient(health_payload=None, health_raises=True)
    html = handle_get(
        query_string="",
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )
    assert "/api/health" in client.get_calls
    glyph_tag = _glyph_open_tag(html)
    assert 'data-health-state="nere"' in glyph_tag, (
        "a failed/timed-out health fetch must render Nere (runtime unreachable)"
    )


def test_handle_get_renders_write_blocked_on_served_page() -> None:
    """write_guard blocked on the served entry page → Pausad glyph (via handle_get)."""
    client = _EntryStateClient(health_payload=_health_write_blocked())
    html = handle_get(
        query_string="",
        client=client,  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )
    glyph_tag = _glyph_open_tag(html)
    assert 'data-health-state="pausad"' in glyph_tag


# ---------------------------------------------------------------------------
# P2 (#2615 Codex): the glyph must not be a <button> nested in another <button>.
# ---------------------------------------------------------------------------


def test_glyph_is_not_nested_button() -> None:
    """The glyph element is not a <button> nested inside the operator node button.

    Nested <button> is invalid HTML; browsers reparent/auto-close it, breaking
    the node DOM and the glyph's own click target (AC4 drill-in).
    """
    # Rendered alone, the glyph itself must not be a <button>.
    glyph_html = _render_ambient_health_glyph(_health_ok())
    assert "<button" not in glyph_html, (
        "the glyph must not be a <button> (it nests inside the operator node button)"
    )
    assert 'role="button"' in glyph_html, (
        "the glyph should be a focusable element with role=button"
    )

    # In a full render, the operator node carries the glyph but contains no
    # nested <button> (i.e. no `<button ...> ... <button` pattern).
    html = _render_cold_start(health=_health_ok())
    node_html = _operator_node_html(html)
    assert 'data-testid="operator-health-glyph"' in node_html, (
        "the operator node should host the health glyph"
    )
    # The node opens with a <button> tag; assert there is no SECOND <button>
    # opening tag anywhere inside it.
    inner = node_html[node_html.index(">") + 1 :]
    assert "<button" not in inner, (
        "operator node must not contain a nested <button> (invalid HTML)"
    )


# ---------------------------------------------------------------------------
# HEALTH_ERGONOMICS.md additional constraints
# ---------------------------------------------------------------------------


def test_glyph_uses_colour_glyph_and_word() -> None:
    """The glyph carries colour + glyph char + word — never colour alone."""
    for health_fn in (_health_ok, _health_write_blocked, _health_worker_stall):
        html = _render_ambient_health_glyph(health_fn())
        assert 'data-testid="operator-health-glyph-dot"' in html, (
            f"glyph char must render for {health_fn.__name__}"
        )
        assert 'data-testid="operator-health-glyph-word"' in html, (
            f"word must render for {health_fn.__name__}"
        )


def test_glyph_frisk_state() -> None:
    """A fully healthy runtime renders Frisk state (no reason text)."""
    state, reason = _derive_health_glyph_state(_health_ok())
    assert state == "frisk", f"healthy runtime → frisk, got {state!r}"
    assert reason == "", "Frisk state must carry no reason text"

    html = _render_ambient_health_glyph(_health_ok())
    assert 'data-health-state="frisk"' in html
    # No reason element when healthy
    assert 'data-testid="operator-health-glyph-reason"' not in html


def test_glyph_nere_when_unreachable() -> None:
    """health endpoint unreachable (None) → Nere state."""
    state, reason = _derive_health_glyph_state(None)
    assert state == "nere"
    assert reason, "Nere state must carry a non-empty reason"

    html = _render_ambient_health_glyph(None)
    assert 'data-health-state="nere"' in html


def test_worst_state_precedence() -> None:
    """write-blocked write_guard with otherwise-ok required_ok → Pausad (not Frisk)."""
    health = _health_ok()
    health["authority_spine"]["write_guard"] = "blocked"
    state, _ = _derive_health_glyph_state(health)
    assert state == "pausad", (
        "write-blocked write_guard must produce Pausad regardless of required_ok"
    )


def test_no_raw_field_names_in_glyph() -> None:
    """No raw JSON field names, status codes, or tracebacks reach the human via the glyph."""
    forbidden = ("write_guard", "authority_spine", "required_ok", "runtime.worker", "traceback")
    for health_fn in (_health_ok, _health_write_blocked, _health_worker_stall):
        _, reason = _derive_health_glyph_state(health_fn())
        for token in forbidden:
            assert token not in reason.lower(), (
                f"raw token {token!r} must not appear in glyph reason from {health_fn.__name__}"
            )


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _glyph_open_tag(html: str) -> str:
    """The glyph's opening element tag (carries the intent/onclick attributes).

    The glyph is a ``<span role="button">`` (not a ``<button>``) so it stays
    valid HTML when nested inside the operator map node's own ``<button>``.
    """
    m = re.search(
        r'<span[^>]*data-testid="operator-health-glyph"[^>]*>',
        html,
    )
    assert m, "operator-health-glyph span must be present in HTML"
    return m.group(0)


def _operator_node_html(html: str) -> str:
    """The full operator map node element (button or article) from a page.

    Used to assert the glyph is not nested inside another ``<button>``.
    """
    m = re.search(
        r'<(?P<tag>button|article)[^>]*data-surface-id="operator"[^>]*>.*?</(?P=tag)>',
        html,
        re.S,
    )
    assert m, "operator map node must render"
    return m.group(0)
