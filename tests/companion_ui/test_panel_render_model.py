"""Tests for Panel render model / component shell (#1039).

Verifies:
- All 8 required Panel states are defined.
- Future-compatible states are named.
- Artifact-local anchoring is enforced.
- no-match and blocked are visible states with messages.
- State transitions are legal/illegal as expected.
- render_panel_state adapter produces sensible output per state.
- No dependency on Canvas Core or direct vault I/O.
"""

import pytest

from companion_ui.panel.render_model import (
    PANEL_STATES_REQUIRED,
    PANEL_STATES_FUTURE,
    PANEL_STATES_ALL,
    PanelRenderState,
    render_panel_state,
)


REQUIRED_STATES = [
    "idle",
    "running",
    "proposals-staged",
    "confirming",
    "executing",
    "receipt-displayed",
    "no-match",
    "blocked",
]

FUTURE_STATES = [
    "clarification-needed",
    "plan-staged",
    "capability-needed",
    "partial-complete",
]


class TestPanelStatesDefinition:
    def test_all_required_states_present(self) -> None:
        for state in REQUIRED_STATES:
            assert state in PANEL_STATES_REQUIRED, f"Required state missing: {state!r}"

    def test_future_compatible_states_present(self) -> None:
        for state in FUTURE_STATES:
            assert state in PANEL_STATES_FUTURE, f"Future state missing: {state!r}"

    def test_all_states_union(self) -> None:
        assert PANEL_STATES_REQUIRED.issubset(PANEL_STATES_ALL)
        assert PANEL_STATES_FUTURE.issubset(PANEL_STATES_ALL)


