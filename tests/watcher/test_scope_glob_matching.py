from __future__ import annotations

from pathlib import Path

import pytest

from app.watcher.scope import matches_scope

pytestmark = pytest.mark.not_pg


def test_scope_list_matches_root_and_nested() -> None:
    assert matches_scope(Path("root.md"), "*.md,**/*.md")
    assert matches_scope(Path("dir/sub.md"), "*.md,**/*.md")


def test_single_pattern_backward_compatible() -> None:
    assert matches_scope(Path("dir/note.md"), "dir/*.md")
    # Python's fnmatch treats '/' as a normal character, so '*' spans path separators.
    assert matches_scope(Path("dir/sub/note.md"), "dir/*.md")
