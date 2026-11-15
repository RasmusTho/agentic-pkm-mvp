from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from app.builderops.legacy_selected_files import SelectedFilesRefused, read_selected


def test_reads_only_selected_bytes_and_refuses_symlink(tmp_path: Path) -> None:
    (tmp_path / "a").write_bytes(b"a\x00")
    (tmp_path / "b").write_bytes(b"b")
    expected = {n: hashlib.sha256((tmp_path / n).read_bytes()).hexdigest() for n in ("a", "b")}
    assert read_selected(tmp_path, expected) == {"a": b"a\x00", "b": b"b"}
    (tmp_path / "a").unlink()
    (tmp_path / "a").symlink_to("b")
    with pytest.raises(SelectedFilesRefused):
        read_selected(tmp_path, expected)
