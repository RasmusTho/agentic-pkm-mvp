"""Panel rail resting-state quieting (#3362, parent #3360).

DESIGN_AUDIT.md (`companion-ui/design_handoff/2026-07-07-uat-design-audit/
DESIGN_AUDIT.md`) §2.1-§2.3 / §6 / top-10 #3 — the worst calm offender: at
rest, with zero proposals and nothing happening, the right panel rail used to
stack ten labelled status idioms (`PANEL · IDLE`, boxed "No active Panel
proposal", `ambient · peripheral`, `Companion · active`, a canvas-disabled
paragraph, `FIND unavailable because no backend candidate payload…`, a 5-line
amber `RESURFACE degraded` block, an ISO `commitments ok · 0 active · as of
…` timestamp) and ~40 words of machine prose to say "nothing is happening".

This slice collapses each idle lane to ONE dim line — label + one-word
state, matching redesigns.html section 1 ("Panel rail — at rest"):
`Suggestions — none`, `Recall — nothing open`, `Search — nothing yet`,
`Commitments — none`. A lane expands only when it has content (a staged
proposal, an actionable degraded state); a non-actionable degraded Resurface
folds into the ONE calm posture note line instead of an amber warning card.

SSR markup/contract tests against the rendered dev-page HTML.
"""

from __future__ import annotations

import re

from companion_ui.workspace.serve_dev_page import render_index_html

_REMOVED_STRINGS = (
    "ambient · peripheral",
    "Companion &middot; active",
    "No active Panel proposal",
    "backend candidate payload",
)


def _fields(**overrides) -> dict:
    base = {
        "title": "Note Title",
        "note_path": "Notes/note.md",
        "artifact_id": "art-123",
        "artifact_kind": "human_note",
        "artifact_identity_source": "frontmatter.uuid",
        "artifact_identity_state": "resolved",
        "artifact_companion_of": None,
        "artifact_owns_identity": True,
        "content_hash": "sha256-aaa",
        "body": "# Note\n\nBody content here.",
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
        "panel_last_response": {},
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
        "commitments_surface": {"state": "empty", "as_of": "2026-07-07T20:28:44+00:00"},
        "suggestion_state": "idle",
        "suggestion_composer_enabled": True,
        "is_production_ui": False,
        "dev_page_label": "dev/staging",
        "workspace_loaded_at": None,
    }
    base.update(overrides)
    return base


def _html(**overrides) -> str:
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/note.md",
        fields=_fields(**overrides),
    )


def _rail(html: str) -> str:
    start = html.index('data-testid="workspace-agent-rail"')
    end = html.index("</aside>", start)
    return html[start:end]


# ---------------------------------------------------------------------------
# AC1 — an all-idle fixture renders each lane as a single line.
# ---------------------------------------------------------------------------


def test_idle_rail_is_single_line_per_lane() -> None:
    rail = _rail(_html())

    # The quiet resting block is present, one line per lane, no accordion.
    assert 'data-testid="workspace-rail-resting"' in rail
    assert 'data-testid="rail-resting-suggestions"' in rail
    assert 'data-testid="rail-resting-recall"' in rail
    assert 'data-testid="rail-resting-search"' in rail
    assert 'data-testid="rail-resting-commitments"' in rail

    # No <details>-boxed idle cards (the old "Companion details" disclosure).
    assert "<details" not in rail
    assert "rail-idle-details" not in rail

    # No explanatory paragraphs from the old per-lane idle copy.
    assert "Find is unavailable" not in rail
    assert "Reorient is available, but no orientation payload" not in rail
    assert "Suggestions are idle." not in rail
    assert "Canvas editing is currently disabled" not in rail

    # Review finding 2 — the fixture is canvas_enabled=True with NO active
    # session: none of the canvas idle prose renders at rest.
    assert "No active Canvas session" not in rail
    assert "Body edit composer unavailable" not in rail
    assert "Canvas action is unavailable" not in rail
    assert "No active Canvas session to close" not in rail
    assert "No undo is available" not in rail

    # The old consolidated empty-state box is gone too (superseded by the
    # per-lane resting lines).
    assert "No active session" not in rail
    assert 'data-testid="workspace-rail-empty-state"' not in rail

    # None of the removed strings (audit §6 copy table).
    for token in _REMOVED_STRINGS:
        assert token not in rail, f"removed string {token!r} still present"

    # The exact resting words from redesigns.html section 1.
    suggestions_line = re.search(
        r'data-testid="rail-resting-suggestions"[^>]*>.*?</div>', rail, re.DOTALL
    )
    assert suggestions_line and "none" in suggestions_line.group()
    recall_line = re.search(
        r'data-testid="rail-resting-recall"[^>]*>.*?</div>', rail, re.DOTALL
    )
    assert recall_line and "nothing open" in recall_line.group()
    search_line = re.search(
        r'data-testid="rail-resting-search"[^>]*>.*?</div>', rail, re.DOTALL
    )
    assert search_line and "nothing yet" in search_line.group()
    commitments_line = re.search(
        r'data-testid="rail-resting-commitments"[^>]*>.*?</div>', rail, re.DOTALL
    )
    assert commitments_line and "none" in commitments_line.group()


# ---------------------------------------------------------------------------
# AC2 — no ISO-8601 timestamp appears in the visible text of the resting rail.
# ---------------------------------------------------------------------------

_ISO_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")


