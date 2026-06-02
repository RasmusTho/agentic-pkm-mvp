from __future__ import annotations

from pathlib import Path

from scripts.validate_source_anchors import validate_issue_body


def test_validate_source_anchors_accepts_required_issue_section_shape() -> None:
    ok, errors = validate_issue_body(
        """
## Context
Test.

## Source Anchors
- #1403 :: prior issue
- `docs/CONCEPTS/RECEIPT_TRACE_ACCOUNTABILITY_CONTRACT.md` :: Promotion receipt query model decision (#1489)
"""
    )

    assert ok is True
    assert errors == []


def test_validate_source_anchors_accepts_explicit_existing_stable_anchor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ROADMAP.md").write_text("## Delivery PA2-FREEFORM\n", encoding="utf-8")

    ok, errors = validate_issue_body(
        """
## Source Anchors
- `docs/ROADMAP.md :: PA2-FREEFORM`
"""
    )

    assert ok is True
    assert errors == []


def test_validate_source_anchors_rejects_missing_section() -> None:
    ok, errors = validate_issue_body("## Context\nNo anchors.\n")

    assert ok is False
    assert errors == ["Issue is missing required `Source Anchors` section"]


def test_validate_source_anchors_rejects_missing_doc_path(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)

    ok, errors = validate_issue_body(
        """
## Source Anchors
- `docs/MISSING.md` :: MISSING-ANCHOR
"""
    )

    assert ok is False
    assert errors == ["Anchor file not found: docs/MISSING.md"]


def test_validate_source_anchors_rejects_missing_explicit_stable_anchor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ROADMAP.md").write_text("## Different Anchor\n", encoding="utf-8")

    ok, errors = validate_issue_body(
        """
## Source Anchors
- `docs/ROADMAP.md :: PA2-FREEFORM`
"""
    )

    assert ok is False
    assert errors == ["Anchor not found in docs/ROADMAP.md: PA2-FREEFORM"]
