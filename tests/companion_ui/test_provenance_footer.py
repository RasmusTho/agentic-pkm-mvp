"""Tests for ProvenanceFooter (#874).

Verifies:
- Construction with and without optional fields
- render dict structure
- session log path displayed from supplied context (not hardcoded)
- open session log intent dispatched when path available
- turn count renders from session state
- undo button disabled when can_undo_last_body_edit=False
- undo button enabled when can_undo_last_body_edit=True
- undo session-bounded (cross-session undo cannot be dispatched)
- footer has no runtime write side effects
- No dependency on Canvas Core, Panel, backend runtime, or vault writes.
"""

import pytest

from companion_ui.canvas_suggestion_flow.provenance_footer import (
    INTENT_OPEN_SESSION_LOG,
    INTENT_UNDO_LAST_EDIT,
    ProvenanceFooter,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_footer(
    suggestion_id: str = "sugg-001",
    artifact_id: str = "art-001",
    source_summary: str = ".chats/my-note/2026-05-17T10.md",
    route_summary: str = "canvas direct body edit",
    receipt_id: str | None = None,
    session_ref: str | None = None,
    session_log_path: str | None = None,
    turn_count: int = 3,
    can_undo_last_body_edit: bool = False,
    last_body_edit_id: str | None = None,
) -> ProvenanceFooter:
    return ProvenanceFooter(
        suggestion_id=suggestion_id,
        artifact_id=artifact_id,
        source_summary=source_summary,
        route_summary=route_summary,
        receipt_id=receipt_id,
        session_ref=session_ref,
        session_log_path=session_log_path,
        turn_count=turn_count,
        can_undo_last_body_edit=can_undo_last_body_edit,
        last_body_edit_id=last_body_edit_id,
    )


# ---------------------------------------------------------------------------
# Construction with required fields only
# ---------------------------------------------------------------------------

class TestProvenanceFooterConstruction:
    def test_required_fields_only(self) -> None:
        footer = make_footer()
        assert footer.suggestion_id == "sugg-001"
        assert footer.artifact_id == "art-001"
        assert footer.source_summary == ".chats/my-note/2026-05-17T10.md"
        assert footer.route_summary == "canvas direct body edit"

    def test_optional_fields_default_to_none(self) -> None:
        footer = make_footer()
        assert footer.receipt_id is None
        assert footer.session_ref is None
        assert footer.session_log_path is None
        assert footer.last_body_edit_id is None

    def test_optional_fields_can_be_set(self) -> None:
        footer = make_footer(
            receipt_id="rec-001",
            session_ref="session-abc",
            session_log_path=".chats/note/2026-05-17.md",
            last_body_edit_id="edit-xyz",
        )
        assert footer.receipt_id == "rec-001"
        assert footer.session_ref == "session-abc"
        assert footer.session_log_path == ".chats/note/2026-05-17.md"
        assert footer.last_body_edit_id == "edit-xyz"

    def test_missing_suggestion_id_raises(self) -> None:
        with pytest.raises(ValueError, match="suggestion_id"):
            make_footer(suggestion_id="")

    def test_missing_artifact_id_raises(self) -> None:
        with pytest.raises(ValueError, match="artifact_id"):
            make_footer(artifact_id="")

    def test_negative_turn_count_raises(self) -> None:
        with pytest.raises(ValueError, match="turn_count"):
            make_footer(turn_count=-1)

    def test_zero_turn_count_allowed(self) -> None:
        footer = make_footer(turn_count=0)
        assert footer.turn_count == 0


# ---------------------------------------------------------------------------
# Render dict structure
# ---------------------------------------------------------------------------

class TestProvenanceFooterRenderDict:
    def test_render_dict_keys(self) -> None:
        footer = make_footer()
        d = footer.to_render_dict()
        assert d["data_testid"] == "provenance-footer"
        assert d["aria_label"] == "Session provenance"
        assert "undo_button_disabled" in d
        assert "session_log_button_disabled" in d
        assert d["open_session_log_intent"] == INTENT_OPEN_SESSION_LOG
        assert d["undo_intent"] == INTENT_UNDO_LAST_EDIT
        assert d["data_testid_undo"] == "undo-last-edit"

    def test_render_dict_contains_turn_count(self) -> None:
        footer = make_footer(turn_count=7)
        d = footer.to_render_dict()
        assert d["turn_count"] == 7

    def test_render_dict_contains_source_and_route(self) -> None:
        footer = make_footer(
            source_summary="src-summary",
            route_summary="route-summary",
        )
        d = footer.to_render_dict()
        assert d["source_summary"] == "src-summary"
        assert d["route_summary"] == "route-summary"

    def test_optional_receipt_id_in_render_dict(self) -> None:
        footer = make_footer(receipt_id="rec-99")
        d = footer.to_render_dict()
        assert d.get("receipt_id") == "rec-99"

    def test_optional_fields_absent_when_none(self) -> None:
        footer = make_footer()
        d = footer.to_render_dict()
        assert "receipt_id" not in d
        assert "session_ref" not in d
        assert "last_body_edit_id" not in d


# ---------------------------------------------------------------------------
# AC: session log path displayed from session context; no hardcoded path
# ---------------------------------------------------------------------------

class TestSessionLogPath:
    def test_session_log_path_displayed(self) -> None:
        """AC: session_log_path displayed from supplied session context."""
        path = ".chats/my-note/2026-05-17T10-00.md"
        footer = make_footer(session_log_path=path)
        d = footer.to_render_dict()
        assert d["session_log_path"] == path
        assert d["session_log_button_disabled"] is False

    def test_session_log_path_none_disables_button(self) -> None:
        footer = make_footer(session_log_path=None)
        d = footer.to_render_dict()
        assert d["session_log_path"] is None
        assert d["session_log_button_disabled"] is True

    def test_no_hardcoded_path_in_source(self) -> None:
        """AC: production code must not hardcode the .chats/... path fixture."""
        import companion_ui.canvas_suggestion_flow.provenance_footer as mod
        src = open(mod.__file__).read()
        # The path shape is documented in the module but must not be hardcoded as a literal value.
        assert ".chats/my-note" not in src
        assert ".chats/note-slug" not in src


# ---------------------------------------------------------------------------
# AC: open session log intent dispatched
# ---------------------------------------------------------------------------

class TestOpenSessionLogIntent:
    def test_open_session_log_intent_dispatched(self) -> None:
        """AC: provenance.openSessionLog intent returned when path available."""
        path = ".chats/slug/2026.md"
        footer = make_footer(session_log_path=path)
        intent = footer.open_session_log_intent
        assert intent is not None
        assert intent["intent"] == INTENT_OPEN_SESSION_LOG
        assert intent["session_log_path"] == path

    def test_no_intent_when_path_missing(self) -> None:
        footer = make_footer(session_log_path=None)
        assert footer.open_session_log_intent is None

    def test_render_dict_intent_payload(self) -> None:
        footer = make_footer(session_log_path=".chats/x/t.md")
        d = footer.to_render_dict()
        assert d["open_session_log_intent_payload"] is not None
        assert d["open_session_log_intent_payload"]["intent"] == INTENT_OPEN_SESSION_LOG


# ---------------------------------------------------------------------------
# AC: turn count renders from session state
# ---------------------------------------------------------------------------

class TestTurnCount:
    def test_turn_count_renders_from_session_state(self) -> None:
        """AC: turn count renders from supplied session state."""
        footer = make_footer(turn_count=12)
        d = footer.to_render_dict()
        assert d["turn_count"] == 12

    def test_turn_count_updates_correctly(self) -> None:
        """AC: turn count updates when state changes (via new instance)."""
        footer_a = make_footer(turn_count=5)
        footer_b = make_footer(turn_count=6)
        assert footer_a.to_render_dict()["turn_count"] == 5
        assert footer_b.to_render_dict()["turn_count"] == 6


# ---------------------------------------------------------------------------
# AC: undo button disabled initially
# ---------------------------------------------------------------------------

class TestUndoButtonDisabled:
    def test_undo_button_disabled_initially(self) -> None:
        """AC: Undo button disabled when can_undo_last_body_edit=False."""
        footer = make_footer(can_undo_last_body_edit=False)
        d = footer.to_render_dict()
        assert d["undo_button_disabled"] is True
        assert d["undo_intent_payload"] is None

    def test_undo_intent_is_none_when_disabled(self) -> None:
        footer = make_footer(can_undo_last_body_edit=False)
        assert footer.undo_intent is None

    def test_undo_button_disabled_when_no_body_edit_id(self) -> None:
        """Undo stays disabled even if session_ref is set but can_undo=False."""
        footer = make_footer(
            can_undo_last_body_edit=False,
            session_ref="s1",
            last_body_edit_id=None,
        )
        assert footer.undo_intent is None


# ---------------------------------------------------------------------------
# AC: undo dispatches intent when available
# ---------------------------------------------------------------------------

class TestUndoDispatchesIntent:
    def test_undo_dispatches_intent_when_available(self) -> None:
        """AC: canvas.undoLastEdit intent returned when can_undo_last_body_edit=True."""
        footer = make_footer(
            can_undo_last_body_edit=True,
            session_ref="sess-1",
            last_body_edit_id="edit-42",
        )
        intent = footer.undo_intent
        assert intent is not None
        assert intent["intent"] == INTENT_UNDO_LAST_EDIT

    def test_undo_intent_payload_in_render_dict(self) -> None:
        footer = make_footer(
            can_undo_last_body_edit=True,
            session_ref="sess-1",
            last_body_edit_id="edit-42",
        )
        d = footer.to_render_dict()
        assert d["undo_button_disabled"] is False
        assert d["undo_intent_payload"] is not None
        assert d["undo_intent_payload"]["intent"] == INTENT_UNDO_LAST_EDIT

    def test_undo_intent_includes_session_ref(self) -> None:
        footer = make_footer(
            can_undo_last_body_edit=True,
            session_ref="sess-abc",
        )
        intent = footer.undo_intent
        assert intent["session_ref"] == "sess-abc"


# ---------------------------------------------------------------------------
# AC: undo session-bounded
# ---------------------------------------------------------------------------

class TestUndoSessionBounded:
    def test_undo_session_bounded(self) -> None:
        """AC: undo intent bounded to active session; cross-session dispatch impossible.

        The footer only includes the session_ref passed in.  Since session_ref
        is an opaque string from the caller, cross-session undo would require
        the caller to supply a different session_ref — the footer never looks
        up or injects a different session.
        """
        footer = make_footer(
            can_undo_last_body_edit=True,
            session_ref="session-current",
        )
        intent = footer.undo_intent
        # The intent only carries the session_ref supplied at construction.
        assert intent["session_ref"] == "session-current"

    def test_footer_cannot_access_other_sessions(self) -> None:
        """Footer has no mechanism to enumerate or switch sessions."""
        import companion_ui.canvas_suggestion_flow.provenance_footer as mod
        src = open(mod.__file__).read()
        # No session enumeration or cross-session lookup symbols
        assert "all_sessions" not in src
        assert "get_sessions" not in src


# ---------------------------------------------------------------------------
# AC: footer has no runtime write side effects
# ---------------------------------------------------------------------------

class TestFooterHasNoRuntimeWriteSideEffects:
    def test_footer_has_no_runtime_write_side_effects(self) -> None:
        """AC: footer is display/intent model only — no runtime writes.

        Checks that none of these runtime writer symbols are importable from
        the module (mentions in docstrings explaining what's forbidden are OK).
        """
        import companion_ui.canvas_suggestion_flow.provenance_footer as mod
        assert not hasattr(mod, "WriteGuard")
        assert not hasattr(mod, "SessionLogWriter")
        assert not hasattr(mod, "GovernanceRouter")
        assert not hasattr(mod, "canvas_writer")

    def test_no_canvas_core_import(self) -> None:
        import companion_ui.canvas_suggestion_flow.provenance_footer as mod
        src = open(mod.__file__).read()
        assert "import companion_ui.canvas_core" not in src
        assert "from companion_ui.canvas_core" not in src

    def test_no_panel_import(self) -> None:
        import companion_ui.canvas_suggestion_flow.provenance_footer as mod
        src = open(mod.__file__).read()
        assert "from companion_ui.panel" not in src