def test_idle_rail_has_no_iso_timestamp() -> None:
    rail = _rail(_html())
    assert not _ISO_TIMESTAMP_RE.search(rail), "resting rail leaks an ISO-8601 timestamp"
    # Explicitly: the fixture's commitments as_of timestamp never appears.
    assert "2026-07-07T20:28:44" not in rail
    commitments_line = re.search(
        r'data-testid="rail-resting-commitments"[^>]*>.*?</div>', rail, re.DOTALL
    )
    assert commitments_line
    assert "none" in commitments_line.group()
    assert "as of" not in commitments_line.group().lower()


# ---------------------------------------------------------------------------
# AC3 — a lane expands only with content; non-actionable degraded Resurface
# renders exactly one calm posture note line.
# ---------------------------------------------------------------------------


def test_lane_expands_only_with_content() -> None:
    # (a) Staged proposals still render the full proposal card content.
    proposals = [
        {
            "proposal_id": "p1",
            "description": "Add a link",
            "action_mode": "confirm_required",
            "status": "staged",
        }
    ]
    populated_rail = _rail(
        _html(
            panel_state="proposals-staged",
            panel_proposal_count=1,
            panel_proposals=proposals,
        )
    )
    # The populated Suggestions lane expands to its full card (its resting
    # line is gone); the collapse is per-lane, so idle sibling lanes still
    # rest as dim lines alongside the expanded one.
    assert 'data-testid="rail-resting-suggestions"' not in populated_rail
    assert 'data-testid="workspace-panel-proposal-row"' in populated_rail
    assert "Add a link" in populated_rail
    assert 'data-testid="rail-resting-recall"' in populated_rail
    assert 'data-testid="rail-resting-search"' in populated_rail
    assert 'data-testid="rail-resting-commitments"' in populated_rail

    # (b) A non-actionable degraded Resurface (guard-reported degraded, no
    # candidates) renders exactly one calm posture note line — no amber
    # warning card, no other rail-resting note.
    degraded_rail = _rail(_html(guard_degraded=True))
    assert 'data-testid="workspace-rail-resting"' in degraded_rail
    assert degraded_rail.count('data-testid="workspace-rail-resting-note"') == 1
    assert "Resurfacing is paused while the vault reconnects." in degraded_rail
    assert "resurface-degraded-state" not in degraded_rail
    assert "runtime reported degraded guard state" not in degraded_rail
    assert "&#9888;" not in degraded_rail  # no warning-triangle glyph
    assert "⚠" not in degraded_rail


# ---------------------------------------------------------------------------
# Review finding 1 — mixed state: one lane populated, the others idle. The
# populated lane keeps its full content; the idle lanes rest as dim lines;
# none of the removed strings re-appear.
# ---------------------------------------------------------------------------


def test_mixed_state_populated_lane_does_not_reexpand_idle_lanes() -> None:
    rail = _rail(
        _html(
            commitments_surface={
                "state": "populated",
                "next_action": [{"summary": "Reply to Anna", "commitment_id": "c-anna"}],
                "review_cycle": [],
                "as_of": "2026-06-22T10:00:00Z",
            }
        )
    )
    # The populated Commitments lane renders full content...
    assert 'data-testid="commitments-mode"' in rail
    assert "Reply to Anna" in rail
    assert 'data-testid="rail-resting-commitments"' not in rail
    # ...the idle sibling lanes rest as dim lines...
    assert 'data-testid="rail-resting-suggestions"' in rail
    assert 'data-testid="rail-resting-recall"' in rail
    assert 'data-testid="rail-resting-search"' in rail
    # ...and none of the removed idle idioms leak back in via the sibling.
    for token in _REMOVED_STRINGS:
        assert token not in rail, f"removed string {token!r} re-appeared in mixed state"
    assert "Suggestions are idle." not in rail
    assert "Find is unavailable" not in rail
    assert 'data-testid="workspace-panel-column-header"' not in rail
    assert 'data-testid="workspace-rail-posture"' not in rail


# ---------------------------------------------------------------------------
# Review finding 3 — a safety warning never co-renders with a contradictory
# "nothing pending" empty-state.
# ---------------------------------------------------------------------------


def test_safety_warning_never_coexists_with_empty_state() -> None:
    rail = _rail(_html(guard_writeguard_status="blocked"))
    assert 'data-testid="workspace-guard-indicator"' in rail
    assert "WriteGuard blocked" in rail
    # The contradictory consolidated empty-state box must not co-render.
    assert 'data-testid="workspace-rail-empty-state"' not in rail
    assert "No active session" not in rail
    assert "Nothing pending" not in rail
    # The posture chip says needs-attention, not idle reassurance.
    assert "needs attention" in rail


# ---------------------------------------------------------------------------
# Review finding 4 — the resting markup is styled: the page carries the
# .rail-resting* rules (one line per lane, dim tones, thin separators).
# ---------------------------------------------------------------------------


def test_rail_resting_styles_present() -> None:
    html = _html()
    assert ".rail-resting-line {" in html
    assert ".rail-resting-label {" in html
    assert ".rail-resting-state {" in html
    assert ".rail-resting-note {" in html
    # The state word is the dim mono token from the mockup.
    line_rule = html.split(".rail-resting-state {", 1)[1].split("}", 1)[0]
    assert "var(--fg-3)" in line_rule
    assert "var(--font-mono)" in line_rule
    # The dead pre-#3362 disclosure styles are gone.
    assert ".rail-idle-details" not in html
    assert ".rail-idle-summary" not in html
