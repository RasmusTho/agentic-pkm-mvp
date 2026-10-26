"""Regression coverage for protected BWS test checkout paths."""

from __future__ import annotations

from pathlib import Path
import stat
import tempfile

import pytest

from tests.deploy import bws_fixture_support


def test_protected_temp_path_uses_home_when_tmp_and_repository_ancestry_are_unsafe(
    tmp_path: Path, monkeypatch
):
    repository_root = Path(__file__).resolve().parents[2]
    safe_parent = next(
        candidate
        for candidate in (tmp_path, repository_root)
        if bws_fixture_support._has_protected_ancestry(candidate)
    )

    with tempfile.TemporaryDirectory(prefix="pytest-bws-fixture-home-", dir=safe_parent) as home_dir:
        safe_home = Path(home_dir)
        safe_home.chmod(0o750)
        unsafe_root = safe_home / "unsafe"
        unsafe_root.mkdir()
        unsafe_root.chmod(0o777)
        tmp_candidate = unsafe_root / "tmp"
        repository_root = unsafe_root / "repo"
        tmp_candidate.mkdir()
        repository_root.mkdir()

        assert not bws_fixture_support._has_protected_ancestry(tmp_candidate)
        assert not bws_fixture_support._has_protected_ancestry(repository_root)

        with monkeypatch.context() as patch:
            patch.setattr(Path, "home", classmethod(lambda cls: safe_home))
            with bws_fixture_support._protected_temp_path(
                tmp_candidate,
                repository_root=repository_root,
            ) as selected:
                assert selected.parent == safe_home
                assert bws_fixture_support._has_protected_ancestry(selected)


def test_protected_temp_path_accepts_root_owned_sticky_ancestor():
    shared_temp = Path("/tmp")
    info = shared_temp.stat()
    if info.st_uid != 0 or not info.st_mode & stat.S_ISVTX:
        pytest.skip("/tmp is not a root-owned sticky directory on this host")

    with tempfile.TemporaryDirectory(prefix="pytest-bws-sticky-", dir=shared_temp) as directory:
        assert bws_fixture_support._has_protected_ancestry(Path(directory))
