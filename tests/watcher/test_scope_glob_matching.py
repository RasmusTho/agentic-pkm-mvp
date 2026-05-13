from __future__ import annotations

from pathlib import Path

import pytest

from app.watcher.scope import derive_scope_roots, matches_scope

pytestmark = pytest.mark.not_pg


def test_scope_list_matches_root_and_nested() -> None:
    assert matches_scope(Path("root.md"), "*.md,**/*.md")
    assert matches_scope(Path("dir/sub.md"), "*.md,**/*.md")


def test_single_pattern_backward_compatible() -> None:
    assert matches_scope(Path("dir/note.md"), "dir/*.md")
    # Python's fnmatch treats '/' as a normal character, so '*' spans path separators.
    assert matches_scope(Path("dir/sub/note.md"), "dir/*.md")


def test_mixed_unprefixed_pattern_keeps_vault_root(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    roots = derive_scope_roots(vault, "*.md,Inbox/*.md")

    assert roots == [vault]
