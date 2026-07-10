"""Regression coverage for the committed Heimdal client-control schema (#3131)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.heimdal.settings_notes import SETTINGS_NOTE_SPECS


pytestmark = pytest.mark.not_pg

SCHEMA_PATH = Path("schemas/heimdal-control-notes.schema.json")
CLIENT_CONTRACT_PATH = Path("docs/contracts/MIMER_CLIENT_CONTRACT.md")


def _published_registry_view() -> list[dict[str, object]]:
    return [
        {
            "kind": spec.kind,
            "relative_path": spec.rel_path,
            "authority": spec.authority,
            "sections": [
                {
                    "name": section.name,
                    "fields": [
                        {"name": field.name, "field_authority": field.field_authority}
                        for field in section.fields
                    ],
                }
                for section in spec.sections
            ],
        }
        for spec in SETTINGS_NOTE_SPECS.values()
    ]


def test_published_schema_matches_settings_note_registry() -> None:
    """The client artifact cannot drift from the runtime's control-note registry."""
    payload = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert payload["$id"] == "https://yggdrasil.local/schemas/heimdal-control-notes.schema.json"
    assert payload["schema_version"] == 1
    assert payload["control_surface_root"] == "_heimdal"
    assert payload["note_kinds"] == _published_registry_view()


def test_note_classification_contract_covers_decided_rows() -> None:
    """ADR-0055's decided classes are published once for all writers to consume."""
    contract = CLIENT_CONTRACT_PATH.read_text(encoding="utf-8")

    for pattern, note_class in (
        ("`_heimdal/**` frontmatter and full-note writes (except the explicit body-append operations below)", "rewritten"),
        ("body steering entries in `_heimdal/steering.log.md`", "append-only"),
        ("body steering entries in `_heimdal/watchlist.md` and `_heimdal/never.md`", "append-only"),
        ("human-authored Markdown outside managed append-only zones", "rewritten"),
        ("`⚙️ System/companions/**`, legacy `_system/companions/**`", "rewritten"),
        ("`<inbox_dir_rel>/inbox.md`", "append-only"),
        ("event-log producer paths", "append-only"),
        ("`Sources/**` (settings-resolved default root)", "append-only / create-once"),
        ("Episode notes (the Episode Note Store's materialized Markdown)", "rewritten"),
    ):
        assert f"| {pattern} | {note_class} |" in contract

    assert "`NSFileCoordinator` / `UIDocument`" in contract
    assert "#3131 supplies the published note-classification table" in contract
