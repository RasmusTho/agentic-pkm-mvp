"""Latency-ladder re-entry treatments on the orientation surface (#1784, SEP-02).

Implements the `orienting` treatments per re-entry shape declared by SEP-01's
server-side resolution (`entry_state.py`, #1783) on the existing orientation
surface in ``serve_dev_page.py``:

- ``full_mist`` / ``long_mist`` render the four-fixed-questions card
  (``data-region="reentry-card"``) with counts-not-enumerations for unresolved
  items and a server-declared ``data-traj-state`` pill;
- ``long_mist`` adds the delta strip (``data-region="delta-strip"``) and the
  right-margin whisper column (suppressed in narrow mode, collapsing into the
  card);
- ``soft_mist`` renders no card — residual ambient cues only (caret-echo cue
  plus a single peripheral "where you stopped" line);
- ``thread_fade`` renders no card and no peripheral line — only the fractional
  rail fade distinguishes it from the active state;
- cold start / first contact render no re-entry overlay of any kind;
- degraded renders an amber banner naming the missing source; a stale leave
  point renders the card guard-held per BLOCKED_AND_STALE_STATE_SPEC.md;
- the display budget caps default visible items at 3 per collection and
  deliberate expansion never exceeds the server caps (8/8/5);
- after resume, the residual ambient layer (caret echo, marginalia) persists
  into ``shell_active``.

Authority: ``companion-ui/docs/SYSTEM_ENTRY_POINT_SPEC.md`` §Entry-point state
model, §Resolved Q5, §Resolved Q9; ``docs/SYSTEM_ENTRY_POINT/
REENTRY_ORIENTATION_TREATMENT.md``; ``companion-ui/docs/CONTINUITY_AND_DECAY.md``;
``companion-ui/docs/BLOCKED_AND_STALE_STATE_SPEC.md``;
``companion-ui/docs/WORKSPACE_ORIENTATION_CONTRACT.md`` §Cognitive-Load Display
Budget.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from companion_ui.workspace.serve_dev_page import render_index_html

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_AS_OF = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)

# Latency-ladder gaps (CONTINUITY_AND_DECAY.md).
_GAP_NO_MIST = timedelta(seconds=30)
_GAP_THREAD_FADE = timedelta(minutes=5)
_GAP_SOFT_MIST = timedelta(hours=1)
_GAP_FULL_MIST = timedelta(days=1)
_GAP_LONG_MIST = timedelta(days=7)
_GAP_COLD = timedelta(days=20)


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
        "artifact_ref": _artifact_ref(f"Notes/change-{idx}.md", f"Change {idx}", f"art-change-{idx}"),
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
    degraded_reasons: list[str] | None = None,
    open_loops: int = 3,
    notable_changes: int = 2,
    resurface_candidates: int = 1,
    staged_proposals: int = 1,
) -> dict[str, Any]:
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
                "open_loops": 8,
                "notable_changes": 8,
                "resurface_candidates": 5,
                "mutation_intents": 0,
                "source_refs_per_item": 3,
            },
        },
        "leave_point": leave_point,
        "open_loops": [_open_loop(idx) for idx in range(open_loops)],
        "notable_changes": [_notable_change(idx) for idx in range(notable_changes)],
        "resurface": {"candidates": [_resurface_candidate(idx) for idx in range(resurface_candidates)]},
        "governance": {
            "pending_proposal_count": staged_proposals,
            "pending_receipt_count": 0,
            "latest_receipt_outcome": "logged",
            "authority_role": "derived",
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


def _render(**kwargs: Any) -> str:
    return render_index_html(api_base_url="http://127.0.0.1:18001", **kwargs)


def _reentry_card(html: str) -> str:
    """Extract the re-entry card region markup."""
    assert 'data-region="reentry-card"' in html
    return html.split('data-region="reentry-card"', 1)[1].split("</section>", 1)[0]


_OVERLAY_MARKERS = (
    'data-region="reentry-card"',
    'data-region="delta-strip"',
    'data-region="whisper-column"',
    'data-region="reentry-peripheral-line"',
    "data-traj-state",
    "data-rail-fade",
    'data-testid="reentry-caret-echo"',
)


# ---------------------------------------------------------------------------
# AC: full_mist renders the four fixed questions with counts-not-enumerations
# ---------------------------------------------------------------------------


def test_full_mist_renders_four_fixed_questions_with_counts() -> None:
    html = _render(orientation=_orientation_payload(gap=_GAP_FULL_MIST))

    card = _reentry_card(html)

    # The four fixed questions, shapes fixed (CONTINUITY_AND_DECAY.md).
    for question in ("doing", "stopped", "unresolved", "changed"):
        assert f'data-reentry-question="{question}"' in card, question
    assert len(re.findall(r'data-reentry-question="', card)) == 4

    # Trajectory state pill is server-declared on the card.
    assert re.search(r'data-traj-state="(warm|dormant)"', card)

    # Unresolved is counts, never an enumeration: "3 open loops · 1 staged".
    assert "3 open loops · 1 staged" in card
    for idx in range(3):
        assert f"Open loop label {idx}" not in card

    # "What changed since" is a delta count, never a timeline.
    assert "2 changes" in card
    assert "Notable change label 0" not in card

    # Deliberate inspect affordance routes to the existing orientation
    # sections until the memory review drawer (SEP-09) lands.
    assert 'data-testid="reentry-inspect"' in card
    assert 'href="#workspace-orientation-open-loops"' in card

    # Resume affordance carries the declared intent and jumps to the artifact.
    assert 'data-intent="entry.resume"' in card
    assert "/workspace?note_path=Notes%2Fresume.md" in card

    # Caret-echo cue at the momentum stop point.
    assert 'data-testid="reentry-caret-echo"' in card

    # full_mist carries no long-mist additions.
    assert 'data-region="delta-strip"' not in html
    assert 'data-region="whisper-column"' not in html

    # No notification/badge/urgency semantics of any kind.
    lowered = card.lower()
    for forbidden in ("notification", "badge", "urgent", "inbox", "overdue"):
        assert forbidden not in lowered, forbidden


# ---------------------------------------------------------------------------
# AC: long_mist adds the delta strip and whisper column (suppressed narrow)
# ---------------------------------------------------------------------------


def test_long_mist_adds_delta_strip_and_whisper_column() -> None:
    html = _render(orientation=_orientation_payload(gap=_GAP_LONG_MIST))

    # The card still renders with the four fixed questions.
    card = _reentry_card(html)
    assert len(re.findall(r'data-reentry-question="', card)) == 4

    # Delta strip from notable_changes, inside the card region.
    assert 'data-region="delta-strip"' in card
    assert "Notable change label 0" in card

    # Right-margin whisper column with the four named items.
    assert 'data-region="whisper-column"' in html
    whisper = html.split('data-region="whisper-column"', 1)[1].split("</aside>", 1)[0]
    for label in ("doing", "unresolved", "changed", "resurfaced"):
        assert f'data-whisper-item="{label}"' in whisper, label

    # Suppressed in narrow mode, collapsing into the card: declared on the
    # element and enforced by the page's narrow-mode stylesheet.
    assert 'data-narrow-mode="suppressed"' in whisper
    narrow_css = html.split("@media (max-width: 860px)", 1)[1].split("}\n", 1)[0]
    assert ".reentry-whisper-col { display: none; }" in html
    assert narrow_css is not None  # media query present


# ---------------------------------------------------------------------------
# AC: soft_mist renders no card — residual ambient cues only
# ---------------------------------------------------------------------------


def test_soft_mist_renders_no_card() -> None:
    html = _render(orientation=_orientation_payload(gap=_GAP_SOFT_MIST))

    # No re-entry card, no long-mist additions, no trajectory pill.
    assert 'data-region="reentry-card"' not in html
    assert 'data-region="delta-strip"' not in html
    assert 'data-region="whisper-column"' not in html
    assert "data-traj-state" not in html

    # Residual ambient cues only: caret-echo cue at the leave point plus a
    # single peripheral "where you stopped" line.
    assert 'data-testid="reentry-caret-echo"' in html
    assert html.count('data-region="reentry-peripheral-line"') == 1
    line = html.split('data-region="reentry-peripheral-line"', 1)[1].split("</p>", 1)[0]
    assert "Where you stopped" in line
    assert "Resume the runtime API contract" in line


# ---------------------------------------------------------------------------
# AC: thread_fade renders no card and no peripheral line — rail fade only
# ---------------------------------------------------------------------------


def test_thread_fade_renders_no_card_and_no_peripheral_line() -> None:
    html = _render(orientation=_orientation_payload(gap=_GAP_THREAD_FADE))

    # No card, no peripheral line, no whisper, no delta strip.
    assert 'data-region="reentry-card"' not in html
    assert 'data-region="reentry-peripheral-line"' not in html
    assert 'data-region="delta-strip"' not in html
    assert 'data-region="whisper-column"' not in html
    assert "data-traj-state" not in html

    # The conversation/rail pane fades a fraction; trajectory stays implicit.
    fade = re.search(r'data-rail-fade="(0\.\d+)"', html)
    assert fade, "thread_fade must declare the fractional rail fade"
    assert 0.0 < float(fade.group(1)) < 1.0

    # Only the fractional rail fade distinguishes thread_fade from the active
    # (no_mist) state: the active render carries no overlay marker at all.
    active = _render(orientation=_orientation_payload(gap=_GAP_NO_MIST))
    for marker in _OVERLAY_MARKERS:
        assert marker not in active, marker


# ---------------------------------------------------------------------------
# AC: cold start and first contact render no re-entry overlay at this surface
# ---------------------------------------------------------------------------


def test_cold_and_first_contact_render_no_overlay() -> None:
    pages = [
        # First contact: leave_point.status absent.
        _render(orientation=_orientation_payload(leave_status="absent")),
        # First contact: no leave point at all.
        _render(orientation=_orientation_payload(leave_status=None)),
        # Cold trajectory: gap beyond 14 days.
        _render(orientation=_orientation_payload(gap=_GAP_COLD)),
    ]
    for page in pages:
        for marker in _OVERLAY_MARKERS:
            assert marker not in page, marker


# ---------------------------------------------------------------------------
# AC: degraded renders the amber banner naming the missing source
# ---------------------------------------------------------------------------


def test_degraded_banner_names_missing_source() -> None:
    html = _render(
        orientation=_orientation_payload(
            gap=_GAP_FULL_MIST,
            degraded_reasons=["resurfacing_source_unavailable"],
        )
    )

    # The amber banner names the missing source.
    assert 'data-testid="workspace-orientation-degraded"' in html
    banner = html.split('data-testid="workspace-orientation-degraded"', 1)[1].split(
        "</section>", 1
    )[0]
    assert 'data-tone="amber"' in html
    assert "Missing source" in banner
    assert "resurfacing_source_unavailable" in banner

    # Calm, never an alarm: amber styling, not the destructive token.
    assert ".orientation-degraded" in html
    degraded_css = html.split(".orientation-degraded {", 1)[1].split("}", 1)[0]
    assert "240,144,48" in degraded_css  # --amber #f09030
    assert "255,61,61" not in degraded_css  # never the destructive red

    # The resolved slices still render alongside the banner.
    assert "Resume the runtime API contract" in html
    assert "Open loop label 0" in html
    assert 'data-region="reentry-card"' in html


# ---------------------------------------------------------------------------
# AC: stale leave point renders the card guard-held, never a generic error
# ---------------------------------------------------------------------------


def test_stale_leave_point_renders_qualified_resume() -> None:
    stale = _render(
        orientation=_orientation_payload(leave_status="stale", gap=_GAP_FULL_MIST)
    )

    # The card still renders, with a qualified guard-held resume affordance.
    card = _reentry_card(stale)
    assert 'data-testid="reentry-resume-guard"' in card
    assert 'data-guard-held="true"' in card
    # Names the cause and states that nothing was mutated.
    assert "Source changed since this was captured" in card
    assert "Nothing was mutated" in card
    # Offers a path forward into the current artifact state — qualified, not
    # a silent resume claiming unbroken continuity.
    assert 'data-intent="entry.resume"' in card
    assert "Open the current artifact state" in card

    # Never a generic error: no error region, no destructive alarm copy.
    assert 'data-testid="workspace-error-state"' not in stale
    assert "error" not in card.lower()

    # A missing artifact never gets a silent resume into it: the path forward
    # re-enters through the vault instead of linking the missing artifact.
    missing = _render(
        orientation=_orientation_payload(
            leave_status="artifact_missing", gap=_GAP_FULL_MIST
        )
    )
    missing_card = _reentry_card(missing)
    assert 'data-guard-held="true"' in missing_card
    assert "missing" in missing_card.lower()
    assert "Nothing was mutated" in missing_card
    assert 'data-intent="entry.resume"' not in missing_card
    assert "/workspace?note_path=Notes%2Fresume.md" not in missing_card
    assert 'data-testid="reentry-resume-reenter"' in missing_card
    assert "error" not in missing_card.lower()


# ---------------------------------------------------------------------------
# AC: display budget — 3 visible per collection; expansion ≤ server caps 8/8/5
# ---------------------------------------------------------------------------


def test_display_budget_caps_visible_items() -> None:
    html = _render(
        orientation=_orientation_payload(
            gap=_GAP_LONG_MIST,
            open_loops=10,
            notable_changes=10,
            resurface_candidates=7,
        )
    )

    # Default 3 visible items per collection.
    assert html.count('data-testid="workspace-orientation-open-loop"') == 3
    assert html.count('data-testid="workspace-orientation-notable-change"') == 3
    assert html.count('data-testid="workspace-orientation-resurface-candidate"') == 3
    # The delta strip honors the same default budget.
    strip = html.split('data-region="delta-strip"', 1)[1].split("</div>", 1)[0]
    assert strip.count('data-testid="reentry-delta-item"') <= 3

    # Deliberate expansion exists but never exceeds the server caps (8/8/5):
    # 10 declared open loops → at most 8 rendered in total, etc.
    assert (
        html.count('data-testid="workspace-orientation-open-loop"')
        + html.count('data-testid="workspace-orientation-open-loop-overflow"')
        == 8
    )
    assert (
        html.count('data-testid="workspace-orientation-notable-change"')
        + html.count('data-testid="workspace-orientation-notable-change-overflow"')
        == 8
    )
    assert (
        html.count('data-testid="workspace-orientation-resurface-candidate"')
        + html.count('data-testid="workspace-orientation-resurface-overflow-candidate"')
        == 5
    )
    # Items beyond the cap are never rendered.
    assert "Open loop label 8" not in html
    assert "Open loop label 9" not in html
    assert "Notable change label 9" not in html
    assert "Resurface candidate 6" not in html

    # The card keeps counts-not-enumerations regardless of collection size.
    card = _reentry_card(html)
    assert "8 open loops · 1 staged" in card


# ---------------------------------------------------------------------------
# AC: residual ambient layer persists into shell_active after resume
# ---------------------------------------------------------------------------


def test_residual_ambient_layer_persists_after_resume() -> None:
    # entry.resume opens the document anchor: the workspace page renders in
    # shell_active with the residual ambient layer present.
    html = _render(note_path="Notes/note.md", fields=_workspace_fields())
    assert 'data-entry-state="shell_active"' in html

    assert 'data-region="reentry-ambient"' in html
    ambient = html.split('data-region="reentry-ambient"', 1)[1].split("</aside>", 1)[0]
    # Caret echo at the stop point and marginalia dots persist.
    assert 'data-testid="reentry-caret-echo"' in ambient
    assert ambient.count('data-testid="reentry-marginalia-dot"') >= 1
    # Dismissal never erases unresolved tension.
    assert 'data-unresolved-tension="preserved"' in ambient

    # The residual layer carries no notification/urgency semantics.
    lowered = ambient.lower()
    for forbidden in ("notification", "badge", "urgent"):
        assert forbidden not in lowered, forbidden
