"""Tests for real-note read-only workspace shell (#1064).

Verifies that the shell renders a real note payload as the primary surface,
exposes a secondary agent rail slot, is read-only, and performs no direct
vault I/O.
"""

from __future__ import annotations

from companion_ui.workspace.real_note_workspace_shell import (
    REGION_AGENT_RAIL,
    REGION_NOTE_BODY,
    REGION_NOTE_HEADER,
    ArtifactNotePayload,
    RealNoteWorkspaceShell,
)


def _payload(
    artifact_id: str = "note-uuid-1",
    note_path: str = "/vault/notes/test.md",
    title: str = "My Test Note",
    body: str = "# My Test Note\n\nBody content here.",
    content_hash: str = "abc123def456",
) -> ArtifactNotePayload:
    return ArtifactNotePayload(
        artifact_id=artifact_id,
        note_path=note_path,
        title=title,
        body=body,
        content_hash=content_hash,
    )


def _shell(**kw) -> RealNoteWorkspaceShell:
    return RealNoteWorkspaceShell(payload=_payload(**kw))


# ---------------------------------------------------------------------------
# AC 1: shell renders all required fields from real note payload
# ---------------------------------------------------------------------------


def test_workspace_shell_renders_real_note_payload() -> None:
    shell = _shell(
        artifact_id="note-uuid-42",
        note_path="/vault/notes/research.md",
        title="Research Note",
        body="# Research Note\n\nDetailed body.",
        content_hash="deadbeef0000",
    )
    assert shell.artifact_id == "note-uuid-42"
    assert shell.note_path == "/vault/notes/research.md"
    assert shell.title == "Research Note"
    assert "Detailed body" in shell.body
    assert shell.content_hash == "deadbeef0000"


# ---------------------------------------------------------------------------
# AC 2: note body is primary surface; agent rail is secondary
# ---------------------------------------------------------------------------


def test_workspace_shell_preserves_note_body_as_primary_surface() -> None:
    shell = _shell()
    assert shell.region_role(REGION_NOTE_BODY) == "primary"
    # Secondary/header regions are subordinate to the body
    assert shell.region_role(REGION_NOTE_HEADER) == "header"
    assert shell.region_role(REGION_AGENT_RAIL) == "secondary"


# ---------------------------------------------------------------------------
# AC 3: secondary agent rail slot is exposed without requiring Panel data
# ---------------------------------------------------------------------------


def test_workspace_shell_exposes_secondary_agent_slot() -> None:
    shell = _shell()
    assert shell.has_agent_rail is True
    # Empty by default — no Panel runtime data required
    assert shell.agent_rail_is_empty is True
    assert REGION_AGENT_RAIL in shell.regions

    # Can receive optional agent state
    shell_with_state = RealNoteWorkspaceShell(
        payload=_payload(), agent_rail_state="proposals-staged"
    )
    assert not shell_with_state.agent_rail_is_empty
    assert shell_with_state.agent_rail_state == "proposals-staged"


# ---------------------------------------------------------------------------
# AC 4: no mutation controls rendered in read-only shell
# ---------------------------------------------------------------------------


def test_workspace_shell_is_read_only() -> None:
    shell = _shell()
    assert shell.is_read_only is True
    assert shell.mutation_controls == []


# ---------------------------------------------------------------------------
# AC 5: shell has no direct vault I/O
# ---------------------------------------------------------------------------


def test_workspace_shell_has_no_direct_vault_io() -> None:
    """Architecture guard: workspace shell must not import or call vault I/O."""
    import ast
    import pathlib

    vault_io_calls = {"read_text", "read_bytes", "write_text", "write_bytes", "open"}
    shell_file = (
        pathlib.Path(__file__).resolve().parents[2]
        / "companion-ui"
        / "companion-app"
        / "companion_ui"
        / "workspace"
        / "real_note_workspace_shell.py"
    )
    assert shell_file.exists(), f"Shell file not found: {shell_file}"

    tree = ast.parse(shell_file.read_text(encoding="utf-8"))
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in vault_io_calls:
            violations.append(f"line {getattr(node, 'lineno', '?')}: uses .{node.attr}")

    assert not violations, (
        "real_note_workspace_shell must not perform direct vault I/O:\n"
        + "\n".join(violations)
    )
