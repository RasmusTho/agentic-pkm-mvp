"""Tests for Canvas Core active artifact body shell (#1025).

The active note/artifact body is the primary Canvas working surface.
The session transcript/provenance is subordinate.
"""

from pathlib import Path
import importlib.util


def _load_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = (
        repo_root / "companion-ui" / "companion-app" / "canvas_active_artifact_shell.py"
    )
    spec = importlib.util.spec_from_file_location("canvas_active_artifact_shell", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_active_artifact_body_renders_as_primary_surface() -> None:
    m = _load_module()
    shell = m.CanvasArtifactShell(
        artifact_id="note-001",
        artifact_title="My Research Note",
        body="# Introduction\n\nThis is the artifact body.",
    )
    assert shell.body == "# Introduction\n\nThis is the artifact body."
    # Artifact body region is the primary surface
    assert shell.region_role(m.REGION_ARTIFACT_BODY) == "primary"


def test_active_artifact_identity_available_to_session() -> None:
    m = _load_module()
    shell = m.CanvasArtifactShell(
        artifact_id="note-001",
        artifact_title="My Research Note",
    )
    identity = shell.identity
    assert identity["artifact_id"] == "note-001"
    assert identity["artifact_title"] == "My Research Note"


def test_transcript_is_subordinate_to_note_body() -> None:
    m = _load_module()
    shell = m.CanvasArtifactShell(artifact_id="note-002", artifact_title="Draft")

    # Provenance/transcript region is subordinate, not primary
    assert shell.region_role(m.REGION_PROVENANCE) == "subordinate"
    # Artifact body remains primary regardless of provenance presence
    assert shell.region_role(m.REGION_ARTIFACT_BODY) == "primary"


def test_canvas_shell_exposes_required_regions() -> None:
    m = _load_module()
    shell = m.CanvasArtifactShell(artifact_id="note-003", artifact_title="Draft")

    # All four canonical regions must be declared
    assert m.REGION_ARTIFACT_BODY in shell.regions
    assert m.REGION_SESSION_CONTROLS in shell.regions
    assert m.REGION_PROVENANCE in shell.regions
    assert m.REGION_ESCAPE_HATCH in shell.regions

    # Session controls and escape hatch are slots (not yet implemented, not absent)
    assert shell.region_role(m.REGION_SESSION_CONTROLS) == "slot"
    assert shell.region_role(m.REGION_ESCAPE_HATCH) == "slot"


def test_portrait_layout_keeps_artifact_visible() -> None:
    m = _load_module()
    shell = m.CanvasArtifactShell(artifact_id="note-004", artifact_title="Draft")
    # Portrait anchor must be True — artifact body is cognitive anchor on narrow layouts
    assert shell.portrait_artifact_anchor is True


def test_shell_does_not_depend_on_panel_components() -> None:
    """Canvas Core shell must not import Panel-specific modules or classes."""
    import inspect
    m = _load_module()
    src = inspect.getsource(m)
    # Check for import-level coupling only — not word presence in docstrings
    assert "from panel" not in src
    assert "import panel" not in src.lower()
    assert "PanelRender" not in src
    assert "panel_agent" not in src
