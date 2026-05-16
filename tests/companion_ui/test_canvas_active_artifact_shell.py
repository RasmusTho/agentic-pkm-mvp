"""Tests for Canvas Core active artifact body shell (#1025).

The active note/artifact body is the primary Canvas working surface.
The session transcript/provenance is subordinate.
"""

from companion_ui.canvas_core.active_artifact_shell import (
    REGION_ARTIFACT_BODY,
    REGION_ESCAPE_HATCH,
    REGION_PROVENANCE,
    REGION_SESSION_CONTROLS,
    CanvasArtifactShell,
)


def test_active_artifact_body_renders_as_primary_surface() -> None:
    shell = CanvasArtifactShell(
        artifact_id="note-001",
        artifact_title="My Research Note",
        body="# Introduction\n\nThis is the artifact body.",
    )
    assert shell.body == "# Introduction\n\nThis is the artifact body."
    assert shell.region_role(REGION_ARTIFACT_BODY) == "primary"


def test_active_artifact_identity_available_to_session() -> None:
    shell = CanvasArtifactShell(
        artifact_id="note-001",
        artifact_title="My Research Note",
    )
    identity = shell.identity
    assert identity["artifact_id"] == "note-001"
    assert identity["artifact_title"] == "My Research Note"


def test_transcript_is_subordinate_to_note_body() -> None:
    shell = CanvasArtifactShell(artifact_id="note-002", artifact_title="Draft")
    assert shell.region_role(REGION_PROVENANCE) == "subordinate"
    assert shell.region_role(REGION_ARTIFACT_BODY) == "primary"


def test_canvas_shell_exposes_required_regions() -> None:
    shell = CanvasArtifactShell(artifact_id="note-003", artifact_title="Draft")
    assert REGION_ARTIFACT_BODY in shell.regions
    assert REGION_SESSION_CONTROLS in shell.regions
    assert REGION_PROVENANCE in shell.regions
    assert REGION_ESCAPE_HATCH in shell.regions

    assert shell.region_role(REGION_SESSION_CONTROLS) == "slot"
    assert shell.region_role(REGION_ESCAPE_HATCH) == "slot"


def test_portrait_layout_keeps_artifact_visible() -> None:
    shell = CanvasArtifactShell(artifact_id="note-004", artifact_title="Draft")
    assert shell.portrait_artifact_anchor is True


def test_shell_does_not_depend_on_panel_components() -> None:
    """Canvas Core shell must not import Panel-specific modules or classes."""
    import inspect
    from companion_ui.canvas_core import active_artifact_shell as mod
    src = inspect.getsource(mod)
    assert "from panel" not in src
    assert "import panel" not in src.lower()
    assert "PanelRender" not in src
    assert "panel_agent" not in src
