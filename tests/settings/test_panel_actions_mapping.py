from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from app.settings.panel_actions import PanelActionMapping, load_panel_action_mappings


def _write_mapping(root: Path, name: str, content: str) -> Path:
    path = root / f"{name}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content).lstrip() + "\n", encoding="utf-8")
    return path


def test_load_panel_action_mappings_single_file(tmp_path: Path) -> None:
    root = tmp_path / "panel"
    _write_mapping(
        root,
        "actions",
        """
        ---
        mappings:
          - text: "Gör denna anteckning evergreen"
            event_type: "review.promote.evergreen"
          - text: "Arkivera den här anteckningen"
            event_type: "note.archive"
        ---
        body text ignored
        """,
    )

    mappings = load_panel_action_mappings(root=root)

    assert set(mappings.keys()) == {
        "Gör denna anteckning evergreen",
        "Arkivera den här anteckningen",
    }
    evergreen = mappings["Gör denna anteckning evergreen"]
    assert isinstance(evergreen, PanelActionMapping)
    assert evergreen.event_type == "review.promote.evergreen"


def test_load_panel_action_mappings_merges_multiple_files(tmp_path: Path) -> None:
    root = tmp_path / "panel"
    _write_mapping(
        root,
        "first",
        """
        ---
        mappings:
          - text: "Gör denna anteckning evergreen"
            event_type: "review.promote.evergreen"
        ---
        """,
    )
    _write_mapping(
        root,
        "second",
        """
        ---
        mappings:
          - text: "Skapa en separat sammanfattningsanteckning"
            event_type: "ingest.summary.create"
        ---
        """,
    )

    mappings = load_panel_action_mappings(root=root)

    assert set(mappings.keys()) == {
        "Gör denna anteckning evergreen",
        "Skapa en separat sammanfattningsanteckning",
    }


def test_load_panel_action_mappings_missing_root_returns_empty(tmp_path: Path) -> None:
    root = tmp_path / "does-not-exist"
    mappings = load_panel_action_mappings(root=root)
    assert mappings == {}
