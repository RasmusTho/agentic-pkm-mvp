"""Tests for Panel Agent NoteContext integration.

Verifies that:
1. When NoteContext is available, the agent uses rich frontmatter + body.
2. When NoteContext fails, the agent falls back to the legacy snippet.
3. The PANEL_BUDGET enforces max_body_chars=2000.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from app.agents.panel_agent.cognition import (
    PANEL_BUDGET,
    _build_note_snippet,
    _format_note_context,
)
from app.agents.panel_agent.graph import run_panel_graph
from app.agents.panel_agent.state import PanelAgentState
from app.components.concurrency import IdempotencyGuard
from app.components.settings.panel_actions_loader import (
    PanelActionCatalog,
    PanelActionDescriptor,
)
from app.events.panel import (
    NoteRef,
    PanelActionMapping,
    PanelInfo,
    PanelIntentAction,
    PanelIntentEvent,
    PanelIntentPayload,
)
from app.services.companion_note import AttachmentRef
from app.services.note_context import NoteContext, NoteContextError

TEST_NOTE_UUID = "nc-test-00000000-0000-4000-8000-000000000001"
TEST_NOTE_PATH = "vault/NoteContextTest.md"


@pytest.fixture(autouse=True)
def _avoid_wiring_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.panel_agent.graph.get_default_action_wiring", lambda: {}
    )


@pytest.fixture(autouse=True)
def _reset_idempotency_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.agents.panel_agent.graph._IDEMPOTENCY_GUARD",
        IdempotencyGuard(ttl_seconds=86400.0),
    )


def _make_note_context(
    *,
    body: str = "Rich body content from NoteContext.",
    frontmatter: dict[str, Any] | None = None,
    body_truncated: bool = False,
    backlinks: list[str] | None = None,
    attachments: list[AttachmentRef] | None = None,
    outgoing_links: list[str] | None = None,
) -> NoteContext:
    return NoteContext(
        uuid=TEST_NOTE_UUID,
        source_ref=TEST_NOTE_PATH,
        content_hash="abc123",
        ingest_state="tracked",
        attachments=attachments or [],
        frontmatter=frontmatter or {"title": "Test Note", "tags": ["test"]},
        body=body,
        body_truncated=body_truncated,
        outgoing_links=outgoing_links or [],
        backlinks=backlinks or [],
        classification=None,
        executed_actions=[],
        kind_policy={},
        trust_level="",
    )


def _make_state(
    *,
    vault_root: Path | None = None,
    note_content: str | None = "fallback snippet content",
) -> PanelAgentState:
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin="vault")
    panel = PanelInfo(
        panel_id="panel-1", instruction="Promote please.", raw_block=None
    )
    return PanelAgentState(
        note=note,
        panel=panel,
        note_content=note_content,
        vault_root=vault_root,
    )


# ---- PANEL_BUDGET constant ----


def test_panel_budget_values() -> None:
    assert PANEL_BUDGET.max_body_chars == 2000
    assert PANEL_BUDGET.include_relations is True
    assert PANEL_BUDGET.include_attachments is True
    assert PANEL_BUDGET.include_history is False


# ---- _format_note_context ----


def test_format_note_context_includes_frontmatter_and_body() -> None:
    ctx = _make_note_context(
        frontmatter={"title": "My Note", "status": "draft"},
        body="This is the body.",
    )
    result = _format_note_context(ctx)
    assert "Frontmatter:" in result
    assert "title: My Note" in result
    assert "status: draft" in result
    assert "Body:" in result
    assert "This is the body." in result


def test_format_note_context_marks_truncated_body() -> None:
    ctx = _make_note_context(body="Short.", body_truncated=True)
    result = _format_note_context(ctx)
    assert "Body (truncated):" in result


def test_format_note_context_includes_backlinks() -> None:
    ctx = _make_note_context(backlinks=["uuid-1", "uuid-2"])
    result = _format_note_context(ctx)
    assert "Backlinks:" in result
    assert "uuid-1" in result
    assert "uuid-2" in result


def test_format_note_context_includes_attachments() -> None:
    ctx = _make_note_context(
        attachments=[AttachmentRef(ref="images/photo.png", content_hash="h1")]
    )
    result = _format_note_context(ctx)
    assert "Attachments:" in result
    assert "images/photo.png" in result


def test_format_note_context_includes_outgoing_links() -> None:
    ctx = _make_note_context(outgoing_links=["uuid-3"])
    result = _format_note_context(ctx)
    assert "Outgoing links:" in result
    assert "uuid-3" in result


# ---- _build_note_snippet with NoteContext ----


def test_build_note_snippet_uses_note_context_when_available() -> None:
    ctx = _make_note_context(body="Rich content from companion.")
    state = _make_state(vault_root=Path("/tmp/vault"))

    with patch(
        "app.agents.panel_agent.cognition.build_note_context", return_value=ctx
    ) as mock_build:
        result = _build_note_snippet(state)

    mock_build.assert_called_once_with(
        uuid=TEST_NOTE_UUID,
        vault_root=Path("/tmp/vault"),
        budget=PANEL_BUDGET,
    )
    assert "Rich content from companion." in result
    assert "Frontmatter:" in result


# ---- Fallback behavior ----


def test_build_note_snippet_falls_back_on_note_context_error() -> None:
    state = _make_state(vault_root=Path("/tmp/vault"), note_content="legacy snippet")

    with patch(
        "app.agents.panel_agent.cognition.build_note_context",
        side_effect=NoteContextError("companion missing"),
    ):
        result = _build_note_snippet(state)

    assert result == "legacy snippet"


def test_build_note_snippet_falls_back_on_unexpected_exception() -> None:
    state = _make_state(vault_root=Path("/tmp/vault"), note_content="legacy snippet")

    with patch(
        "app.agents.panel_agent.cognition.build_note_context",
        side_effect=RuntimeError("unexpected"),
    ):
        result = _build_note_snippet(state)

    assert result == "legacy snippet"


def test_build_note_snippet_falls_back_when_no_vault_root() -> None:
    state = _make_state(vault_root=None, note_content="legacy snippet only")

    # Ensure VAULT_ROOT env var is not set
    with patch.dict("os.environ", {}, clear=True):
        result = _build_note_snippet(state)

    assert result == "legacy snippet only"


def test_build_note_snippet_truncates_legacy_to_800_chars() -> None:
    long_content = "x" * 1500
    state = _make_state(vault_root=None, note_content=long_content)

    with patch.dict("os.environ", {}, clear=True):
        result = _build_note_snippet(state)

    assert len(result) == 800


# ---- Budget enforcement ----


def test_build_note_context_receives_panel_budget() -> None:
    """Verify that PANEL_BUDGET with max_body_chars=2000 is passed to build_note_context."""
    ctx = _make_note_context(body="a" * 2000, body_truncated=True)
    state = _make_state(vault_root=Path("/tmp/vault"))

    with patch(
        "app.agents.panel_agent.cognition.build_note_context", return_value=ctx
    ) as mock_build:
        _build_note_snippet(state)

    call_kwargs = mock_build.call_args
    assert call_kwargs.kwargs["budget"].max_body_chars == 2000


# ---- Integration: LLM decider path receives NoteContext ----


class _StubReasoningFacade:
    def __init__(self, response: dict[str, Any]) -> None:
        self._response = response
        self.last_messages: list[dict[str, str]] | None = None

    def structured(
        self,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        *,
        task_kind: str,
        trace_id: str | None = None,
    ) -> dict[str, Any]:
        self.last_messages = messages
        return self._response


def test_llm_decider_uses_note_context_in_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    """When vault_root is set and NoteContext works, the LLM prompt includes rich context."""
    ctx = _make_note_context(
        frontmatter={"title": "Integration Test", "maturity": "seed"},
        body="This is the full body from NoteContext.",
    )
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.build_note_context", lambda **kw: ctx
    )

    stub = _StubReasoningFacade({"actions": ["promote.evergreen"]})
    monkeypatch.setattr(
        "app.agents.panel_agent.cognition.get_reasoning_facade", lambda: stub
    )

    mapping = PanelActionMapping(
        id="promote.evergreen",
        intent_type="promotion",
        downstream_event="review.promote.evergreen",
        params={"maturity": "evergreen"},
    )
    action = PanelIntentAction(
        id=mapping.id, label="Promote", checked=True, mapping=mapping
    )
    note = NoteRef(uuid=TEST_NOTE_UUID, path=TEST_NOTE_PATH, origin="vault")
    panel = PanelInfo(
        panel_id="panel-1", instruction="Promote please.", raw_block=None
    )
    payload = PanelIntentPayload(note=note, panel=panel, actions=[action])
    intent = PanelIntentEvent(payload=payload, trace_id="trace-nc-integration")
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                downstream_event="review.promote.evergreen",
                labels=["Promote"],
            )
        ]
    )
    state = PanelAgentState(
        trace_id=intent.trace_id,
        note=note,
        panel=panel,
        actions=[action],
        intent_event=intent,
        action_catalog=catalog,
        vault_root=Path("/tmp/vault"),
        note_content="old snippet that should not appear",
    )

    result = run_panel_graph(state, decider_mode="llm")

    # The LLM was called and the prompt contained NoteContext data
    assert stub.last_messages is not None
    user_prompt = next(msg["content"] for msg in stub.last_messages if msg["role"] == "user")
    assert "Integration Test" in user_prompt
    assert "full body from NoteContext" in user_prompt
    # The old snippet should NOT appear
    assert "old snippet that should not appear" not in user_prompt

    # The graph still completed successfully
    event_names = {getattr(evt, "event", None) for evt in result.emitted_events}
    assert "promote.intent.created" in event_names
