"""CodeMirror source-mode adapter spike tests (#1305)."""

from __future__ import annotations

from pathlib import Path

import pytest

from companion_ui.spikes.codemirror_adapter import (
    BodyPatch,
    CodeMirrorNoteEditorAdapter,
    SelectionRange,
)


def test_adapter_interface() -> None:
    adapter = CodeMirrorNoteEditorAdapter("# Title\n\nBody")

    assert adapter.getMarkdown() == "# Title\n\nBody"
    adapter.setMarkdown("alpha beta gamma")
    assert adapter.getMarkdown() == "alpha beta gamma"
    assert adapter.getSelection() is None

    adapter.setSelection(6, 10)
    assert adapter.getSelection() == SelectionRange(start=6, end=10)

    adapter.applyBodyPatch(BodyPatch(start=6, end=10, replacement="BETA"))
    assert adapter.getMarkdown() == "alpha BETA gamma"
    assert adapter.getSelection() == SelectionRange(start=6, end=10)

    adapter.setMarkdown("Paragraph with ^block-id marker")
    assert adapter.focusBlock("block-id") is True
    assert adapter.getSelection() == SelectionRange(start=15, end=24)
    assert adapter.focusBlock("missing") is False


def test_no_autosave_or_write() -> None:
    adapter = CodeMirrorNoteEditorAdapter("Body")

    assert adapter.autosave_enabled is False
    assert adapter.production_wired is False
    assert adapter.write_calls == ()

    with pytest.raises(ValueError, match="ungoverned"):
        adapter.applyBodyPatch({"start": 0, "end": 0, "replacement": "x", "governed": False})

    source = (
        Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "spikes"
        / "codemirror_adapter.py"
    ).read_text(encoding="utf-8")
    for forbidden_call in (
        "httpx.",
        "WorkspaceHttpClient",
        "fetch(",
        ".post(",
        ".put(",
        ".patch(",
        ".delete(",
        "write_text(",
        "open(",
    ):
        assert forbidden_call not in source
