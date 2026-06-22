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
    recents_anchor: dict[str, str] | None = None,
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
    payload: dict[str, Any] = {
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
    if recents_anchor is not None:
        payload["recents_anchor"] = recents_anchor
    return payload


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


def test_reentry_orientation_regions_do_not_duplicate_heading_and_body_without_leave_label() -> None:
    payload = _orientation_payload(gap=_GAP_LONG_MIST)
    assert payload["leave_point"] is not None
    payload["leave_point"].pop("label", None)
    payload["open_loops"][0]["label"] = payload["open_loops"][0]["artifact_ref"]["title"]
    payload["notable_changes"][0]["label"] = payload["notable_changes"][0]["artifact_ref"][
        "title"
    ]
    payload["resurface"]["candidates"][0]["label"] = payload["resurface"]["candidates"][0][
        "artifact_ref"
    ]["title"]

    html = _render(orientation=payload)

    leave_section = html.split('data-testid="workspace-orientation-leave-point"', 1)[1].split(
        "</section>", 1
    )[0]
    assert leave_section.count("Resume plan") == 1
    assert 'data-testid="workspace-orientation-leave-link"' in leave_section
    assert "Open artifact" in leave_section

    card = _reentry_card(html)
    # The 'doing' question now shows "Where you left off" (not the artifact title)
    # and the 'stopped' artifact link shows the title directly (not suppressed).
    assert "Where you left off" in card
    assert 'data-testid="reentry-stop-link"' in card
    assert card.count("Resume plan") == 1  # title in stopped link, not in doing body

    whisper = html.split('data-region="whisper-column"', 1)[1].split("</aside>", 1)[0]
    assert "Where you left off" in whisper
    assert whisper.count("Resume plan") == 0  # title no longer repeated in whisper doing slot

    open_loop = html.split('data-testid="workspace-orientation-open-loop"', 1)[1].split(
        "</article>", 1
    )[0]
    assert open_loop.count("Loop 0") == 1
    assert 'data-testid="workspace-orientation-open-loop-link"' in open_loop
    assert "Open artifact" in open_loop

    notable_change = html.split(
        'data-testid="workspace-orientation-notable-change"', 1
    )[1].split("</article>", 1)[0]
    assert notable_change.count("Change 0") == 1
    assert 'data-testid="workspace-orientation-notable-change-link"' in notable_change
    assert "Open artifact" in notable_change

    resurface = html.split(
        'data-testid="workspace-orientation-resurface-candidate"', 1
    )[1].split("</article>", 1)[0]
    assert resurface.count("Candidate 0") == 1
    assert 'data-testid="workspace-orientation-resurface-link"' in resurface
    assert "Open artifact" in resurface

    soft_payload = _orientation_payload(gap=_GAP_SOFT_MIST)
    assert soft_payload["leave_point"] is not None
    soft_payload["leave_point"].pop("label", None)
    soft_html = _render(orientation=soft_payload)
    peripheral = soft_html.split('data-region="reentry-peripheral-line"', 1)[1].split(
        "</p>", 1
    )[0]
    assert peripheral.count("Resume plan") == 1


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

    # Deliberate inspect affordance always emits the declared entry/shell
    # intent. Even with zero candidates, the owner vocabulary stays
    # `memory.open`; the href remains a no-JS fallback to the orientation
    # section and is not a separate entry intent.
    assert 'data-testid="reentry-inspect"' in card
    assert 'data-intent="memory.open"' in card
    assert 'data-memory-candidate-count="0"' in card
    assert 'data-intent="open_loops.inspect"' not in card
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


def test_long_mist_renders_four_fixed_questions_with_counts() -> None:
    payload = _orientation_payload(gap=_GAP_LONG_MIST)
    payload["memory"] = {"pending_candidate_count": 4}

    html = _render(orientation=payload)

    card = _reentry_card(html)

    assert 'data-reentry-treatment="long_mist"' in card
    for question in ("doing", "stopped", "unresolved", "changed"):
        assert f'data-reentry-question="{question}"' in card, question
    assert len(re.findall(r'data-reentry-question="', card)) == 4

    unresolved = card.split('data-testid="reentry-unresolved-counts"', 1)[1].split(
        "</span>", 1
    )[0]
    unresolved_text = re.sub(r"\s+", " ", unresolved)
    assert "3 open loops · 1 staged · 4 memory candidates" in unresolved_text
    assert 'data-memory-candidate-count="4"' in unresolved
    for idx in range(3):
        assert f"Open loop label {idx}" not in card

    changed = card.split('data-testid="reentry-changed-count"', 1)[1].split(
        "</span>", 1
    )[0]
    assert "2 changes while you were away" in re.sub(r"\s+", " ", changed)
    assert "Notable change label 0" not in changed

    whisper = html.split('data-region="whisper-column"', 1)[1].split("</aside>", 1)[0]
    whisper_text = re.sub(r"\s+", " ", whisper)
    assert "3 open loops · 1 staged" in whisper_text
    assert "2 deltas since you left" in whisper_text
    assert "1 why-now candidates" in whisper_text


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

    # Start fresh must remove the card and its sibling long-mist cues before
    # declaring shell_active, so no orienting whisper column is left behind.
    dismiss = re.search(r"function entryDismiss\(control\) \{(.*?)\n  \}\n  </script>", html, re.S)
    assert dismiss, "entry.dismiss handler must render"
    body = dismiss.group(1)
    assert "[data-region=delta-strip], [data-region=whisper-column]" in body
    assert "siblingCues[i].remove()" in body
    assert "data-entry-state', 'shell_active'" in body


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
    # CUIDR-01: the banner names the missing source in humanised copy, never the
    # raw runtime enum (resurfacing_source_unavailable).
    assert "Orientation source unavailable" in banner
    assert "resurfacing_source_unavailable" not in banner

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


# ---------------------------------------------------------------------------
# AC2 (#2171): cold_start threshold body — inline verb-line, vault chip,
# eyebrow/headline variants, provenance line
# ---------------------------------------------------------------------------


def test_cold_start_threshold_renders_inline_intent_verbs() -> None:
    """AC2 verify: verb-line is inline affordances, not a button/card grid.

    Three intent affordances map 1:1 onto vault.open / capture.open / map.open
    inside a data-region="cold-start-verbs" element.  The element is inline
    prose — never a grid, card, or button.
    """
    # First-contact variant (leave_point absent)
    first_contact = _render(orientation=_orientation_payload(leave_status="absent"))
    # Cold-trajectory variant (gap > 14 d)
    cold_traj = _render(orientation=_orientation_payload(gap=_GAP_COLD))

    for html, label in [(first_contact, "first-contact"), (cold_traj, "cold-trajectory")]:
        # Threshold container is present.
        assert 'data-region="cold-start-threshold"' in html, label

        # Verb-line is present.
        assert 'data-region="cold-start-verbs"' in html, label

        # All three intent affordances are present.
        assert 'data-intent="vault.open"' in html, label
        assert 'data-intent="capture.open"' in html, label
        assert 'data-intent="map.open"' in html, label

        # Verb text labels are present.
        assert "Find a note" in html, label
        assert "Jot something down" in html, label
        assert "See the map" in html, label

        # No "Reorient" verb on cold_start.
        assert "Reorient" not in html, label

        # Verb-line is NOT a button/card grid — no grid wrapper around the verbs.
        verb_region = html.split('data-region="cold-start-verbs"', 1)[1].split("</p>", 1)[0]
        assert "<button" not in verb_region, label
        assert 'class="orientation-grid"' not in verb_region, label
        assert 'class="orientation-column"' not in verb_region, label


def test_cold_start_vault_open_targets_rendered_vault_browser() -> None:
    """#2308: cold-start vault.open targets the rendered orientation browser."""
    html = _render(
        orientation=_orientation_payload(leave_status="absent"),
        orientation_vault_browser=_vault_browser_payload(),
    )

    assert 'data-entry-state="cold_start"' in html
    assert 'id="workspace-orientation-vault-entry"' in html
    verb_region = html.split('data-region="cold-start-verbs"', 1)[1].split("</p>", 1)[0]
    assert 'data-intent="vault.open"' in verb_region
    assert 'href="#workspace-orientation-vault-entry"' in verb_region
    assert "vaultBrowser.focus(); return false;" in verb_region
    assert "window.vaultBrowser = window.vaultBrowser || {};" in html
    assert "window.vaultBrowser.focus = focusOrientationVaultBrowser;" in html
    assert "data-browse-focused" in html
    assert 'data-testid="vault-browser-overlay"' not in html


def test_cold_start_vault_open_focus_skips_hidden_vault_rows() -> None:
    """#2308: hidden companion rows must not steal vault.open focus."""
    vault_browser = _vault_browser_payload()
    vault_browser["notes"] = [
        {
            "note_path": "System/companion.md",
            "title": "System companion",
            "zone": "System",
            "kind": "companion_note",
            "frontmatter_valid": True,
            "missing_required_fields": [],
        },
        {
            "note_path": "Notes/visible.md",
            "title": "Visible note",
            "zone": "Notes",
            "kind": "human_note",
            "frontmatter_valid": True,
            "missing_required_fields": [],
        },
    ]
    html = _render(
        orientation=_orientation_payload(leave_status="absent"),
        orientation_vault_browser=vault_browser,
    )

    assert 'data-entry-state="cold_start"' in html
    assert 'data-kind="companion_note" data-companion="true" data-nav-visible="false" hidden' in html
    assert "function firstVisibleFocusTarget(selector)" in html
    assert "closest('[hidden]')" in html
    assert "firstVisibleFocusTarget('[data-testid=\"workspace-vault-browser\"] summary')" in html
    assert "firstVisibleFocusTarget('[data-testid=\"workspace-vault-browser-note-link\"]')" in html


def test_cold_start_threshold_eyebrow_headline_variants() -> None:
    """Eyebrow and headline differ for first-contact vs cold-trajectory."""
    first_contact = _render(orientation=_orientation_payload(leave_status="absent"))
    cold_traj = _render(orientation=_orientation_payload(gap=_GAP_COLD))

    # First contact variant.
    assert "First contact" in first_contact
    assert "Nothing is open yet." in first_contact

    # Cold trajectory variant.
    assert "Returning after a while" in cold_traj
    assert "Re-entry is through the vault." in cold_traj

    # Variants are mutually exclusive (correct content in each page).
    assert "Returning after a while" not in first_contact
    assert "First contact" not in cold_traj


def test_cold_start_threshold_vault_chip() -> None:
    """Vault chip renders the server-declared vault_id."""
    html = _render(orientation=_orientation_payload(leave_status="absent"))

    assert "cold-start-vault-chip" in html
    assert "dev-vault" in html  # from scope.vault_id in _orientation_payload fixture


def test_cold_start_threshold_provenance_line() -> None:
    """Provenance line content matches the variant."""
    first_contact = _render(orientation=_orientation_payload(leave_status="absent"))
    cold_traj = _render(orientation=_orientation_payload(gap=_GAP_COLD))

    assert "leave_point: absent" in first_contact
    assert "read-only · server-declared" in first_contact

    assert "trajectory: cold" in cold_traj
    assert "leave_point: present" in cold_traj
    assert "read-only · server-declared" in cold_traj


def test_cold_start_provenance_omits_present_when_leave_point_absent() -> None:
    """#2309: the "Returning after a while" copy is also used for a non-empty
    vault whose leave_point is *absent* (recents_anchor present, no leave
    point). The provenance must declare the real (absent) status, never
    fabricate "present"."""
    html = _render(
        orientation=_orientation_payload(
            leave_status=None,  # leave_point absent
            recents_anchor={"note_path": "Inbox/inbox.md", "display_label": "inbox"},
        )
    )
    # Returning copy is used (non-empty vault), not first-contact.
    assert "Returning after a while" in html
    assert "Re-entry is through the vault." in html
    # Provenance reflects the actual declared leave_point status — not "present".
    assert "leave_point: absent" in html
    assert "leave_point: present" not in html


# ---------------------------------------------------------------------------
# AC (#2176): recents-anchor sub-affordance on the cold_start threshold
# ---------------------------------------------------------------------------


def test_cold_start_recents_anchor_renders_when_present_and_omits_when_absent() -> None:
    """AC: recents-anchor sub-affordance renders when present; omits when absent.

    When the server declares recents_anchor on the orientation payload the
    cold_start threshold must render a labeled "Open your most recent note"
    link routing via /workspace?note_path=…  When the field is absent the
    link must not appear and the threshold must still render correctly.
    """
    anchor = {"note_path": "Notes/recent.md", "display_label": "My Recent Note"}

    # --- Present case ---
    with_anchor = _render(
        orientation=_orientation_payload(leave_status="absent", recents_anchor=anchor)
    )

    # The labeled sub-affordance must be present.
    assert "data-testid=\"cold-start-recents-anchor\"" in with_anchor
    assert "Open your most recent note" in with_anchor
    assert "My Recent Note" in with_anchor
    # Must route via /workspace?note_path= (URL-encoded).
    assert "/workspace?note_path=" in with_anchor
    assert "Notes%2Frecent.md" in with_anchor
    # Must carry data-intent="recents.open".
    assert 'data-intent="recents.open"' in with_anchor
    # The threshold itself must still render correctly.
    assert 'data-region="cold-start-threshold"' in with_anchor
    assert 'data-region="cold-start-verbs"' in with_anchor
    assert 'data-intent="vault.open"' in with_anchor
    # NEVER auto-opens: no redirect, no location.href, no window.open on mount.
    assert "location.href" not in with_anchor.split('data-intent="recents.open"')[1].split("</a>")[0]

    # Cold-trajectory variant also renders the anchor.
    cold_with_anchor = _render(
        orientation=_orientation_payload(gap=_GAP_COLD, recents_anchor=anchor)
    )
    assert 'data-testid="cold-start-recents-anchor"' in cold_with_anchor

    # --- Absent case ---
    without_anchor = _render(orientation=_orientation_payload(leave_status="absent"))

    assert "data-testid=\"cold-start-recents-anchor\"" not in without_anchor
    assert "Open your most recent note" not in without_anchor
    # Threshold still renders correctly without the anchor.
    assert 'data-region="cold-start-threshold"' in without_anchor
    assert 'data-region="cold-start-verbs"' in without_anchor
    assert 'data-intent="vault.open"' in without_anchor


def test_recents_anchor_uses_server_payload_without_ui_filesystem_probe() -> None:
    """AC: UI renders server-declared field; no client-side vault mtime probe.

    The recents_anchor in the payload is the single source of truth.  The
    rendered page must carry exactly the note_path and display_label from the
    server field.  A different payload with a different path must render that
    different path — proving the renderer consumes the server fact, not a
    local filesystem mtime scan.
    """
    anchor_a = {"note_path": "Projects/alpha.md", "display_label": "Alpha Project"}
    anchor_b = {"note_path": "Archive/beta.md", "display_label": "Beta Archive"}

    html_a = _render(
        orientation=_orientation_payload(leave_status="absent", recents_anchor=anchor_a)
    )
    html_b = _render(
        orientation=_orientation_payload(leave_status="absent", recents_anchor=anchor_b)
    )

    # Each render carries exactly the server-declared path, not the other.
    assert "Projects%2Falpha.md" in html_a
    assert "Alpha Project" in html_a
    assert "Projects%2Falpha.md" not in html_b
    assert "Alpha Project" not in html_b

    assert "Archive%2Fbeta.md" in html_b
    assert "Beta Archive" in html_b
    assert "Archive%2Fbeta.md" not in html_a
    assert "Beta Archive" not in html_a

    # No filesystem I/O marker: the rendered link text comes from the server
    # display_label, not from any local path computation (confirmed by the
    # two renders above differing only by payload, not by worktree state).


# ---------------------------------------------------------------------------
# AC (#2240-a,b): vault card de-dupes "read-only" and uses resolved vault_id
# ---------------------------------------------------------------------------


def _vault_browser_payload(vault_name: str = "Niflheim") -> dict:
    """Minimal vault_browser payload for cold_start orientation rendering."""
    return {
        "notes": [],
        "query": "",
        "total_notes": 0,
        "filtered_notes": 0,
        "read_only": True,
        "identity_available": True,
        "vault_identity": {
            "vault_name": vault_name,
            "channel": "local",
            "provenance": "resolved",
        },
        "active_filters": {},
        "pagination": {},
    }


def test_cold_start_vault_card_dedupes_readonly_and_uses_resolved_vault_id() -> None:
    """#2240-a,b: vault card shows read-only exactly once; vault_id matches chip.

    The vault_browser badge already shows "read-only"; the calm_provenance string
    must not repeat it.  The vault card identity must resolve from scope.vault_id
    (same source as the cold_start chip), not from vault_browser.vault_identity.
    """
    payload = _orientation_payload(leave_status="absent")
    # scope.vault_id = "dev-vault" (from _orientation_payload fixture)
    vault_browser = _vault_browser_payload(vault_name="SomethingElse")

    html = _render(orientation=payload, orientation_vault_browser=vault_browser)

    # Only cold_start surfaces the threshold.
    assert 'data-region="cold-start-threshold"' in html

    # --- AC 2240-a: "read-only" must not appear in the provenance string ---
    # The badge (data-testid=workspace-vault-browser-read-only) shows "read-only".
    # The provenance calm label must NOT also contain "read-only" (de-duplication).
    assert 'data-testid="workspace-vault-browser"' in html
    provenance_block = html.split('data-testid="workspace-vault-browser-provenance"', 1)[1].split("</span>", 1)[0]
    assert "read-only" not in provenance_block, (
        "Provenance string must not repeat 'read-only' — badge already shows it"
    )
    # Provenance should indicate fallback source without duplicating the badge text.
    assert "fallback" in provenance_block or "filesystem index" in provenance_block, (
        f"Provenance should indicate fallback source, got: {provenance_block!r}"
    )

    # --- AC 2240-b: vault card identity matches scope.vault_id (the chip source) ---
    # The cold_start chip shows "dev-vault" (from scope.vault_id).
    assert "dev-vault" in html  # chip still shows it
    # The vault browser identity label also resolves from scope.vault_id.
    identity_block = html.split('data-testid="workspace-vault-browser-active-identity"', 1)[1].split("</span>", 1)[0]
    assert "dev-vault" in identity_block, (
        f"Vault browser identity should use scope.vault_id='dev-vault', got: {identity_block!r}"
    )
    # Must NOT show the vault_browser.vault_identity value ("SomethingElse").
    assert "SomethingElse" not in identity_block


# ---------------------------------------------------------------------------
# AC (#2240-c): inline capture input is not truncated
# ---------------------------------------------------------------------------


def test_cold_start_inline_capture_not_truncated() -> None:
    """#2240-c: inline capture input has full-width CSS so placeholder is readable.

    The input must carry width:100% (or equivalent) styling so the placeholder
    'Leave a note for future-you…' is not truncated on the cold_start surface.
    """
    html = _render(orientation=_orientation_payload(leave_status="absent"))

    assert 'data-testid="cold-start-capture-input"' in html
    assert 'data-region="cold-start-capture"' in html

    # The placeholder text must be present verbatim (not truncated at render time).
    assert "Leave a note for future-you" in html

    # CSS for the input must declare full-width treatment.
    assert ".cold-start-capture-input" in html
    # Locate the CSS rule for .cold-start-capture-input
    css_rule = html.split(".cold-start-capture-input", 1)[1].split("}", 1)[0]
    assert "width" in css_rule, (
        "cold-start-capture-input CSS must declare a width so the placeholder is not truncated"
    )
    # width must be 100% (full-width, unadorned inline line per design item 4).
    assert "100%" in css_rule, (
        "cold-start-capture-input must be width:100% to render the full placeholder"
    )


# ---------------------------------------------------------------------------
# AC (#2243): returning copy when vault is non-empty (recents_anchor present)
# ---------------------------------------------------------------------------


def _with_recents_anchor(
    payload: dict,
    note_path: str = "Notes/latest.md",
    display_label: str = "Latest note",
) -> dict:
    """Attach a server-declared recents_anchor to the orientation payload."""
    import copy
    p = copy.deepcopy(payload)
    p["recents_anchor"] = {
        "note_path": note_path,
        "display_label": display_label,
    }
    return p


def test_cold_start_headline_uses_returning_copy_when_vault_nonempty() -> None:
    """#2243: recents_anchor present → returning copy, even with absent leave_point.

    'First contact / Nothing is open yet.' is reserved for a genuinely empty vault
    (no recents_anchor AND absent/no leave_point).  A non-empty vault (recents_anchor
    present) must use 'Returning after a while / Re-entry is through the vault.' even
    when leave_point.status == 'absent'.
    """
    # Case 1: leave_point absent AND recents_anchor present → non-empty vault → returning copy
    payload_absent_lp = _with_recents_anchor(
        _orientation_payload(leave_status="absent")
    )
    html_absent = _render(orientation=payload_absent_lp)
    assert "Returning after a while" in html_absent, (
        "Non-empty vault (recents_anchor present) with absent leave_point must show returning copy"
    )
    assert "Re-entry is through the vault." in html_absent
    assert "First contact" not in html_absent, (
        "First contact copy must be reserved for genuinely empty vault"
    )
    assert "Nothing is open yet." not in html_absent

    # Case 2: no leave_point at all AND recents_anchor present → non-empty vault → returning copy
    payload_no_lp = _with_recents_anchor(
        _orientation_payload(leave_status=None)
    )
    html_no_lp = _render(orientation=payload_no_lp)
    assert "Returning after a while" in html_no_lp, (
        "Non-empty vault (recents_anchor present) with no leave_point must show returning copy"
    )
    assert "First contact" not in html_no_lp

    # Case 3: absent leave_point AND no recents_anchor → genuinely empty vault → first contact copy
    payload_empty_vault = _orientation_payload(leave_status="absent")
    # Ensure no recents_anchor
    payload_empty_vault.pop("recents_anchor", None)
    html_empty = _render(orientation=payload_empty_vault)
    assert "First contact" in html_empty, (
        "Empty vault (no recents_anchor + absent leave_point) must show first contact copy"
    )
    assert "Nothing is open yet." in html_empty
    assert "Returning after a while" not in html_empty

    # Case 4: cold trajectory (>14d) with leave_point present → always returning (unchanged)
    payload_cold_traj = _orientation_payload(gap=_GAP_COLD)
    html_cold = _render(orientation=payload_cold_traj)
    assert "Returning after a while" in html_cold
    assert "First contact" not in html_cold


# ---------------------------------------------------------------------------
# AC (#2241): re-entry card heading must not duplicate artifact-link body text
# ---------------------------------------------------------------------------


def test_reentry_card_heading_not_duplicated_with_body() -> None:
    """The 'doing' question body must not equal the artifact-link body text.

    When the v1 leave_point has no top-level ``label`` field,
    ``_reentry_leave_label`` previously fell through to ``artifact.get("title")``,
    making the 'doing' question body identical to the artifact title that would
    appear in the 'stopped' artifact link.  The fix must derive a distinct
    human-readable heading (e.g. "Where you left off") instead of repeating
    the title.

    Authority: issue #2241.
    """
    payload = _orientation_payload(gap=_GAP_FULL_MIST)
    assert payload["leave_point"] is not None
    # v1 contract: no top-level label field
    payload["leave_point"].pop("label", None)
    artifact_title = payload["leave_point"]["artifact_ref"]["title"]  # "Resume plan"

    html = _render(orientation=payload)
    card = _reentry_card(html)

    # Extract the 'doing' question body text.
    doing_li = card.split('data-reentry-question="doing"', 1)[1].split("</li>", 1)[0]
    doing_body = doing_li.split('class="reentry-q-body"', 1)[1].split("</span>", 1)[0]
    # Strip the leading '>' from the attribute close.
    doing_body_text = doing_body.lstrip(">").strip()

    # The 'doing' heading must NOT be the raw artifact title — the title
    # already surfaces as the artifact link in the 'stopped' question.
    assert doing_body_text != artifact_title, (
        f"re-entry card 'doing' body is identical to artifact title {artifact_title!r}; "
        "expected a distinct human-readable heading when leave.label is absent"
    )

    # The heading must be non-empty (a meaningful cue, not silent).
    assert doing_body_text, "re-entry card 'doing' body must not be empty"

    # The artifact link in the 'stopped' question must still display the title
    # (no longer suppressed to 'Open artifact' once the heading is distinct).
    stopped_li = card.split('data-reentry-question="stopped"', 1)[1].split("</li>", 1)[0]
    assert 'data-testid="reentry-stop-link"' in stopped_li

    # long_mist whisper column 'doing' text must also be distinct from the title.
    long_mist_payload = _orientation_payload(gap=_GAP_LONG_MIST)
    assert long_mist_payload["leave_point"] is not None
    long_mist_payload["leave_point"].pop("label", None)
    long_mist_html = _render(orientation=long_mist_payload)

    whisper = long_mist_html.split('data-region="whisper-column"', 1)[1].split("</aside>", 1)[0]
    whisper_doing = whisper.split('data-whisper-item="doing"', 1)[1].split("</div>", 1)[0]
    whisper_doing_text = whisper_doing.split('class="reentry-whisper-text"', 1)[1].split("</span>", 1)[0].lstrip(">").strip()
    assert whisper_doing_text != artifact_title, (
        f"whisper column 'doing' text is identical to artifact title {artifact_title!r}"
    )


# ---------------------------------------------------------------------------
# AC (#2248): cold_start omits notable-changes — suppression gate
# ---------------------------------------------------------------------------


def test_cold_start_omits_relocated_telemetry_regions() -> None:
    """#2248 AC1+AC3 + #2249 AC1 + #2250 AC1: notable-changes, resurface, and
    _reentry_counts aggregate absent on cold_start.

    The suppression gate ensures _render_orientation_notable_changes and
    _render_orientation_resurface output never appears in a cold_start render.
    The orienting long-mist delta strip is the only surface where
    notable-changes may appear; cold_start is not orienting.  Resurface
    candidates move to the shell resurface rail mode (not the orientation grid).

    #2250: _reentry_counts aggregates (open_loops, notable_changes,
    resurface_candidates, staged, memory_candidates counts) must not appear in
    cold_start as a grid cell, badge, or +N overflow.  The reentry card
    (data-region="reentry-card") is the only surface that renders these counts;
    cold_start is not orienting so the card never renders.  The explicit
    suppression assertion here is the enforcement gate: a future refactor that
    moves the _reentry_counts call site will trip this test before silent
    re-appearance on cold_start.

    Three cold_start variants are tested:
    - first contact (leave_point.status == "absent")
    - first contact (leave_point missing entirely)
    - cold trajectory (gap > 14 d)

    Supplies notable_changes=5 and resurface_candidates=5 to the payload so
    that both the main sections and overflow blocks would render if the gates
    were absent.
    """
    pages = [
        # First contact: leave_point.status absent, payload has notable_changes + resurface.
        _render(orientation=_orientation_payload(leave_status="absent", notable_changes=5, resurface_candidates=5)),
        # First contact: no leave point at all.
        _render(orientation=_orientation_payload(leave_status=None, notable_changes=5, resurface_candidates=5)),
        # Cold trajectory: gap beyond 14 days.
        _render(orientation=_orientation_payload(gap=_GAP_COLD, notable_changes=5, resurface_candidates=5)),
    ]
    for page in pages:
        # Main notable-changes section must not appear.
        assert 'data-testid="workspace-orientation-notable-changes"' not in page, (
            "cold_start must not render the notable-changes section"
        )
        # Individual change articles must not appear.
        assert 'data-testid="workspace-orientation-notable-change"' not in page, (
            "cold_start must not render individual notable-change articles"
        )
        # Overflow expand block must not appear.
        assert 'data-testid="workspace-orientation-notable-changes-expand"' not in page, (
            "cold_start must not render notable-changes overflow expansion"
        )
        # #2249 AC1: resurface candidates region must not appear on cold_start (#2171 gate).
        assert 'data-testid="workspace-orientation-resurface"' not in page, (
            "cold_start must not render the orientation resurface region"
        )
        assert 'data-testid="workspace-orientation-resurface-candidate"' not in page, (
            "cold_start must not render individual resurface candidates"
        )
        assert 'data-testid="workspace-orientation-resurface-overflow-candidate"' not in page, (
            "cold_start must not render the +N resurface overflow"
        )
        # #2246 AC4: governance grid and governance-counts row must not appear on cold_start.
        # The is_cold gate suppresses the orientation-column--rail (which holds the
        # governance grid); the governance-counts row must also be absent from the body
        # since the receipts modal is closed on the entry surface.
        assert 'data-testid="workspace-orientation-governance"' not in page, (
            "cold_start must not render the governance 3-cell grid"
        )
        assert 'data-testid="governance-counts-row"' not in page, (
            "cold_start must not render the governance-counts row outside pull-only surfaces"
        )
        # #2247 AC4: open-loops list/section and _render_orientation_open_loops output
        # must not appear on cold_start body (suppressed by the is_cold orientation grid
        # gate; confirmed by TELEMETRY_RELOCATION-03 cross-task invariant).
        assert 'data-testid="workspace-orientation-open-loops"' not in page, (
            "cold_start must not render the open-loops orientation section (#2247)"
        )
        assert 'data-testid="workspace-orientation-open-loop"' not in page, (
            "cold_start must not render individual open-loop articles (#2247)"
        )
        # The panel-rail-open-loops badge is only for shell_active (a note is open);
        # it must not appear on the cold_start orientation substrate.
        assert 'data-region="panel-rail-open-loops"' not in page, (
            "cold_start must not render the panel-rail-open-loops badge (#2247)"
        )
        # #2250 AC1: _reentry_counts aggregate must not appear on cold_start — not as a
        # grid cell, not as a badge, not as a +N overflow.  The reentry card
        # (data-region="reentry-card") is the sole renderer of these counts; since the card
        # is suppressed by the is_cold/shape gate, its count-bearing testid markers must
        # also be absent.  These assertions form the explicit suppression gate for the
        # _reentry_counts helper output so any future refactor that moves the call site
        # trips here before silent re-appearance on cold_start.
        assert 'data-region="reentry-card"' not in page, (
            "cold_start must not render the reentry-card (counts imply a trajectory cold_start cannot back) (#2250)"
        )
        assert 'data-testid="reentry-unresolved-counts"' not in page, (
            "cold_start must not render the _reentry_counts unresolved-counts display (#2250)"
        )
        assert 'data-testid="reentry-changed-count"' not in page, (
            "cold_start must not render the _reentry_counts changed-count display (#2250)"
        )
