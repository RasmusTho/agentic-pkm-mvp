from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.knowledge.adapters import FsVaultAdapter, ObsidianCliAdapter
from app.knowledge.contracts import NoteLocator
from app.knowledge.errors import KnowledgeCapabilityError, KnowledgeTransportError


def test_fs_adapter_write_and_read(tmp_path: Path) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="PKM", path="Inbox/Test.md")
    adapter.write_note(locator, "hello")
    assert adapter.read_note(locator) == "hello"


def test_fs_adapter_append_and_prepend(tmp_path: Path) -> None:
    adapter = FsVaultAdapter(tmp_path)
    locator = NoteLocator(vault="PKM", path="Inbox/Test.md")
    adapter.write_note(locator, "body")
    adapter.prepend_note(locator, "start\n")
    adapter.append_note(locator, "\nend")
    assert adapter.read_note(locator) == "start\nbody\nend"


def test_obsidian_cli_adapter_scopes_vault_as_first_arg() -> None:
    calls: list[list[str]] = []

    class _Proc:
        stdout = ""

    def fake_runner(cmd, check, capture_output, text):  # type: ignore[no-untyped-def]
        calls.append(list(cmd))
        return _Proc()

    adapter = ObsidianCliAdapter(runner=fake_runner)
    adapter.open_note(NoteLocator(vault="Mimer", path="Inbox/Note.md"))
    assert calls
    assert calls[0][0] == "obsidian"
    assert calls[0][1] == "vault=Mimer"


def test_obsidian_cli_adapter_raises_transport_error_for_timeout() -> None:
    def fake_runner(cmd, check, capture_output, text):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(1, cmd, stderr="connection timed out")

    adapter = ObsidianCliAdapter(runner=fake_runner)

    with pytest.raises(KnowledgeTransportError):
        adapter.open_note(NoteLocator(vault="Mimer", path="Inbox/Note.md"))


def test_obsidian_cli_adapter_keeps_semantic_failures_as_capability_errors() -> None:
    def fake_runner(cmd, check, capture_output, text):  # type: ignore[no-untyped-def]
        raise subprocess.CalledProcessError(1, cmd, stderr="invalid path")

    adapter = ObsidianCliAdapter(runner=fake_runner)

    with pytest.raises(KnowledgeCapabilityError):
        adapter.write_note(NoteLocator(vault="Mimer", path="Inbox/Note.md"), "body")
