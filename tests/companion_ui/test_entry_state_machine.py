"""Server-side entry-state resolution (#1783, SEP-01).

The entry point is a small explicit state machine wrapping the existing
orientation/workspace renderer branch in ``serve_dev_page.py``
(`companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md §Entry-point state model`,
`docs/SYSTEM_ENTRY_POINT/ENTRY_STATE_MACHINE.md`):

- exactly five states: ``boot``, ``no_vault``, ``cold_start``, ``orienting``,
  ``shell_active`` — server-resolved, never re-derived client-side;
- ``data-entry-state`` declared on the shell root (``<body>``) in every render
  path; ``data-reentry-shape`` only when ``orienting``; ``degraded`` / ``stale``
  as cross-flag attributes, never separate states;
- ``cold_start`` (first contact and >14d cold trajectories) and ``no_vault``
  render no re-entry overlay of any kind;
- input combinations outside the enumerated transitions resolve to the nearest
  declared state and are surfaced as degraded reasons, never as implicit states.

``boot`` note (task-spec semantics): ``boot`` is "runtime handshake in
progress" — the state declared while the orientation fetch is unresolved, and
the state any client-side ``entry.retry`` returns to. Server-rendered pages
resolve the orientation fetch *before* emitting HTML, so every page rendered
through ``handle_get`` declares a post-boot state; ``boot`` remains a declared
member of the enum (the resolver produces it when no orientation outcome
exists) without any client-side state derivation being introduced.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from companion_ui.workspace.entry_state import (
    ENTRY_STATES,
    REENTRY_SHAPES,
    EntryStateResolution,
    resolve_entry_state,
)
from companion_ui.workspace.serve_dev_page import handle_get, render_index_html
from companion_ui.workspace.workspace_http_client import (
    WorkspaceClientHTTPError,
    WorkspaceClientNetworkError,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_AS_OF = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _leave_point(status: str | None, *, gap: timedelta | None = None) -> dict[str, Any] | None:
    if status is None:
        return None
    leave: dict[str, Any] = {
        "status": status,
        "artifact_ref": {
            "artifact_uuid": "art-resume",
            "logical_ref": "Notes/resume.md",
            "title": "Resume plan",
        },
        "captured_at": _iso(_AS_OF - gap) if gap is not None else None,
        "last_session_id": None,
        "authority_role": "operational_trace_pointer",
        "source_ref": {"kind": "artifact_activation", "trace_id": "trace-leave"},
    }
    return leave


def _orientation_payload(
    *,
    leave_status: str | None = "present",
    gap: timedelta | None = timedelta(hours=5),
    degraded_reasons: list[str] | None = None,
) -> dict[str, Any]:
    reasons = degraded_reasons or []
    return {
        "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": _iso(_AS_OF),
            "trace_id": "trace-orientation-1",
            "freshness": "partial" if reasons else "fresh",
            "stale_after": _iso(_AS_OF + timedelta(minutes=5)),
            "degraded_reasons": reasons,
        },
        "leave_point": _leave_point(leave_status, gap=gap),
        "open_loops": [],
        "notable_changes": [],
        "resurface": {"candidates": []},
        "governance": {
            "pending_proposal_count": 0,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": None,
            "authority_role": "derived",
            "source_ref": {"kind": "runtime_signal", "ref": "gov", "label": "governance"},
        },
        "guards": {
            "read_only": True,
            "runtime_posture": "degraded" if reasons else "healthy",
            "degraded": bool(reasons),
            "reasons": reasons,
            "authority_role": "derived",
            "source_ref": {"kind": "status", "ref": "status", "label": "status"},
        },
        "mutation_intents": [],
    }


def _workspace_fields() -> dict[str, Any]:
    return {
        "title": "Note Title",
        "note_path": "Notes/note.md",
        "artifact_id": "art-123",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-aaa",
        "body": "# Note\n\nBody paragraph.",
        "panel_rail": "Panel / agent rail placeholder",
        "runtime_environment_label": "dev",
        "runtime_api_base_url_label": "local-dev",
        "runtime_trace_id": "trace-1",
        "runtime_vault_name": "vault/dev",
        "runtime_vault_channel": "local-dev",
        "runtime_vault_provenance": "resolved",
        "canvas_session_state": "idle",
        "canvas_session_persistence": "durable",
        "panel_state": "idle",
        "panel_proposal_count": 0,
        "panel_proposals": [],
        "panel_message": "",
        "guard_writeguard_status": "ok",
        "guard_canvas_enabled": True,
        "guard_degraded": False,
        "guard_workspace_update_available": True,
        "guard_update_flow_available": True,
        "find_candidates": [],
        "find_payload_available": False,
        "reorient_sections": {},
        "resurface_candidates": [],
        "governance_receipts": [],
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
        "workspace_loaded_at": None,
    }


def _vault_browser_payload() -> dict[str, Any]:
    return {
        "notes": [
            {
                "note_path": "Notes/resume.md",
                "title": "Resume plan",
                "zone": "Notes",
                "kind": "human_note",
                "frontmatter_valid": True,
                "missing_required_fields": [],
            }
        ],
        "query": "",
        "total_notes": 1,
        "filtered_notes": 1,
        "read_only": True,
        "identity_available": True,
        "vault_identity": {
            "vault_name": "dev-vault",
            "channel": "dev",
            "provenance": "env",
        },
    }


_RUNTIME_503_BODY = json.dumps(
    {
        "error": "runtime_unavailable",
        "message": "The workspace orientation source could not be reached",
        "trace_id": "trace-503",
        "contract_version": "workspace_orientation.v1",
    }
)


class _FakeClient:
    """Read-only fake of WorkspaceHttpClient for handle_get render paths."""

    def __init__(
        self,
        *,
        orientation: dict[str, Any] | None = None,
        orientation_error: Exception | None = None,
        vault_browser: dict[str, Any] | None = None,
        vault_browser_error: Exception | None = None,
    ) -> None:
        self.orientation = orientation
        self.orientation_error = orientation_error
        self.vault_browser = vault_browser or _vault_browser_payload()
        self.vault_browser_error = vault_browser_error

    def get(self, url: str, *, params: dict[str, Any]) -> dict[str, Any]:
        if url == "/api/companion/orientation":
            if self.orientation_error is not None:
                raise self.orientation_error
            assert self.orientation is not None
            return self.orientation
        if url == "/api/companion/vault-browser":
            if self.vault_browser_error is not None:
                raise self.vault_browser_error
            return self.vault_browser
        raise AssertionError(f"unexpected GET: {url}")

    def post(self, url: str, *, json: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError(f"unexpected POST: {url}")

    def delete(self, url: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        raise AssertionError(f"unexpected DELETE: {url}")


def _body_tag(html: str) -> str:
    m = re.search(r"<body[^>]*>", html)
    assert m, "rendered page must have a <body> tag"
    return m.group(0)


def _entry_state(html: str) -> str:
    body = _body_tag(html)
    states = re.findall(r'data-entry-state="([^"]*)"', body)
    assert len(states) == 1, f"shell root must declare exactly one entry state: {body!r}"
    return states[0]


def _reentry_shape(html: str) -> str | None:
    shapes = re.findall(r'data-reentry-shape="([^"]*)"', _body_tag(html))
    assert len(shapes) <= 1
    return shapes[0] if shapes else None


def _render(**kwargs: Any) -> str:
    return render_index_html(api_base_url="http://127.0.0.1:18001", **kwargs)


# ---------------------------------------------------------------------------
# AC: shell root declares data-entry-state in every render path
# ---------------------------------------------------------------------------


def test_shell_root_declares_entry_state_in_all_render_paths() -> None:
    # Orientation page — recoverable trajectory.
    orienting = _render(orientation=_orientation_payload())
    assert _entry_state(orienting) == "orienting"

    # Orientation page — no admissible leave point.
    cold = _render(orientation=_orientation_payload(leave_status="absent"))
    assert _entry_state(cold) == "cold_start"

    # Workspace page — active note anchor.
    shell = _render(note_path="Notes/note.md", fields=_workspace_fields())
    assert _entry_state(shell) == "shell_active"

    # Error page — runtime unreachable while loading a note.
    unreachable = _render(note_path="Notes/note.md", error="connection refused")
    assert _entry_state(unreachable) == "no_vault"

    # Error page — non-runtime failure (note not found) still declares a state.
    not_found = _render(
        note_path="Notes/missing.md",
        error='HTTP 404: {"detail": {"error": "note_not_found", "note_path": "Notes/missing.md"}}',
    )
    assert _entry_state(not_found) in ENTRY_STATES

    # Server-rendered through handle_get: orientation 503 → no_vault.
    html = handle_get(
        query_string="",
        client=_FakeClient(orientation_error=WorkspaceClientHTTPError(503, _RUNTIME_503_BODY)),  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )
    assert _entry_state(html) == "no_vault"

    # Every declared value is inside the five-state enum.
    for page in (orienting, cold, shell, unreachable, not_found, html):
        assert _entry_state(page) in ENTRY_STATES


def test_boot_is_client_transient_pre_resolution_state() -> None:
    """`boot` = handshake in progress (task-spec semantics).

    Server-rendered pages resolve the orientation fetch before HTML is
    emitted, so `handle_get` output never declares `boot`; the resolver
    declares it only while no orientation outcome exists (the state a
    client-side `entry.retry` returns to). No client logic re-derives it.
    """
    assert resolve_entry_state().state == "boot"

    rendered_paths = [
        handle_get(
            query_string="",
            client=_FakeClient(orientation=_orientation_payload()),  # type: ignore[arg-type]
            api_base_url="http://127.0.0.1:18001",
        ),
        handle_get(
            query_string="",
            client=_FakeClient(orientation_error=WorkspaceClientHTTPError(503, _RUNTIME_503_BODY)),  # type: ignore[arg-type]
            api_base_url="http://127.0.0.1:18001",
        ),
    ]
    for page in rendered_paths:
        assert _entry_state(page) != "boot"


# ---------------------------------------------------------------------------
# AC: leave_point.status absent / >14d cold → cold_start, no re-entry overlay
# ---------------------------------------------------------------------------


def test_cold_start_shows_no_reentry_overlay() -> None:
    # First contact: status "absent".
    absent = _render(orientation=_orientation_payload(leave_status="absent"))
    # No leave point at all (null) is the same first-contact posture.
    null_leave = _render(orientation=_orientation_payload(leave_status=None))
    # Cold trajectory: leave point present but the gap exceeds 14 days.
    cold_gap = _render(
        orientation=_orientation_payload(leave_status="present", gap=timedelta(days=20))
    )

    for page in (absent, null_leave, cold_gap):
        assert _entry_state(page) == "cold_start"
        # No re-entry overlay of any kind: no shape, no re-entry card region.
        assert _reentry_shape(page) is None
        assert 'data-region="reentry-card"' not in page
        assert "data-traj-state" not in page


# ---------------------------------------------------------------------------
# AC: cold_start suppresses all dashboard/orientation sections (#2225)
# ---------------------------------------------------------------------------

_COLD_DASHBOARD_MARKERS = (
    # Anti-dashboard posture: these sections must not appear on cold_start.
    # SYSTEM_ENTRY_POINT_SPEC.md §Anti-dashboard; REENTRY_ORIENTATION_TREATMENT.md §Cold.
    'data-testid="workspace-orientation-leave-point"',
    'data-testid="workspace-orientation-open-loops"',
    'data-testid="workspace-orientation-notable-changes"',
    'data-testid="workspace-orientation-governance"',
    'data-testid="workspace-orientation-resurface"',
    "Re-entry snapshot",
)


def test_cold_start_shows_no_dashboard_sections() -> None:
    pages = [
        _render(orientation=_orientation_payload(leave_status="absent")),
        _render(orientation=_orientation_payload(leave_status=None)),
        _render(orientation=_orientation_payload(leave_status="present", gap=timedelta(days=20))),
    ]
    for page in pages:
        assert _entry_state(page) == "cold_start"
        for marker in _COLD_DASHBOARD_MARKERS:
            assert marker not in page, f"cold_start must not render: {marker!r}"


def test_cold_start_shows_vault_and_map_affordances() -> None:
    page = _render(orientation=_orientation_payload(leave_status="absent"))
    assert _entry_state(page) == "cold_start"
    assert 'data-intent="map.open"' in page
    assert 'data-testid="workspace-orientation-ambient-refresh"' in page


def test_orienting_still_renders_dashboard_sections() -> None:
    page = _render(
        orientation=_orientation_payload(leave_status="present", gap=timedelta(hours=5))
    )
    assert _entry_state(page) == "orienting"
    assert 'data-testid="workspace-orientation-leave-point"' in page
    assert 'data-testid="workspace-orientation-governance"' in page
    assert "Re-entry snapshot" in page


# ---------------------------------------------------------------------------
# AC: orientation HTTP 503 → no_vault, retry affordance, nothing fabricated
# ---------------------------------------------------------------------------


def test_runtime_unavailable_resolves_to_no_vault() -> None:
    # 503 runtime_unavailable with the vault browser still reachable.
    html = handle_get(
        query_string="",
        client=_FakeClient(orientation_error=WorkspaceClientHTTPError(503, _RUNTIME_503_BODY)),  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )
    assert _entry_state(html) == "no_vault"
    # Retry affordance carries the declared intent.
    assert 'data-intent="entry.retry"' in html
    # No fabricated snapshot content: no re-entry overlay/shape, no leave-point
    # continuity claim, no trajectory classification.
    assert _reentry_shape(html) is None
    assert 'data-region="reentry-card"' not in html
    assert 'data-leave-point-kind="present"' not in html
    assert "data-traj-state" not in html

    # 503 with the vault browser also down: the error page is still no_vault
    # and still offers retry.
    both_down = handle_get(
        query_string="",
        client=_FakeClient(
            orientation_error=WorkspaceClientHTTPError(503, _RUNTIME_503_BODY),
            vault_browser_error=WorkspaceClientNetworkError("connection refused"),
        ),  # type: ignore[arg-type]
        api_base_url="http://127.0.0.1:18001",
    )
    assert _entry_state(both_down) == "no_vault"
    assert 'data-intent="entry.retry"' in both_down
    assert _reentry_shape(both_down) is None


# ---------------------------------------------------------------------------
# AC: orienting carries data-reentry-shape; degraded/stale are cross-flags
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gap", "shape"),
    [
        (timedelta(seconds=30), "no_mist"),
        (timedelta(minutes=5), "thread_fade"),
        (timedelta(hours=1), "soft_mist"),
        (timedelta(days=1), "full_mist"),
        (timedelta(days=7), "long_mist"),
    ],
)
def test_orienting_carries_shape_and_cross_flags(gap: timedelta, shape: str) -> None:
    # Latency-ladder shape derivation (CONTINUITY_AND_DECAY.md ladder).
    html = _render(orientation=_orientation_payload(gap=gap))
    assert _entry_state(html) == "orienting"
    assert _reentry_shape(html) == shape
    assert shape in REENTRY_SHAPES

    # degraded renders as a cross-flag attribute on the same orienting state,
    # never as a separate state.
    degraded = _render(
        orientation=_orientation_payload(
            gap=gap, degraded_reasons=["resurfacing_source_unavailable"]
        )
    )
    assert _entry_state(degraded) == "orienting"
    assert 'data-degraded="true"' in _body_tag(degraded)
    assert 'data-stale="true"' not in _body_tag(degraded)

    # stale leave point renders as a cross-flag, still orienting.
    stale = _render(orientation=_orientation_payload(leave_status="stale", gap=gap))
    assert _entry_state(stale) == "orienting"
    assert 'data-stale="true"' in _body_tag(stale)

    # The healthy render carries neither cross-flag.
    assert 'data-degraded="true"' not in _body_tag(html)
    assert 'data-stale="true"' not in _body_tag(html)


def test_stale_variants_are_cross_flags_not_states() -> None:
    for status in ("stale", "artifact_missing", "degraded"):
        html = _render(orientation=_orientation_payload(leave_status=status))
        assert _entry_state(html) == "orienting", status
        assert 'data-stale="true"' in _body_tag(html), status


# ---------------------------------------------------------------------------
# AC: undeclared transitions are rejected
# ---------------------------------------------------------------------------


def test_undeclared_transitions_are_rejected() -> None:
    # The resolution type cannot represent a state outside the declared enum.
    with pytest.raises(ValueError):
        EntryStateResolution(state="mist_walk")
    # A re-entry shape outside the declared ladder is rejected.
    with pytest.raises(ValueError):
        EntryStateResolution(state="orienting", reentry_shape="dense_fog")
    # Shapes only decorate orienting; cold_start/no_vault carry no overlay.
    with pytest.raises(ValueError):
        EntryStateResolution(state="cold_start", reentry_shape="full_mist")
    # Cross-flags may decorate only orienting and shell_active (spec).
    with pytest.raises(ValueError):
        EntryStateResolution(state="no_vault", degraded=True)
    with pytest.raises(ValueError):
        EntryStateResolution(state="boot", stale=True)

    # Out-of-contract inputs resolve to the nearest declared state and are
    # surfaced as degraded reasons — never as a new implicit state.
    undeclared_status = resolve_entry_state(
        orientation=_orientation_payload(leave_status="warping")
    )
    assert undeclared_status.state == "orienting"
    assert "entry_state_leave_point_status_undeclared" in undeclared_status.degraded_reasons

    gapless = _orientation_payload()
    gapless["meta"]["as_of"] = ""
    gap_unknown = resolve_entry_state(orientation=gapless)
    assert gap_unknown.state == "orienting"
    assert gap_unknown.reentry_shape == "full_mist"  # canonical re-entry fallback
    assert "entry_state_reentry_gap_unknown" in gap_unknown.degraded_reasons

    note_load_failed = resolve_entry_state(
        note_path="Notes/missing.md",
        error='HTTP 404: {"detail": {"error": "note_not_found"}}',
    )
    assert note_load_failed.state in ENTRY_STATES
    assert "entry_state_note_load_failed" in note_load_failed.degraded_reasons

    # Adversarial sweep: every input combination resolves inside the enum.
    sweep = [
        resolve_entry_state(),
        resolve_entry_state(error="???"),
        resolve_entry_state(note_path="Notes/x.md", error="HTTP 500: boom"),
        resolve_entry_state(orientation={}),
        resolve_entry_state(orientation={"leave_point": "not-a-dict"}),
        resolve_entry_state(orientation={"leave_point": {"status": 42}}),
        resolve_entry_state(orientation=_orientation_payload(), orientation_error="HTTP 503"),
        resolve_entry_state(note_path="Notes/x.md", note_loaded=True),
    ]
    for resolution in sweep:
        assert resolution.state in ENTRY_STATES
        assert resolution.reentry_shape is None or resolution.reentry_shape in REENTRY_SHAPES


def test_rendered_entry_states_never_leave_the_enum() -> None:
    pages = [
        _render(orientation=_orientation_payload()),
        _render(orientation=_orientation_payload(leave_status="warping")),
        _render(orientation=_orientation_payload(leave_status="absent")),
        _render(note_path="Notes/note.md", fields=_workspace_fields()),
        _render(note_path="Notes/note.md", error="timed out"),
        _render(error="HTTP 500: boom"),
    ]
    for page in pages:
        assert _entry_state(page) in ENTRY_STATES
