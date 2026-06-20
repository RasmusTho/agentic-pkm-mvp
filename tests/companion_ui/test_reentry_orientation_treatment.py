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
    assert card.count("Resume plan") == 1
    assert 'data-testid="reentry-stop-link"' in card
    assert "Open artifact" in card

    whisper = html.split('data-region="whisper-column"', 1)[1].split("</aside>", 1)[0]
    assert whisper.count("Resume plan") == 1

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