class TestPanelRenderStateArtifactAnchoring:
    def test_artifact_id_required(self) -> None:
        with pytest.raises(ValueError, match="artifact_id is required"):
            PanelRenderState(artifact_id="")

    def test_artifact_id_stored(self) -> None:
        s = PanelRenderState(artifact_id="note-123")
        assert s.artifact_id == "note-123"

    def test_default_state_is_idle(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        assert s.state == "idle"

    def test_unknown_state_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown Panel state"):
            PanelRenderState(artifact_id="note-a", state="nonexistent")


class TestPanelRenderStateTransitions:
    def test_idle_to_running(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        assert s.state == "running"

    def test_running_to_proposals_staged(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("proposals-staged")
        assert s.state == "proposals-staged"

    def test_proposals_staged_to_confirming(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("proposals-staged")
        s.transition("confirming")
        assert s.state == "confirming"

    def test_confirming_to_executing(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("proposals-staged")
        s.transition("confirming")
        s.transition("executing")
        assert s.state == "executing"

    def test_executing_to_receipt_displayed(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("proposals-staged")
        s.transition("confirming")
        s.transition("executing")
        s.transition("receipt-displayed")
        assert s.state == "receipt-displayed"

    def test_receipt_displayed_to_idle(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("proposals-staged")
        s.transition("confirming")
        s.transition("executing")
        s.transition("receipt-displayed")
        s.transition("idle")
        assert s.state == "idle"

    def test_running_to_no_match(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("no-match")
        assert s.state == "no-match"

    def test_running_to_blocked(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        s.transition("running")
        s.transition("blocked")
        assert s.state == "blocked"

    def test_illegal_transition_raises(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        with pytest.raises(ValueError, match="Illegal Panel state transition"):
            s.transition("executing")  # idle → executing is illegal

    def test_unknown_target_state_raises(self) -> None:
        s = PanelRenderState(artifact_id="note-a")
        with pytest.raises(ValueError, match="Unknown Panel target state"):
            s.transition("bogus-state")

    def test_same_turn_generated_to_executed_not_direct_path(self) -> None:
        # There is no legal idle→executing transition.
        # Proposals must go through: running→proposals-staged→confirming→executing.
        s = PanelRenderState(artifact_id="note-a")
        with pytest.raises(ValueError, match="Illegal Panel state transition"):
            s.transition("executing")


class TestNoMatchAndBlockedVisibility:
    def test_no_match_is_visible_failure(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="no-match")
        assert s.is_visible_failure is True

    def test_blocked_is_visible_failure(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="blocked")
        assert s.is_visible_failure is True

    def test_no_match_carries_message(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="no-match", message="No lifecycle match found.")
        assert s.message == "No lifecycle match found."

    def test_blocked_carries_reason(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="blocked", message="WriteGuard denied: tag allowlist.")
        assert s.message == "WriteGuard denied: tag allowlist."

    def test_idle_is_not_visible_failure(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="idle")
        assert s.is_visible_failure is False


class TestRenderPanelStateAdapter:
    def test_idle_render(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="idle")
        out = render_panel_state(s)
        assert out["state"] == "idle"
        assert out["artifact_id"] == "note-a"
        assert out["visible"] is True

    def test_running_has_loading(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="running")
        out = render_panel_state(s)
        assert out.get("loading") is True

    def test_proposals_staged_includes_count(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="proposals-staged", proposal_count=3)
        out = render_panel_state(s)
        assert out["proposal_count"] == 3

    def test_no_match_render_has_message(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="no-match", message="No match.")
        out = render_panel_state(s)
        assert out["message"] == "No match."

    def test_blocked_render_has_message(self) -> None:
        s = PanelRenderState(artifact_id="note-a", state="blocked", message="Policy denied.")
        out = render_panel_state(s)
        assert out["message"] == "Policy denied."

    def test_no_canvas_core_dependency(self) -> None:
        import companion_ui.panel.render_model as mod
        src = open(mod.__file__).read()
        assert "canvas_core" not in src
        assert "canvas_suggestion_flow" not in src

    def test_no_vault_write_in_module(self) -> None:
        import companion_ui.panel.render_model as mod
        src = open(mod.__file__).read()
        assert "SessionLogWriter" not in src
        assert "WriteGuard" not in src

    @pytest.mark.parametrize("state", REQUIRED_STATES)
    def test_all_required_states_renderable(self, state: str) -> None:
        s = PanelRenderState(artifact_id="note-a", state=state)
        out = render_panel_state(s)
        assert out["state"] == state
        assert "label" in out


# ---------------------------------------------------------------------------
# #2482 / C3 — no raw proposal/artifact identifier in proposal Evidence copy.
#
# The proposal Evidence "trigger_summary" is free-text runtime copy that can
# embed a raw correlation id mid-sentence (e.g. "Trigger for prop-move-1 …").
# #2444 humanised the standalone proposal_id/artifact_id spans but left the
# embedded-in-prose case in trigger_summary, which still leaked. The assertion
# is on *rendered visible text* (HTML tags AND <script> bodies stripped), so a
# token in visible copy fails even when the matching data-* hook still carries
# the raw id.
# ---------------------------------------------------------------------------
from html.parser import HTMLParser  # noqa: E402

from companion_ui.workspace.real_note_workspace_dev_page import (  # noqa: E402
    NoteLoadIntent,
    RealNoteWorkspaceDevPage,
)
from companion_ui.workspace.serve_dev_page import render_index_html  # noqa: E402

_RAW_PROPOSAL_IDS = ["prop-move-1", "prop-cross-1", "art-123"]

_VISIBLE_SKIP_TAGS = frozenset({"head", "script", "style", "template"})
_VISIBLE_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})


class _VisibleTextExtractor(HTMLParser):
    """Collect on-screen text via a real HTML parser (no regex tag-filter), so
    whitespace-padded or upper-case close tags (``</script >``, ``<SCRIPT>``)
    cannot leak inert markup into the scanned copy."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in _VISIBLE_VOID_TAGS:
            return
        if self._skip_depth or tag in _VISIBLE_SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _VISIBLE_VOID_TAGS:
            return
        if self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._chunks.append(data)


def _visible_text(html: str) -> str:
    """Rendered human-visible text: tags removed and <script>/<style>/<head>
    bodies dropped. Whitespace-collapsed and lower-cased for substring scans."""
    extractor = _VisibleTextExtractor()
    extractor.feed(html)
    extractor.close()
    return " ".join("".join(extractor._chunks).split()).lower()


class _ProposalClient:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def get(self, url: str, *, params: dict) -> dict:
        if url == "/api/companion/workspace":
            return self._payload
        raise AssertionError(f"unexpected GET: {url}")

    def post(self, url: str, *, json: dict) -> dict:  # noqa: A002
        raise AssertionError(f"unexpected POST: {url}")

    def delete(self, url: str, *, params: dict | None = None) -> dict:
        raise AssertionError(f"unexpected DELETE: {url}")


def _leaky_evidence_workspace_payload() -> dict:
    """Workspace payload whose proposal Evidence embeds raw ids in prose."""
    return {
        "artifact": {
            "artifact_id": "artifact-loaded-note",
            "note_path": "Notes/panel.md",
            "title": "Panel Note",
            "body": "# Panel Note\n\nBody.",
            "content_hash": "hash-1",
        },
        "canvas": {
            "session_id": None,
            "session_state": None,
            "user_present": False,
            "can_edit_body": False,
            "recovery_needed": False,
            "session_log_path": None,
            "undo_available": False,
            "applied_edit_count": 0,
            "undone_edit_count": 0,
            "session_persistence": "in_memory",
        },
        "panel": {
            "state": "proposals-staged",
            "proposal_count": 1,
            "proposals": [
                {
                    "proposal_id": "prop-move-1",
                    "artifact_id": "art-123",
                    "description": "Move this note into Projects/",
                    "status": "staged",
                    "evidence": {
                        # The embedded-in-prose leak: the runtime copy names the
                        # internal correlation ids inside an otherwise-human
                        # sentence. These must not reach visible copy.
                        "trigger_summary": (
                            "Trigger for prop-move-1 and prop-cross-1 on art-123"
                        ),
                        "action_class": "lifecycle.move",
                        "cognition_route": "rule",
                    },
                    "affordances": {
                        "confirm": True,
                        "correct": True,
                        "reject": True,
                    },
                }
            ],
        },
        "guards": {"canvas_enabled": True, "writeguard_status": "ok"},
        "runtime": {},
        "suggestions": {},
    }


def _render_leaky_evidence_html() -> str:
    client = _ProposalClient(_leaky_evidence_workspace_payload())
    page = RealNoteWorkspaceDevPage(client)  # type: ignore[arg-type]
    state = page.load(NoteLoadIntent(note_path="Notes/panel.md"))
    assert state.is_loaded is True
    fields = page.render_fields()
    assert fields is not None
    return render_index_html(
        api_base_url="http://127.0.0.1:18001",
        note_path="Notes/panel.md",
        fields=fields,
    )


def test_evidence_has_no_raw_proposal_id() -> None:
    html = _render_leaky_evidence_html()
    visible = _visible_text(html)
    for token in _RAW_PROPOSAL_IDS:
        assert token not in visible, (
            f"raw identifier {token!r} leaked into visible Evidence copy"
        )
    # Multi-hyphen ids (prop-move-1 / prop-cross-1) must be redacted *whole* — no
    # residual hyphen-suffix may survive. A regex that stops at the first hyphen
    # redacts only the leading "prop-move" / "prop-cross" segment and leaves the
    # trailing numeric segment behind as "this item-1" in visible copy. Assert
    # that partial-redaction residue does not leak (the full identifier is
    # consumed, segment by segment, to the human placeholder).
    assert "this item-1" not in visible, (
        "partial-redaction residue 'this item-1' survived prose redaction "
        "(hyphenated identifier only partially redacted — trailing '-1' kept)"
    )
    # The trigger summary embeds three ids (prop-move-1, prop-cross-1, art-123);
    # each collapses to the human placeholder, so it appears three times.
    assert visible.count("this item") >= 3
    # The evidence still reads as human copy (the prose around the redacted ids
    # survives), and the proposal's human description is shown.
    assert "trigger for" in visible  # _visible_text lower-cases
    assert "move this note into projects/" in visible  # _visible_text lower-cases
    # The raw correlation ids still arrive server-authoritatively in the payload
    # (proof of authority is the payload + data-* hooks, not a visible echo).
    proposal = _leaky_evidence_workspace_payload()["panel"]["proposals"][0]
    assert proposal["proposal_id"] == "prop-move-1"
    assert proposal["artifact_id"] == "art-123"
    assert 'data-proposal-id="prop-move-1"' in html
