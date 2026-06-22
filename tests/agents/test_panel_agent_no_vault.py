from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agents.panel_agent.cognition import _build_note_snippet


def test_panel_agent_no_vault_skips_note_context_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VAULT_ROOT", raising=False)
    monkeypatch.delenv("VAULT_ROOT_DEV", raising=False)
    monkeypatch.delenv("VAULT_ROOT_TEST", raising=False)

    def _fail_build_note_context(**_: object) -> None:
        raise AssertionError("no-vault panel cognition must not build NoteContext")

    monkeypatch.setattr("app.agents.panel_agent.cognition.build_note_context", _fail_build_note_context)
    state = SimpleNamespace(
        vault_root=None,
        note=SimpleNamespace(uuid="note-no-vault"),
        note_content="legacy snippet",
    )

    assert _build_note_snippet(state) == "legacy snippet"
