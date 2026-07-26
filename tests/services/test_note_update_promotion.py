from pathlib import Path

import pytest

from app.domain.state_axes import normalize_promotion_payload, resolve_promotion_axes
from app.knowledge.errors import KnowledgeWriteConflict
from app.services.note_update import apply_promotion_frontmatter
from scripts.yaml_roundtrip import load_frontmatter


def test_promotion_frontmatter_created_when_missing(tmp_path: Path) -> None:
    note_path = tmp_path / "note.md"
    note_path.write_text("Body content", encoding="utf-8")

    ok = apply_promotion_frontmatter(note_path, "UUID-1", "evergreen")
    assert ok

    frontmatter, body = load_frontmatter(note_path.read_text(encoding="utf-8"))
    assert frontmatter["uuid"] == "UUID-1"
    assert frontmatter["review_state"] == "reviewed"
    assert frontmatter["maturity"] == "evergreen"
    assert "Body content" in body


def test_promotion_normalizes_wikilink_uuid(tmp_path: Path) -> None:
    note_path = tmp_path / "note.md"
    note_path.write_text(
        """---
uuid: [[UUID-2]]
title: Sample
---

Keep body.
""",
        encoding="utf-8",
    )

    ok = apply_promotion_frontmatter(note_path, "UUID-2", "evergreen")
    assert ok

    frontmatter, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
    assert frontmatter["uuid"] == "UUID-2"
    assert frontmatter["review_state"] == "reviewed"
    assert frontmatter["maturity"] == "evergreen"
    assert frontmatter["title"] == "Sample"


def test_promotion_frontmatter_supports_normalized_review_and_maturity_axes(tmp_path: Path) -> None:
    note_path = tmp_path / "note.md"
    note_path.write_text("Body content", encoding="utf-8")

    ok = apply_promotion_frontmatter(note_path, "UUID-3", "reviewed", maturity="evergreen")
    assert ok

    frontmatter, _ = load_frontmatter(note_path.read_text(encoding="utf-8"))
    assert frontmatter["uuid"] == "UUID-3"
    assert frontmatter["review_state"] == "reviewed"
    assert frontmatter["maturity"] == "evergreen"


def test_promotion_frontmatter_staged_conflict_returns_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    note_path = tmp_path / "note.md"
    original = "Body content\n"
    note_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        "app.services.note_update.write_note_from_absolute",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            KnowledgeWriteConflict("rewritten note conflict staged")
        ),
    )

    assert apply_promotion_frontmatter(note_path, "UUID-stale", "evergreen") is False
    assert note_path.read_text(encoding="utf-8") == original


def test_resolve_promotion_axes_accepts_legacy_review_state_evergreen() -> None:
    axes = resolve_promotion_axes(review_state="evergreen")

    assert axes.review_state == "reviewed"
    assert axes.maturity == "evergreen"


def test_normalize_promotion_payload_keeps_event_name_compatibility_and_adds_transition() -> None:
    payload = normalize_promotion_payload(
        {
            "note": {"uuid": "UUID-4", "path": "vault/Note.md"},
            "action": {"id": "promote.evergreen", "label": "Promote to evergreen"},
            "maturity": "evergreen",
        }
    )

    assert payload["maturity"] == "evergreen"
    assert payload["transition"] == {
        "family": "promotion",
        "target_maturity": "evergreen",
    }
