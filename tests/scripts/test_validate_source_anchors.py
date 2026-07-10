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


def test_validate_source_anchors_rejects_absolute_and_symlink_escape(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("## OUTSIDE-ANCHOR\n", encoding="utf-8")
    repo = tmp_path / "repo"
    docs = repo / "docs"
    docs.mkdir(parents=True)
    (docs / "escape.md").symlink_to(outside)

    absolute_ok, absolute_errors = validate_issue_body(
        f"## Source Anchors\n- `{outside}`\n",
        repo,
    )
    escape_ok, escape_errors = validate_issue_body(
        "## Source Anchors\n- `docs/escape.md :: OUTSIDE-ANCHOR`\n",
        repo,
    )

    assert absolute_ok is False
    assert absolute_errors == [f"Anchor path must be repository-relative: {outside}"]
    assert escape_ok is False
    assert escape_errors == ["Anchor path escapes repository root: docs/escape.md"]


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


def test_bold_bullet_anchor_found(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Emphasis-wrapped bullet anchors (bold, italic, inline-code) must resolve."""
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "KERNEL.md").write_text(
        "- **I-E2 (Idempotent handlers).** For every topic T: idempotent dispatch.\n",
        encoding="utf-8",
    )

    ok, errors = validate_issue_body(
        """
## Source Anchors
- `docs/KERNEL.md :: I-E2`
"""
    )

    assert ok is True
    assert errors == []


def test_italic_and_inline_code_bullet_anchor_found(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Other emphasis variants (`*ID*`, `` `ID` ``, `__ID__`) also resolve."""
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "REGISTER.md").write_text(
        "- *ID-ONE* some description\n"
        "- `ID-TWO` another description\n"
        "- __ID-THREE__ yet another\n",
        encoding="utf-8",
    )

    for anchor in ("ID-ONE", "ID-TWO", "ID-THREE"):
        ok, errors = validate_issue_body(
            f"""
## Source Anchors
- `docs/REGISTER.md :: {anchor}`
"""
        )
        assert ok is True, errors
        assert errors == []


def test_validate_source_anchors_still_rejects_absent_emphasis_anchor(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """An anchor ID genuinely absent from the doc must still fail, emphasis or not."""
    monkeypatch.chdir(tmp_path)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "KERNEL.md").write_text(
        "- **I-E2 (Idempotent handlers).** For every topic T: idempotent dispatch.\n",
        encoding="utf-8",
    )

    ok, errors = validate_issue_body(
        """
## Source Anchors
- `docs/KERNEL.md :: I-E9`
"""
    )

    assert ok is False
    assert errors == ["Anchor not found in docs/KERNEL.md: I-E9"]


def test_kernel_audit_invariant_ids_resolvable() -> None:
    """Real-world instance: the kernel audit doc's bold-bullet invariant IDs
    must resolve against the actual repo checkout (issue #2917 regression)."""
    repo_root = Path(__file__).resolve().parents[2]
    doc_path = repo_root / "docs/audits/SYSTEM_REDESIGN_CORRECTNESS_KERNEL_2026-07-02.md"
    assert doc_path.exists(), f"expected kernel audit doc at {doc_path}"

    ok, errors = validate_issue_body(
        f"""
## Source Anchors
- `{doc_path.relative_to(repo_root)} :: I-E2`
"""
    )

    assert ok is True
    assert errors == []
