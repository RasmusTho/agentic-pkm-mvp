from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from app.builderops.legacy_patch_material import verify_material


def test_two_file_material_binds_index_backup_and_bytes(tmp_path: Path) -> None:
    def git(*args: str) -> bytes:
        return subprocess.check_output(["/usr/bin/git", "-C", str(tmp_path), *args])
    git("init", "-q")
    baseline = {"a": b"baseline\x00", "b": b"old\n"}
    for name, data in baseline.items():
        (tmp_path / name).write_bytes(data)
    git("add", "a", "b")
    oids = {name: git("hash-object", name).decode().strip() for name in baseline}
    (tmp_path / "a").write_bytes(b"changed\x00")
    (tmp_path / "b").write_bytes(b"new\n")
    patch = git("diff", "--binary")
    backup = tmp_path.parent / (tmp_path.name + "-backup")
    backup.write_bytes(patch)
    hashes = {name: hashlib.sha256((tmp_path / name).read_bytes()).hexdigest() for name in baseline}
    arguments = dict(root=tmp_path, index=tmp_path / ".git/index", backup=backup,
                     baseline=baseline, baseline_oids=oids, selected_sha256=hashes,
                     patch_sha256=hashlib.sha256(patch).hexdigest())
    result = verify_material(**arguments)
    assert result["file_sha256"] == hashes
    (tmp_path / "b").write_bytes(b"drift")
    with pytest.raises(ValueError):
        verify_material(**arguments)
