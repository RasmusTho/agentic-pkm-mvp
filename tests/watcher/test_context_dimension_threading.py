from __future__ import annotations

from app.watcher.vault_watcher import extract_context_dimensions_for_note


def test_per_note_scope_not_overridden_by_global() -> None:
    frontmatter = {"scope": "note-scope", "domain": "legacy-scope"}

    dims = extract_context_dimensions_for_note(frontmatter, global_scope="global-scope")

    assert dims["scope"] == "note-scope"


def test_scope_glob_stays_separate_from_operational_scope() -> None:
    frontmatter = {"scope_glob": "Inbox/**", "domain": "work"}

    dims = extract_context_dimensions_for_note(frontmatter, global_scope="global-scope")

    assert dims["scope"] == "work"
    assert dims["scope"] != frontmatter["scope_glob"]
