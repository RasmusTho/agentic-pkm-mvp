from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from app.builderops.legacy_patch_application import PatchApplicationRefused, verify_application


def test_binary_patch_binds_both_bytes_and_rejects_extra_file(tmp_path: Path) -> None:
    def git(*args: str) -> bytes:
        return subprocess.check_output(["/usr/bin/git", "-C", str(tmp_path), *args])
    git("init", "-q")
    baseline = {"a": b"base\x00a", "b": b"base b\n"}
    for name, data in baseline.items():
        (tmp_path / name).write_bytes(data)
    git("add", "a", "b")
    (tmp_path / "a").write_bytes(b"dirty\x00a")
    (tmp_path / "b").write_bytes(b"dirty b\n")
    patch = git("diff", "--binary")
    expected = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in baseline}
    verify_application(baseline, expected, patch, hashlib.sha256(patch).hexdigest())
    with pytest.raises(PatchApplicationRefused):
        verify_application(baseline, {**expected, "a": "0" * 64}, patch, hashlib.sha256(patch).hexdigest())
    (tmp_path / "c").write_text("extra")
    git("add", "-N", "c")
    extra = git("diff", "--binary")
    with pytest.raises(PatchApplicationRefused):
        verify_application(baseline, expected, extra, hashlib.sha256(extra).hexdigest())
