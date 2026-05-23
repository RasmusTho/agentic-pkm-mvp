from __future__ import annotations

import textwrap
from datetime import datetime, timezone

import pytest

from app.agents.panel.agent import handle_note_update
from app.settings.panel_actions import PanelActionMapping
import app.store.object_store as object_store_module
from app.objects import DomainObject, ObjectStore
from app.stores import reset_store_backends


def _note(markdown_body: str) -> str:
    return textwrap.dedent(
        f"""\
        ---
        uuid: NOTE-1
        title: Sample
        ---

        %% AI:Start %%
        ## AI-instruktion
        Do things
        ## AI-åtgärder
        {markdown_body}
        %% AI:End %%
        """
    )


def _store_note(payload: dict | None = None) -> None:
    object_store_module._MEMORY_STORE["NOTE-1"] = DomainObject(
        uuid="NOTE-1",
        kind="note",
        payload=payload or {},
        source_ref="vault/note.md",
        created_at=datetime.now(timezone.utc),
    )


@pytest.fixture(autouse=True)
def _reset_store() -> None:
    reset_store_backends()
    import app.agents.panel.agent as panel_agent

    panel_agent._EXECUTED_FALLBACK.clear()
    _store_note()


def test_checked_action_removed_and_receipt_added(monkeypatch: pytest.MonkeyPatch) -> None:
    mapping = {
        "Promote this note": PanelActionMapping(
            text="Promote this note",
            event_type="promote.intent.created",
            payload_template={"note": {"uuid": "NOTE-1"}},
        )
    }
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: mapping)
    markdown = _note("- [x] Promote this note")

    result = handle_note_update("NOTE-1", markdown, markdown)

    updated = result.updated_markdown
    assert "- [x] Promote this note" not in updated
    assert "> [!info]- AI status" in updated
    assert "- ✅ Promote this note" in updated


def test_re_run_does_not_reexecute_same_id(monkeypatch: pytest.MonkeyPatch) -> None:
    mapping = {
        "Promote this note": PanelActionMapping(
            text="Promote this note",
            event_type="promote.intent.created",
            payload_template={"note": {"uuid": "NOTE-1"}},
        )
    }
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: mapping)
    markdown = _note("- [x] Promote this note")
    first = handle_note_update("NOTE-1", markdown, markdown)
    second = handle_note_update("NOTE-1", first.updated_markdown, first.updated_markdown)

    assert second.updated_markdown.count("- ✅ Promote this note") == 1


def test_clear_status_removes_receipts(monkeypatch: pytest.MonkeyPatch) -> None:
    mapping = {}
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: mapping)
    markdown = textwrap.dedent(
        """\
        ---
        uuid: NOTE-1
        title: Sample
        ---

        %% AI:Start %%
        ## AI-instruktion
        clear status
        ## AI-åtgärder
        - [ ] Promote this note
        %% AI:End %%

        > [!info]- AI status
        > - ✅ Promote this note
        > - ⚠️ Something failed
        """
    )
    cleared = handle_note_update("NOTE-1", markdown, markdown)

    assert "> [!info]- AI status" in cleared.updated_markdown
    assert "- ✅" not in cleared.updated_markdown
    assert "- ⚠️" not in cleared.updated_markdown


def test_freeform_promote_does_not_autoexecute_without_checkbox(monkeypatch: pytest.MonkeyPatch) -> None:
    mapping = {
        "Make this note evergreen": PanelActionMapping(
            text="Make this note evergreen",
            event_type="promote.intent.created",
            payload_template={"note": {"uuid": "NOTE-1"}, "maturity": "evergreen"},
            action_id="promote.evergreen",
        )
    }
    monkeypatch.setattr("app.settings.panel_actions.load_panel_action_mappings", lambda: mapping)
    markdown = textwrap.dedent(
        """\
        ---
        uuid: NOTE-1
        title: Sample
        ---

        %% AI:Start %%
        Instruction: promote this
        %% AI:End %%
        """
    )

    first = handle_note_update("NOTE-1", markdown, markdown, action_mappings=mapping)
    promote_events = [ev for ev in first.events if ev.event == "promote.intent.created"]
    assert not promote_events
    assert "auto-executed: promote" not in first.updated_markdown
    assert "- [ ] Make this note evergreen" in first.updated_markdown
