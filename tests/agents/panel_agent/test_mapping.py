from __future__ import annotations

from pathlib import Path

from app.components.settings.panel_actions_loader import (
    PanelActionCatalog,
    PanelActionDescriptor,
    load_panel_action_mapping,
    normalize_label,
)


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


def test_catalog_marks_duplicate_labels_ambiguous() -> None:
    catalog = PanelActionCatalog.from_descriptors(
        [
            PanelActionDescriptor(
                id="promote.evergreen",
                intent_type="promotion",
                trust_verb="APPLY",
                downstream_event="review.promote.evergreen",
                labels=["Shared Label"],
            ),
            PanelActionDescriptor(
                id="note.archive",
                intent_type="archival",
                downstream_event="note.archive",
                labels=["Shared Label"],
            ),
        ]
    )

    assert catalog.find_by_label("Shared Label") is None
    assert catalog.has_ambiguous_label("Shared Label") is True
    assert normalize_label("Shared Label") not in catalog.label_index
    assert normalize_label("Shared Label") in catalog.ambiguous_labels


def test_load_panel_action_mapping_ignores_ambiguous_labels(tmp_path: Path) -> None:
    settings_path = tmp_path / "panel-actions.md"
    settings_path.write_text(
        """---
mappings:
  - id: promote.evergreen
    label: Shared Label
    intent_type: promotion
    downstream_event: review.promote.evergreen
  - id: note.archive
    label: Shared Label
    intent_type: archival
    downstream_event: note.archive
---
""",
        encoding="utf-8",
    )

    mappings = load_panel_action_mapping(settings_path)

    assert normalize_label("Shared Label") not in mappings
