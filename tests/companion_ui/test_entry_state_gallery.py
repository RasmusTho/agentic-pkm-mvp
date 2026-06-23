"""State-gallery validation harness (#1795, SEP-11) — composition proof.

Renders every state the spec's gallery declares from fixture orientation
snapshots and asserts every invariant the spec's Validation-expectations
section names (`companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md §Validation
expectations`, `docs/SYSTEM_ENTRY_POINT/STATE_GALLERY_VALIDATION.md`):

- every declared entry-point transition renders; undeclared transitions are
  rejected across the fixture matrix;
- no UI-derived posture / class / authority anywhere — all classification
  server-declared (traceable to fixture-declared fields);
- ``cold_start`` (first contact and >14d) and ``no_vault`` render no re-entry
  overlay of any kind;
- governed intents route through the pipeline and surface receipts; body
  edits and non-terminal ``memory.defer`` produce no governance receipt
  (the receipt asymmetry is asserted, not assumed);
- blocked and stale present as guard-held states, never generic errors;
- the display budget caps visible items at or below the server caps with the
  §Resolved Q5 default scarce subset;
- reduced motion: every end-state is fully visible without animation
  (server-rendered static markup; the only animation declares a
  ``prefers-reduced-motion`` override);
- narrow/portrait preserves every critical affordance (rail → bottom sheet;
  whisper column suppressed).

Gallery source: `companion-ui/design_handoff/2026-06-09-system-entry-point/
state-gallery.md` (entry states A1–A7, shell states B1–B12, responsive C1,
guidance E, and the shipped settings/read-back/capture/receipts F-states).
The fixture set is owned by this harness (the spec delegates it here).

Each child slice proves its own surface in its own test module; this harness
proves the composition as a whole and is the regression net that keeps later
UI work from silently violating the entry/overlay grammar.
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from companion_ui.workspace.entry_state import (
    ENTRY_STATES,
    REENTRY_SHAPES,
    EntryStateResolution,
    resolve_entry_state,
)
from companion_ui.workspace.memory_review_drawer import (
    GOVERNED_REVIEW_ACTIONS,
    NON_TERMINAL_REVIEW_ACTIONS,
    REVIEW_ACTIONS,
    memory_review_queue_fragment,
)
from companion_ui.workspace.overlay_host import (
    DECLARED_OVERLAYS,
    DEFAULT_POSTURE_EMPHASIS,
    KEYBOARD_MAP,
    POSTURE_EMPHASES,
    SHIPPED_OVERLAY_OCCUPANTS,
    SHIPPED_TOPBAR_SURFACES,
    OverlayHostState,
    apply_intent,
    dismiss,
    mount,
)
from companion_ui.workspace.serve_dev_page import handle_get, render_index_html
from companion_ui.workspace.workspace_http_client import (
    WorkspaceClientHTTPError,
    WorkspaceClientNetworkError,
)

# ---------------------------------------------------------------------------
# Fixture orientation snapshots (extend the proven fixtures in
# test_entry_state_machine.py / test_reentry_orientation_treatment.py /
# test_overlay_host.py — this harness owns the gallery fixture set)
# ---------------------------------------------------------------------------

_AS_OF = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)

# Latency-ladder gaps (CONTINUITY_AND_DECAY.md).
_GAP_NO_MIST = timedelta(seconds=30)
_GAP_THREAD_FADE = timedelta(minutes=5)
_GAP_SOFT_MIST = timedelta(hours=1)
_GAP_FULL_MIST = timedelta(days=1)
_GAP_LONG_MIST = timedelta(days=7)
_GAP_COLD = timedelta(days=21)

# Server caps per WORKSPACE_ORIENTATION_CONTRACT.md §Bounded Collections.
_SERVER_CAPS = {"open_loops": 8, "notable_changes": 8, "resurface_candidates": 5}
_DEFAULT_VISIBLE = 3  # §Resolved Q5 items_per_orientation_moment


def _iso(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _source_ref(label: str = "orientation signals") -> dict[str, str]:
    return {"kind": "runtime_signal", "ref": "orientation.signals", "label": label}


def _artifact_ref(
    note_path: str = "Notes/resume.md",
    title: str = "Resume plan",
    artifact_id: str = "art-resume",
) -> dict[str, str]:
    return {"artifact_id": artifact_id, "note_path": note_path, "title": title}


def _open_loop(idx: int) -> dict[str, Any]:
    return {
        "id": f"loop-{idx}",
        "label": f"Open loop label {idx}",
        "status": "open",
        "handoff_hint": "panel",
        "artifact_ref": _artifact_ref(f"Notes/loop-{idx}.md", f"Loop {idx}", f"art-loop-{idx}"),
        "authority_role": "derived",
        "source_ref": _source_ref(f"open loop {idx}"),
    }


def _notable_change(idx: int) -> dict[str, Any]:
    return {
        "id": f"change-{idx}",
        "label": f"Notable change label {idx}",
        "summary": f"Bounded delta summary {idx}.",
        "changed_at": _iso(_AS_OF - timedelta(hours=idx + 1)),
        "artifact_ref": _artifact_ref(
            f"Notes/change-{idx}.md", f"Change {idx}", f"art-change-{idx}"
        ),
        "authority_role": "derived",
        "source_ref": _source_ref(f"notable change {idx}"),
    }


def _resurface_candidate(idx: int) -> dict[str, Any]:
    return {
        "id": f"candidate-{idx}",
        "label": f"Resurface candidate {idx}",
        "why_now": f"Relevant now because signal {idx} changed.",
        "signal_labels": [f"signal={idx}"],
        "artifact_ref": _artifact_ref(f"Notes/res-{idx}.md", f"Candidate {idx}", f"art-res-{idx}"),
        "authority_role": "derived",
        "source_ref": _source_ref(f"resurfacing signal {idx}"),
    }


def _orientation_payload(
    *,
    leave_status: str | None = "present",
    gap: timedelta | None = _GAP_FULL_MIST,
    trajectory_state: str | None = None,
    degraded_reasons: list[str] | None = None,
    governance_authority_role: str = "derived",
    open_loops: int = 3,
    notable_changes: int = 2,
    resurface_candidates: int = 1,
    staged_proposals: int = 1,
) -> dict[str, Any]:
    """One fixture orientation snapshot in the contract's verbatim shape."""
    reasons = degraded_reasons or []
    leave_point: dict[str, Any] | None = None
    if leave_status is not None:
        leave_point = {
            "status": leave_status,
            "artifact_ref": _artifact_ref(),
            "label": "Resume the runtime API contract",
            "captured_at": _iso(_AS_OF - gap) if gap is not None else None,
            "last_session_id": "session-123",
            "authority_role": "operational_trace_pointer",
            "source_ref": {"kind": "artifact_activation", "trace_id": "trace-leave"},
        }
        if trajectory_state is not None:
            leave_point["trajectory_state"] = trajectory_state
    return {
        "scope": {"kind": "workspace", "vault_id": "dev-vault", "channel": "dev"},
        "meta": {
            "contract_version": "workspace_orientation.v1",
            "as_of": _iso(_AS_OF),
            "trace_id": "trace-orientation-1",
            "freshness": "partial" if reasons else "fresh",
            "stale_after": _iso(_AS_OF + timedelta(minutes=5)),
            "degraded_reasons": reasons,
            "caps": {
                "open_loops": _SERVER_CAPS["open_loops"],
                "notable_changes": _SERVER_CAPS["notable_changes"],
                "resurface_candidates": _SERVER_CAPS["resurface_candidates"],
                "mutation_intents": 0,
                "source_refs_per_item": 3,
            },
        },
        "leave_point": leave_point,
        "open_loops": [_open_loop(idx) for idx in range(open_loops)],
        "notable_changes": [_notable_change(idx) for idx in range(notable_changes)],
        "resurface": {
            "candidates": [_resurface_candidate(idx) for idx in range(resurface_candidates)]
        },
        "governance": {
            "pending_proposal_count": staged_proposals,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": "logged",
            "authority_role": governance_authority_role,
            "source_ref": _source_ref("governance summary"),
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


def _panel_proposal(
    proposal_id: str,
    *,
    description: str,
    status: str = "staged",
) -> dict[str, Any]:
    return {
        "proposal_id": proposal_id,
        "artifact_id": "art-123",
        "description": description,
        "evidence": {
            "trigger_summary": f"Trigger for {proposal_id}",
            "action_class": "lifecycle.move",
            "cognition_route": "rule",
        },
        "status": status,
        "proposal_origin": None,
        "reflected_receipt": None,
        "affordances": {"confirm": True, "correct": True, "reject": True},
    }


def _governance_receipt(idx: int = 1, *, status: str = "applied") -> dict[str, Any]:
    """One runtime-produced receipt projection row (the UI invents none)."""
    return {
        "data_testid": "receipt-pill",
        "data_receipt_id": f"receipt-{idx}",
        "data_suggestion_id": f"sugg-{idx}",
        "data_artifact_id": "art-123",
        "data_status": status,
        "data_intent": "governance.openReceipt",
        "aria_label": f"Receipt {idx}: {status}",
        "label": f"{status} · receipt-{idx}",
        "display_timestamp": "2026-06-10T11:00:00Z",
    }


def _workspace_fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
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
    base.update(overrides)
    return base


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
        "vault_identity": {"vault_name": "dev-vault", "channel": "dev", "provenance": "env"},
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


def _render(**kwargs: Any) -> str:
    return render_index_html(api_base_url="http://127.0.0.1:18001", **kwargs)


def _render_orientation(orientation: dict[str, Any]) -> str:
    """Render the entry substrate from one fixture orientation snapshot."""
    return _render(
        orientation=orientation,
        orientation_vault_browser=_vault_browser_payload(),
    )


def _render_workspace(**overrides: Any) -> str:
    fields = _workspace_fields(**overrides)
    return _render(note_path=str(fields["note_path"]), fields=fields)


def _render_no_vault(*, vault_browser_down: bool = False) -> str:
    return handle_get(
        query_string="",
        client=_FakeClient(  # type: ignore[arg-type]
            orientation_error=WorkspaceClientHTTPError(503, _RUNTIME_503_BODY),
            vault_browser_error=(
                WorkspaceClientNetworkError("connection refused") if vault_browser_down else None
            ),
        ),
        api_base_url="http://127.0.0.1:18001",
    )


# ---------------------------------------------------------------------------
# The state gallery — every state from the handoff package's state-gallery.md
# that shipped, rendered from a fixture orientation snapshot
# ---------------------------------------------------------------------------

# Markers that constitute "a re-entry overlay of any kind" (SEP-02 set).
_REENTRY_OVERLAY_MARKERS = (
    'data-region="reentry-card"',
    'data-region="delta-strip"',
    'data-region="whisper-column"',
    'data-region="reentry-peripheral-line"',
    "data-traj-state",
    "data-rail-fade",
    'data-testid="reentry-caret-echo"',
)

# Shipped overlay-host occupant → its rendered region marker on the shell.
_OCCUPANT_MARKERS: dict[str, str] = {
    "vault": 'data-testid="vault-browser-overlay"',
    "cmd": 'data-region="panel-palette"',
    "capture": 'data-testid="capture-modal"',
    "memory": 'data-region="memory-review-drawer"',
    "receipts": 'data-testid="receipts-history-modal"',
    "settings": 'data-region="settings-drawer"',
    "map": 'data-region="system-map-overlay"',
}

_OCCUPANT_REGISTRATION_MARKERS: dict[str, str] = {
    occupant: f"window.overlayHost.register('{occupant}'"
    for occupant in SHIPPED_OVERLAY_OCCUPANTS
}

_OCCUPANT_OPEN_INTENTS: dict[str, str] = {
    "vault": "vault.open",
    "cmd": "cmd.open",
    "capture": "capture.open",
    "memory": "memory.open",
    "receipts": "receipts.open",
    "settings": "settings.open",
    "map": "map.open",
}


@dataclass(frozen=True)
class OpenOverlayFixture:
    """Pure open-state proof for one shipped overlay-host occupant."""

    occupant: str
    host: OverlayHostState
    html: str
    required: tuple[str, ...] = field(default=())


@dataclass(frozen=True)
class GalleryState:
    """One declared gallery state rendered from its fixture snapshot."""

    gallery_id: str  # state-gallery.md identifier (A2, B5, C1, E, F5, …)
    entry_state: str
    reentry_shape: str | None
    html: str
    required: tuple[str, ...] = field(default=())
    forbidden: tuple[str, ...] = field(default=())


@functools.lru_cache(maxsize=1)
def _gallery() -> dict[str, GalleryState]:
    """Render the full state gallery once from fixture snapshots."""
    states: dict[str, GalleryState] = {}

    def add(name: str, state: GalleryState) -> None:
        assert name not in states
        states[name] = state

    # --- A. Entry-point states -------------------------------------------
    # A1 boot is the pre-resolution handshake: the resolver declares it when
    # no orientation outcome exists; server-rendered pages always resolve the
    # fetch first, so A1 has no fixture page (asserted directly in the tests).
    add(
        "A2_first_contact",
        GalleryState(
            gallery_id="A2",
            entry_state="cold_start",
            reentry_shape=None,
            html=_render_orientation(orientation=_orientation_payload(leave_status="absent")),
            required=(
                'data-testid="workspace-orientation-vault-entry"',
                'data-intent="map.open"',
            ),
            forbidden=_REENTRY_OVERLAY_MARKERS,
        ),
    )
    add(
        "A2_first_contact_null_leave",
        GalleryState(
            gallery_id="A2",
            entry_state="cold_start",
            reentry_shape=None,
            html=_render_orientation(orientation=_orientation_payload(leave_status=None)),
            forbidden=_REENTRY_OVERLAY_MARKERS,
        ),
    )
    add(
        "A3_cold_trajectory_21d",
        GalleryState(
            gallery_id="A3",
            entry_state="cold_start",
            reentry_shape=None,
            html=_render_orientation(orientation=_orientation_payload(gap=_GAP_COLD)),
            required=('data-intent="map.open"',),
            forbidden=_REENTRY_OVERLAY_MARKERS,
        ),
    )
    add(
        "A4_full_mist",
        GalleryState(
            gallery_id="A4",
            entry_state="orienting",
            reentry_shape="full_mist",
            html=_render_orientation(
                orientation=_orientation_payload(gap=_GAP_FULL_MIST, trajectory_state="warm")
            ),
            required=(
                'data-region="reentry-card"',
                'data-traj-state="warm"',
                'data-intent="entry.resume"',
                'data-intent="entry.dismiss"',
                'data-testid="reentry-caret-echo"',
            ),
            forbidden=(
                'data-region="delta-strip"',
                'data-region="whisper-column"',
            ),
        ),
    )
    add(
        "A4_active_no_mist",
        GalleryState(
            gallery_id="A4",
            entry_state="orienting",
            reentry_shape="no_mist",
            html=_render_orientation(orientation=_orientation_payload(gap=_GAP_NO_MIST)),
            forbidden=_REENTRY_OVERLAY_MARKERS,
        ),
    )
    add(
        "A4_thread_fade",
        GalleryState(
            gallery_id="A4",
            entry_state="orienting",
            reentry_shape="thread_fade",
            html=_render_orientation(orientation=_orientation_payload(gap=_GAP_THREAD_FADE)),
            required=("data-rail-fade",),
            forbidden=(
                'data-region="reentry-card"',
                'data-region="reentry-peripheral-line"',
                'data-region="delta-strip"',
                'data-region="whisper-column"',
                "data-traj-state",
            ),
        ),
    )
    add(
        "A4_soft_mist",
        GalleryState(
            gallery_id="A4",
            entry_state="orienting",
            reentry_shape="soft_mist",
            html=_render_orientation(orientation=_orientation_payload(gap=_GAP_SOFT_MIST)),
            required=(
                'data-region="reentry-peripheral-line"',
                'data-testid="reentry-caret-echo"',
            ),
            forbidden=(
                'data-region="reentry-card"',
                'data-region="delta-strip"',
                'data-region="whisper-column"',
                "data-traj-state",
            ),
        ),
    )
    add(
        "A5_long_mist",
        GalleryState(
            gallery_id="A5",
            entry_state="orienting",
            reentry_shape="long_mist",
            html=_render_orientation(
                orientation=_orientation_payload(gap=_GAP_LONG_MIST, trajectory_state="dormant")
            ),
            required=(
                'data-region="reentry-card"',
                'data-traj-state="dormant"',
                'data-region="delta-strip"',
                'data-region="whisper-column"',
                'data-narrow-mode="suppressed"',
            ),
        ),
    )
    add(
        "A6_no_vault",
        GalleryState(
            gallery_id="A6",
            entry_state="no_vault",
            reentry_shape=None,
            html=_render_no_vault(),
            required=(
                'data-intent="entry.retry"',
                'data-intent="map.open"',
            ),
            forbidden=_REENTRY_OVERLAY_MARKERS,
        ),
    )
    add(
        "A6_no_vault_browser_down",
        GalleryState(
            gallery_id="A6",
            entry_state="no_vault",
            reentry_shape=None,
            html=_render_no_vault(vault_browser_down=True),
            required=('data-intent="entry.retry"',),
            forbidden=_REENTRY_OVERLAY_MARKERS,
        ),
    )
    add(
        "A7_degraded_full_mist",
        GalleryState(
            gallery_id="A7",
            entry_state="orienting",
            reentry_shape="full_mist",
            html=_render_orientation(
                orientation=_orientation_payload(
                    gap=_GAP_FULL_MIST,
                    degraded_reasons=["resurfacing_source_unavailable"],
                )
            ),
            required=(
                'data-degraded="true"',
                'data-testid="workspace-orientation-degraded"',
                "resurfacing_source_unavailable",
                'data-region="reentry-card"',
            ),
        ),
    )
    add(
        "A7_degraded_long_mist",
        GalleryState(
            gallery_id="A7",
            entry_state="orienting",
            reentry_shape="long_mist",
            html=_render_orientation(
                orientation=_orientation_payload(
                    gap=_GAP_LONG_MIST,
                    degraded_reasons=["resurfacing_source_unavailable"],
                )
            ),
            required=('data-degraded="true"', 'data-region="delta-strip"'),
        ),
    )
    add(
        "A4_stale_leave_point",
        GalleryState(
            gallery_id="A4+stale",
            entry_state="orienting",
            reentry_shape="full_mist",
            html=_render_orientation(
                orientation=_orientation_payload(leave_status="stale", gap=_GAP_FULL_MIST)
            ),
            required=(
                'data-stale="true"',
                'data-guard-held="true"',
                "Nothing was mutated",
            ),
        ),
    )
    add(
        "A4_artifact_missing",
        GalleryState(
            gallery_id="A4+stale",
            entry_state="orienting",
            reentry_shape="full_mist",
            html=_render_orientation(
                orientation=_orientation_payload(
                    leave_status="artifact_missing", gap=_GAP_FULL_MIST
                )
            ),
            required=(
                'data-stale="true"',
                'data-guard-held="true"',
                'data-testid="reentry-resume-reenter"',
            ),
            forbidden=('data-intent="entry.resume"',),
        ),
    )

    # --- B/E/F. Unified shell states -------------------------------------
    shell_occupant_markers = tuple(
        _OCCUPANT_MARKERS[occupant] for occupant in SHIPPED_OVERLAY_OCCUPANTS
    )
    add(
        "B1_shell_active_anchor",
        GalleryState(
            gallery_id="B1",
            entry_state="shell_active",
            reentry_shape=None,
            html=_render_workspace(),
            required=(
                'data-region="workspace-header"',
                'data-region="document-anchor"',
                'data-region="note-body"',
                'data-region="overlay-host"',
                'data-region="reentry-ambient"',
                "data-posture-emphasis=",
                'data-testid="workspace-vault-status-dot"',
                # B8 vault browser, B12 map, F1 settings, F5 capture,
                # F6 receipts, B9 memory, B5 cmd palette: every shipped
                # occupant's surface is mounted on this shell.
                *shell_occupant_markers,
                # F2 read-back: plan-inspected local TTS controls.
                'data-testid="tts-readback-controls"',
                'data-testid="tts-plan-inspection"',
            ),
        ),
    )
    add(
        "B3_staged_suggestion",
        GalleryState(
            gallery_id="B3",
            entry_state="shell_active",
            reentry_shape=None,
            html=_render_workspace(
                suggestion_state="staged_body",
                suggestion_cards=[
                    {
                        "data_variant": "body",
                        "data_suggestion_id": "sugg-1",
                        "title": "Staged body suggestion",
                        "preview_text": "Proposed paragraph text.",
                        "available_intents": ["suggestion.apply", "suggestion.discard"],
                    }
                ],
                suggested_insertions=[
                    {
                        "data_suggestion_id": "sugg-1",
                        "data_state": "staged",
                        "label": "suggested",
                        "proposed_text": "Proposed paragraph text.",
                        "is_visible": True,
                    }
                ],
            ),
            required=(
                'data-testid="suggestion-card"',
                'data-intent="suggestion.apply"',
                'data-intent="suggestion.discard"',
                'data-testid="suggested-insertion-block"',
                'data-state="staged"',
            ),
        ),
    )
    add(
        "B4_suggestion_applied",
        GalleryState(
            gallery_id="B4",
            entry_state="shell_active",
            reentry_shape=None,
            html=_render_workspace(
                suggested_insertions=[
                    {
                        "data_suggestion_id": "sugg-1",
                        "data_state": "applied",
                        "label": "applied · vault-canonical",
                        "proposed_text": "Applied paragraph text.",
                        "is_visible": True,
                    }
                ],
            ),
            required=(
                'data-testid="suggested-insertion-block"',
                'data-state="applied"',
            ),
        ),
    )
    add(
        "B5_panel_proposals",
        GalleryState(
            gallery_id="B5",
            entry_state="shell_active",
            reentry_shape=None,
            html=_render_workspace(
                panel_state="proposals-staged",
                panel_proposal_count=2,
                panel_proposals=[
                    _panel_proposal("prop-move-1", description="Move note to Projects"),
                    _panel_proposal("prop-tag-2", description="Add status tag evergreen"),
                ],
            ),
            required=(
                'data-proposal-id="prop-move-1"',
                'data-proposal-id="prop-tag-2"',
                'data-api-path="/api/panel/confirm"',
            ),
        ),
    )
    add(
        "B6_governed_receipt",
        GalleryState(
            gallery_id="B6",
            entry_state="shell_active",
            reentry_shape=None,
            html=_render_workspace(
                governance_receipts=[_governance_receipt(1)],
                panel_state="proposals-staged",
                panel_proposal_count=1,
                panel_proposals=[
                    _panel_proposal("prop-move-1", description="Move note to Projects"),
                ],
                # The runtime's declared confirm response — the only source a
                # receipt may render from (the UI invents none).
                panel_last_response={
                    "status": "executed",
                    "proposal_id": "prop-move-1",
                    "receipt": {
                        "outcome": "success",
                        "message": "moved via governed path",
                        "timestamp": "2026-06-10T11:00:00Z",
                    },
                },
            ),
            required=(
                'data-testid="receipts-strip"',
                'data-receipt-id="receipt-1"',
                'data-testid="palette-receipt"',
                'data-receipt-persistence="durable-runtime-projection"',
            ),
        ),
    )
    add(
        "B7_panel_blocked",
        GalleryState(
            gallery_id="B7",
            entry_state="shell_active",
            reentry_shape=None,
            html=_render_workspace(
                guard_writeguard_status="blocked",
                panel_state="proposals-staged",
                panel_proposal_count=1,
                panel_proposals=[
                    _panel_proposal("prop-cross-1", description="Cross-note proposal"),
                ],
            ),
            required=(
                'data-guard-held="true"',
                'data-guard-gate="writeguard"',
            ),
        ),
    )

    # C1 narrow/portrait, E guidance, and the F-states are cross-cutting
    # presentations of the shell render; their assertions live in the
    # dedicated tests below against the B1 fixture page.
    return states


@functools.lru_cache(maxsize=1)
def _open_overlay_gallery() -> dict[str, OpenOverlayFixture]:
    """Exercise every shipped overlay occupant as an open host-state fixture.

    The rendered shell mounts each occupant closed by default; the open-state
    proof stays pure and deterministic by using the same overlay-host model
    the in-page controller mirrors.
    """
    shell = _gallery()["B1_shell_active_anchor"].html
    base = OverlayHostState(
        anchor_note_path="Notes/note.md",
        route="/api/companion/workspace?note_path=Notes%2Fnote.md",
        scroll_owner="note-body",
        rail_state="open",
        staged_suggestion_ids=("sugg-1",),
        open_loop_count=3,
    )
    return {
        occupant: OpenOverlayFixture(
            occupant=occupant,
            host=mount(base, occupant),
            html=shell,
            required=(
                _OCCUPANT_MARKERS[occupant],
                _OCCUPANT_REGISTRATION_MARKERS[occupant],
            ),
        )
        for occupant in SHIPPED_OVERLAY_OCCUPANTS
    }


def _body_tag(html: str) -> str:
    m = re.search(r"<body[^>]*>", html)
    assert m, "rendered page must have a <body> tag"
    return m.group(0)


def _entry_state(html: str) -> str:
    states = re.findall(r'data-entry-state="([^"]*)"', _body_tag(html))
    assert len(states) == 1, "shell root must declare exactly one entry state"
    return states[0]


def _reentry_shape(html: str) -> str | None:
    shapes = re.findall(r'data-reentry-shape="([^"]*)"', _body_tag(html))
    assert len(shapes) <= 1
    return shapes[0] if shapes else None


# CodeQL-safe script stripper: tolerant of attributes on both tags.
_SCRIPT_RE = re.compile(r"<script\b[^>]*>([\s\S]*?)</script\b[^>]*>", re.I)


def _without_scripts(html: str) -> str:
    return _SCRIPT_RE.sub("", html)


def _scripts(html: str) -> str:
    return "\n".join(m.group(1) for m in _SCRIPT_RE.finditer(html))


# ---------------------------------------------------------------------------
# AC: every declared gallery state renders from a fixture with its declared
# data-entry-state / regions present
# ---------------------------------------------------------------------------


def test_state_gallery_renders_all_declared_states() -> None:
    gallery = _gallery()

    for name, state in gallery.items():
        declared = _entry_state(state.html)
        assert declared == state.entry_state, name
        assert declared in ENTRY_STATES, name
        assert _reentry_shape(state.html) == state.reentry_shape, name
        for marker in state.required:
            assert marker in state.html, f"{name}: missing {marker}"
        for marker in state.forbidden:
            assert marker not in state.html, f"{name}: must not render {marker}"

    # A1 boot: the pre-resolution handshake state. The resolver declares it
    # while no orientation outcome exists; every rendered page resolves the
    # fetch before emitting HTML, so no gallery page declares boot.
    assert resolve_entry_state().state == "boot"
    for name, state in gallery.items():
        assert _entry_state(state.html) != "boot", name

    # Coverage completeness: the gallery exercises every declared entry state
    # (boot via the resolver) and every declared re-entry shape.
    rendered_states = {state.entry_state for state in gallery.values()}
    assert rendered_states | {"boot"} == set(ENTRY_STATES)
    rendered_shapes = {
        state.reentry_shape for state in gallery.values() if state.reentry_shape is not None
    }
    assert rendered_shapes == set(REENTRY_SHAPES)

    # Every shipped overlay occupant has its surface mounted on the shell
    # fixture (B/E/F states), and the topbar offers only shipped surfaces.
    shell = gallery["B1_shell_active_anchor"].html
    for occupant in SHIPPED_OVERLAY_OCCUPANTS:
        assert _OCCUPANT_MARKERS[occupant] in shell, occupant
    rendered_icons = set(re.findall(r'data-surface="([^"]+)"', shell))
    assert rendered_icons == set(SHIPPED_TOPBAR_SURFACES)

    # E. guidance layer: off by default in every gallery state (the root
    # never carries data-guidance="on" server-side), with the ⓘ toggle and
    # server-rendered callouts present on the shell.
    for name, state in gallery.items():
        assert 'data-guidance="on"' not in _body_tag(state.html), name
    assert 'data-intent="guidance.toggle"' in shell
    assert "guidance-callout" in shell


def test_state_gallery_exercises_each_shipped_overlay_open_state() -> None:
    fixtures = _open_overlay_gallery()
    assert set(fixtures) == set(SHIPPED_OVERLAY_OCCUPANTS)
    assert set(_OCCUPANT_MARKERS) == set(SHIPPED_OVERLAY_OCCUPANTS)
    assert set(_OCCUPANT_REGISTRATION_MARKERS) == set(SHIPPED_OVERLAY_OCCUPANTS)
    assert set(_OCCUPANT_OPEN_INTENTS) == set(SHIPPED_OVERLAY_OCCUPANTS)

    base = OverlayHostState(
        anchor_note_path="Notes/note.md",
        route="/api/companion/workspace?note_path=Notes%2Fnote.md",
        scroll_owner="note-body",
        rail_state="open",
        staged_suggestion_ids=("sugg-1",),
        open_loop_count=3,
    )

    for occupant, fixture in fixtures.items():
        assert fixture.occupant == occupant
        assert fixture.host.stack == (occupant,), occupant
        assert apply_intent(base, _OCCUPANT_OPEN_INTENTS[occupant]) == fixture.host

        host = re.search(r'<div[^>]*data-region="overlay-host"[^>]*>', fixture.html)
        assert host, occupant
        declared = re.search(r'data-declared-overlays="([^"]*)"', host.group(0))
        shipped = re.search(r'data-shipped-occupants="([^"]*)"', host.group(0))
        assert declared and occupant in declared.group(1).split(), occupant
        assert shipped and occupant in shipped.group(1).split(), occupant

        for marker in fixture.required:
            assert marker in fixture.html, f"{occupant}: missing {marker}"

        closed = dismiss(fixture.host)
        assert closed.stack == (), occupant
        assert closed.anchor_note_path == base.anchor_note_path, occupant
        assert closed.route == base.route, occupant
        assert closed.scroll_owner == base.scroll_owner, occupant
        assert closed.rail_state == base.rail_state, occupant
        assert closed.staged_suggestion_ids == base.staged_suggestion_ids, occupant
        assert closed.open_loop_count == base.open_loop_count, occupant

    # Declared-but-unshipped overlays stay inert, and parked Q15/Q16 surfaces
    # are not part of the shipped open-state coverage.
    unshipped = set(DECLARED_OVERLAYS) - set(SHIPPED_OVERLAY_OCCUPANTS)
    assert unshipped
    assert unshipped.isdisjoint(fixtures)
    for occupant in unshipped:
        assert mount(base, occupant) == base, occupant
    for parked in ("context", "location"):
        assert parked not in fixtures
        with pytest.raises(ValueError):
            mount(base, parked)


# ---------------------------------------------------------------------------
# AC: undeclared entry transitions are rejected across the fixture matrix
# ---------------------------------------------------------------------------


def test_undeclared_transitions_rejected_across_fixtures() -> None:
    gallery = _gallery()

    # The resolution type rejects undeclared states, shapes, and cross-flag
    # placements at the type level.
    with pytest.raises(ValueError):
        EntryStateResolution(state="dashboard")
    with pytest.raises(ValueError):
        EntryStateResolution(state="orienting", reentry_shape="dense_fog")
    with pytest.raises(ValueError):
        EntryStateResolution(state="cold_start", reentry_shape="full_mist")
    with pytest.raises(ValueError):
        EntryStateResolution(state="no_vault", degraded=True)
    with pytest.raises(ValueError):
        EntryStateResolution(state="boot", stale=True)

    # Declared transitions render across the matrix:
    # boot → cold_start / orienting / no_vault per the fixture signal …
    assert _entry_state(gallery["A2_first_contact"].html) == "cold_start"
    assert _entry_state(gallery["A4_full_mist"].html) == "orienting"
    assert _entry_state(gallery["A6_no_vault"].html) == "no_vault"
    # … no_vault → boot via entry.retry (the declared retry affordance) …
    assert 'data-intent="entry.retry"' in gallery["A6_no_vault"].html
    # … cold_start → shell_active via vault.open / map→surface …
    assert 'data-testid="workspace-orientation-vault-entry"' in gallery["A2_first_contact"].html
    # … orienting → shell_active via entry.resume | entry.dismiss …
    assert 'data-intent="entry.resume"' in gallery["A4_full_mist"].html
    assert 'data-intent="entry.dismiss"' in gallery["A4_full_mist"].html
    # … and the resumed shell renders shell_active.
    assert _entry_state(gallery["B1_shell_active_anchor"].html) == "shell_active"

    # Out-of-contract fixture inputs resolve to the nearest declared state
    # with the divergence surfaced — never an implicit new state.
    matrix = [
        _orientation_payload(leave_status="warping"),
        _orientation_payload(leave_status="present", gap=None),
        {},
        {"leave_point": "not-a-dict"},
        {"leave_point": {"status": 42}},
    ]
    for payload in matrix:
        resolution = resolve_entry_state(orientation=payload)
        assert resolution.state in ENTRY_STATES
        assert resolution.reentry_shape is None or resolution.reentry_shape in REENTRY_SHAPES
        rendered = _render(orientation=payload)
        assert _entry_state(rendered) in ENTRY_STATES

    # Within shell_active the overlay layer rejects undeclared occupants and
    # undeclared intents (spec: reject any transition not enumerated).
    host = OverlayHostState(anchor_note_path="Notes/note.md")
    for bogus in ("task-popup", "notifications", "VAULT", ""):
        with pytest.raises(ValueError):
            mount(host, bogus)
    with pytest.raises(ValueError):
        apply_intent(host, "overlay.maximize")
    assert set(KEYBOARD_MAP.values()) == {"cmd.open", "capture.open", "overlay.dismiss"}

    # Reserved parked intents (§Parked Q15–Q16) are not implementable and
    # never render in any gallery state; the parked overlay ids stay
    # undeclared on the host.
    for name, state in gallery.items():
        assert 'data-intent="context.open"' not in state.html, name
        assert 'data-intent="location.enable"' not in state.html, name
    assert "context" not in DECLARED_OVERLAYS
    assert "location" not in DECLARED_OVERLAYS


# ---------------------------------------------------------------------------
# AC: cold, first-contact, and no-vault fixtures contain no re-entry overlay
# ---------------------------------------------------------------------------


def test_cold_and_no_vault_have_no_reentry_overlay() -> None:
    gallery = _gallery()
    no_overlay_states = (
        "A2_first_contact",
        "A2_first_contact_null_leave",
        "A3_cold_trajectory_21d",
        "A6_no_vault",
        "A6_no_vault_browser_down",
    )
    for name in no_overlay_states:
        page = gallery[name].html
        assert _reentry_shape(page) is None, name
        for marker in _REENTRY_OVERLAY_MARKERS:
            assert marker not in page, f"{name}: {marker}"
        # No continuity claim the system cannot back: no resume affordance.
        assert 'data-intent="entry.resume"' not in page, name

    # no_vault never fabricates a fresh successful snapshot (gallery A6
    # MUST NOT): the fixture's orientation content does not render.
    for name in ("A6_no_vault", "A6_no_vault_browser_down"):
        page = gallery[name].html
        assert "Resume the runtime API contract" not in page, name
        assert "Open loop label 0" not in page, name


# ---------------------------------------------------------------------------
# AC: governed-vs-body-edit receipt asymmetry holds across the gallery
# ---------------------------------------------------------------------------


def test_governed_vs_body_edit_receipt_asymmetry() -> None:
    gallery = _gallery()
    shell = gallery["B1_shell_active_anchor"].html

    # Governed intents declare the governed pipeline transport on the shell:
    # panel.confirm → POST /api/panel/confirm (rail and palette, one
    # transport, no palette-local execution) …
    palette = gallery["B5_panel_proposals"].html
    assert 'data-api-path="/api/panel/confirm"' in palette
    # The runtime receipt persists as a durable runtime projection (B6).
    assert (
        'data-receipt-persistence="durable-runtime-projection"'
        in gallery["B6_governed_receipt"].html
    )
    # … capture.save → the governed capture append (#1790) …
    assert "/api/companion/capture" in shell
    assert 'data-intent="capture.save"' in shell
    # … vault.queue → the governed queue-review handoff …
    assert "/api/companion/vault-browser/actions/queue-review" in shell
    # … memory review decisions → the governed decision boundary (ADR-0009).
    assert "/decision" in shell

    # Governed outcomes surface receipts the runtime produced: the reflected
    # receipt pill renders with the server-declared receipt id (B6) and the
    # read-only receipts history surface is mounted (F6).
    receipt_page = gallery["B6_governed_receipt"].html
    assert 'data-receipt-id="receipt-1"' in receipt_page
    assert 'data-testid="receipts-history-modal"' in shell

    # Memory review: accept/reject/revise are governed receipt-bearing
    # decisions; defer is non-terminal and receipt-free — marked explicitly
    # on the server-rendered candidate fragment (B9).
    assert set(GOVERNED_REVIEW_ACTIONS) == {"accept", "reject", "revise"}
    assert set(NON_TERMINAL_REVIEW_ACTIONS) == {"defer"}
    assert set(REVIEW_ACTIONS) == {"accept", "reject", "revise", "defer"}
    fragment = memory_review_queue_fragment(
        {
            "pending_count": 1,
            "candidates": [
                {
                    "candidate_id": "cand-1",
                    "title": "Candidate memory",
                    "why_now": "Surfaced by the re-entry inspect affordance.",
                    "proposed_memory_type": "semantic",
                    "authority_posture": {
                        "authority": "non_authoritative",
                        "authority_role": "candidate",
                        "review_posture": "pending_explicit_review",
                        "semantic_authority": False,
                    },
                }
            ],
        }
    )
    for action in GOVERNED_REVIEW_ACTIONS:
        m = re.search(rf'<button[^>]*data-action="{action}"[^>]*>', fragment)
        assert m and 'data-governed="true"' in m.group(0), action
        assert "data-non-terminal" not in m.group(0), action
    defer = re.search(r'<button[^>]*data-action="defer"[^>]*>', fragment)
    assert defer and 'data-governed="false"' in defer.group(0)
    assert 'data-non-terminal="true"' in defer.group(0)

    # Body-edit lane: suggestion.apply / suggestion.discard render with no
    # governance receipt anywhere — staged and applied blocks carry no
    # receipt id, and no receipts strip renders without server-declared rows.
    staged = gallery["B3_staged_suggestion"].html
    applied = gallery["B4_suggestion_applied"].html
    for page, name in ((staged, "B3"), (applied, "B4")):
        block = re.search(r'<ins[^>]*data-testid="suggested-insertion-block"[^>]*>', page)
        assert block, name
        assert "data-receipt-id" not in block.group(0), name
        assert 'data-testid="receipts-strip"' not in page, (
            f"{name}: a body edit must never produce a governance receipt"
        )
    apply_button = re.search(r'<button[^>]*data-intent="suggestion.apply"[^>]*>', staged)
    assert apply_button and "receipt" not in apply_button.group(0).lower()

    # Receipts are never invented by the UI: every rendered receipt id is
    # traceable to a fixture-declared receipt row.
    for name, state in gallery.items():
        for receipt_id in re.findall(r'data-receipt-id="([^"]+)"', state.html):
            assert receipt_id == "receipt-1", (name, receipt_id)
            assert name == "B6_governed_receipt", name

    # Blocked and stale present as guard-held states, never generic errors.
    blocked = gallery["B7_panel_blocked"].html
    assert 'data-guard-held="true"' in blocked
    assert 'data-guard-gate="writeguard"' in blocked
    stale = gallery["A4_stale_leave_point"].html
    guard = stale.split('data-testid="reentry-resume-guard"', 1)[1].split("</div>", 1)[0]
    assert "Nothing was mutated" in guard
    assert "error" not in guard.lower()
    assert 'data-testid="workspace-error-state"' not in stale


# ---------------------------------------------------------------------------
# AC: no fixture render contains UI-derived authority classification
# ---------------------------------------------------------------------------


def test_no_ui_derived_authority() -> None:
    gallery = _gallery()

    # Trajectory state is rendered exactly as the fixture declares it —
    # warm renders warm, dormant renders dormant, never re-classified.
    assert 'data-traj-state="warm"' in gallery["A4_full_mist"].html
    assert 'data-traj-state="dormant"' in gallery["A5_long_mist"].html

    # Authority roles render verbatim from the fixture payload: flipping the
    # declared role flips the rendered attribute with no UI normalization.
    # CUIDR-06 (#2450): the governance summary tile no longer renders on the
    # orientation surface (operator telemetry lives behind the System Map), so
    # this verbatim-authority contract is exercised on a panel that still
    # renders from full_mist up — the open-loop provenance.
    custom_payload = _orientation_payload(gap=_GAP_FULL_MIST)
    custom_payload["open_loops"][0]["authority_role"] = "fixture_declared_role"
    custom = _render(orientation=custom_payload)
    assert 'data-authority-role="fixture_declared_role"' in custom
    baseline = gallery["A4_full_mist"].html
    assert 'data-authority-role="fixture_declared_role"' not in baseline

    # The posture pill is Local UI emphasis only (§Resolved Q6): rendering
    # only, declared default, no switch affordance (the posture-switch
    # overlay has not shipped), and never conflated with a cognitive mode.
    shell = gallery["B1_shell_active_anchor"].html
    pill = re.search(r'<span[^>]*data-testid="workspace-posture-pill"[^>]*>', shell)
    assert pill and 'data-authority="local-ui"' in pill.group(0)
    emphasis = re.search(r'data-posture-emphasis="([^"]+)"', pill.group(0))
    assert emphasis and emphasis.group(1) == DEFAULT_POSTURE_EMPHASIS
    assert DEFAULT_POSTURE_EMPHASIS in POSTURE_EMPHASES
    for name, state in gallery.items():
        # No fixture declares a cognitive mode, so no page may invent one.
        assert "data-cognitive-mode" not in state.html, name
        # The unshipped posture switch never renders an affordance.
        assert 'data-intent="posture.open"' not in state.html, name

    # Entry-state classification is server-resolved; no client script
    # re-derives it from payload contents. The only client write is the
    # declared `orienting → shell_active` transition (entry.dismiss /
    # entry.resume), which applies the constant declared target state —
    # never a computed classification.
    for name, state in gallery.items():
        script = _scripts(state.html)
        for write in re.findall(r"setAttribute\(['\"]data-entry-state['\"],\s*([^)]+)\)", script):
            assert write.strip() in ("'shell_active'", '"shell_active"'), (name, write)
        for attribute in ("data-traj-state", "data-reentry-shape", "data-authority-role"):
            assert f"setAttribute('{attribute}'" not in script, (name, attribute)
            assert f'setAttribute("{attribute}"' not in script, (name, attribute)

    # The rendered entry state equals the pure resolver's output for the
    # same fixture snapshot — the page never re-branches on payload contents.
    for payload, expected in (
        (_orientation_payload(leave_status="absent"), "cold_start"),
        (_orientation_payload(gap=_GAP_COLD), "cold_start"),
        (_orientation_payload(gap=_GAP_FULL_MIST), "orienting"),
        (_orientation_payload(gap=_GAP_LONG_MIST), "orienting"),
    ):
        resolution = resolve_entry_state(orientation=payload)
        assert resolution.state == expected
        assert _entry_state(_render(orientation=payload)) == expected


# ---------------------------------------------------------------------------
# AC: display budget ≤ server caps; reduced-motion full visibility; narrow
# parity for every critical affordance
# ---------------------------------------------------------------------------


def test_budget_reduced_motion_and_narrow_parity() -> None:
    gallery = _gallery()

    # Display budget (§Resolved Q5): the default scarce subset shows 3 items
    # per collection; deliberate expansion never exceeds the server caps
    # (8/8/5) even when the fixture over-declares.
    overloaded = _render(
        orientation=_orientation_payload(
            gap=_GAP_LONG_MIST,
            open_loops=10,
            notable_changes=10,
            resurface_candidates=7,
        )
    )
    for collection, overflow_id in (
        ("open-loop", "open-loop-overflow"),
        ("notable-change", "notable-change-overflow"),
    ):
        visible = overloaded.count(f'data-testid="workspace-orientation-{collection}"')
        assert visible == _DEFAULT_VISIBLE, collection
    assert overloaded.count('data-testid="workspace-orientation-resurface-candidate"') == 3
    total_loops = overloaded.count(
        'data-testid="workspace-orientation-open-loop"'
    ) + overloaded.count('data-testid="workspace-orientation-open-loop-overflow"')
    assert total_loops <= _SERVER_CAPS["open_loops"]
    total_changes = overloaded.count(
        'data-testid="workspace-orientation-notable-change"'
    ) + overloaded.count('data-testid="workspace-orientation-notable-change-overflow"')
    assert total_changes <= _SERVER_CAPS["notable_changes"]
    total_resurface = overloaded.count(
        'data-testid="workspace-orientation-resurface-candidate"'
    ) + overloaded.count('data-testid="workspace-orientation-resurface-overflow-candidate"')
    assert total_resurface <= _SERVER_CAPS["resurface_candidates"]
    # Items beyond the cap never render; the card keeps counts, never lists.
    assert "Open loop label 9" not in overloaded
    assert "8 open loops · 1 staged" in overloaded

    # Reduced motion: every gallery end-state is fully visible without
    # animation — the declared regions are server-rendered static markup
    # (still present with every script stripped), and any CSS animation
    # declares a prefers-reduced-motion override that disables it while
    # keeping the element visible.
    for name, state in gallery.items():
        static = _without_scripts(state.html)
        assert _entry_state(static) == state.entry_state, name
        for marker in state.required:
            assert marker in static, f"{name}: {marker} must not depend on scripts"
        animations = [
            m
            for m in re.findall(r"animation:\s*([^;]+);", state.html)
            if m.strip() != "none"
        ]
        if animations:
            assert "@media (prefers-reduced-motion: reduce)" in state.html, name
            reduced_block = state.html.split("@media (prefers-reduced-motion: reduce)", 1)[1][:400]
            assert "animation: none" in reduced_block, name

    # Narrow/portrait parity (C1): the shell collapses to one column with
    # bottom-sheet triggers and the modal vault browser; no critical
    # affordance is display-gated away.
    shell = gallery["B1_shell_active_anchor"].html
    assert 'class="workspace-sheet-triggers"' in shell
    assert 'data-testid="workspace-outline-sheet-trigger"' in shell
    assert 'data-testid="workspace-panel-sheet-trigger"' in shell
    assert 'data-testid="vault-browser-overlay"' in shell
    assert 'data-browser-role="responsive-fallback"' in shell
    # The rail becomes a fixed bottom sheet in portrait (OVERLAY_GRAMMAR.md).
    narrow_sheet_css = shell.split("@media (max-width: 899px)", 1)[1]
    assert ".portrait-sheet" in narrow_sheet_css
    assert "position: fixed" in narrow_sheet_css.split(".portrait-sheet", 2)[1]
    # The topbar's surface icons and the anchor pill stay reachable.
    assert not re.search(r"\.workspace-surface-icons[^{]*\{[^}]*display:\s*none", shell)
    assert not re.search(r"\.workspace-anchor-pill[^{]*\{[^}]*display:\s*none", shell)
    # Every shipped occupant surface stays mounted regardless of width: the
    # narrow stylesheet hides panes (which have modal/sheet fallbacks), not
    # the overlay-host occupants.
    for occupant in SHIPPED_OVERLAY_OCCUPANTS:
        assert _OCCUPANT_MARKERS[occupant] in shell, occupant

    # The whisper column is suppressed in narrow mode, collapsing into the
    # card (declared on the element and enforced by the narrow stylesheet).
    long_mist = gallery["A5_long_mist"].html
    whisper = long_mist.split('data-region="whisper-column"', 1)[1].split("</aside>", 1)[0]
    assert 'data-narrow-mode="suppressed"' in whisper
    assert ".reentry-whisper-col { display: none; }" in long_mist
    assert "@media (max-width: 860px)" in long_mist
