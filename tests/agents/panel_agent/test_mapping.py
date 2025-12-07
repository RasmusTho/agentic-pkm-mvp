from __future__ import annotations

from pathlib import Path

from app.components.settings.panel_actions_loader import load_panel_action_mapping, normalize_label


def _write_settings(path: Path) -> None:
    path.write_text(
        """---
mappings:
  - id: promote
    label: "  Promote   Note "
    intent_type: promotion
    downstream_event: note.promote
    params:
      level: evergreen
  - label: "Archive Note"
    intent_type: archival
    downstream_event: note.archive
---
""",
        encoding="utf-8",
    )


def test_load_panel_action_mapping_normalizes_labels(tmp_path: Path) -> None:
    settings_path = tmp_path / "panel-actions.md"
    _write_settings(settings_path)

    mappings = load_panel_action_mapping(settings_path)

    assert normalize_label("promote   note") in mappings
    promote = mappings[normalize_label("promote note")]
    assert promote.id == "promote"
    assert promote.intent_type == "promotion"
    assert promote.downstream_event == "note.promote"
    assert promote.params == {"level": "evergreen"}

    archive = mappings[normalize_label("archive note")]
    assert archive.intent_type == "archival"
    assert archive.downstream_event == "note.archive"
