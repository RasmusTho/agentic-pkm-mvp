from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

import pytest

from app.builderops.legacy_tracked_index import IndexRefused, inspect_index


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["/usr/bin/git", "-C", str(root), *args], text=True).strip()


def test_index_isolation_ignores_poisoned_source_config(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    for name in ("a", "b"):
        (tmp_path / name).write_text(name)
    git(tmp_path, "add", "a", "b")
    expected = {name: git(tmp_path, "hash-object", name) for name in ("a", "b")}
    index = tmp_path / ".git/index"
    digest = hashlib.sha256(index.read_bytes()).hexdigest()
    (tmp_path / ".git/config").write_text('[include]\n path = poison\n')
    (tmp_path / ".git/poison").write_text('[invalid\n')
    assert inspect_index(index, expected) == digest
    with pytest.raises(IndexRefused):
        inspect_index(index, {**expected, "a": "0" * 40})


def test_index_refuses_hidden_and_split_entries(tmp_path: Path) -> None:
    git(tmp_path, "init", "-q")
    for name in ("a", "b"):
        (tmp_path / name).write_text(name)
    git(tmp_path, "add", "a", "b")
    expected = {name: git(tmp_path, "hash-object", name) for name in ("a", "b")}
    git(tmp_path, "update-index", "--assume-unchanged", "a")
    with pytest.raises(IndexRefused):
        inspect_index(tmp_path / ".git/index", expected)
    git(tmp_path, "update-index", "--no-assume-unchanged", "a")
    git(tmp_path, "update-index", "--split-index")
    with pytest.raises(IndexRefused):
        inspect_index(tmp_path / ".git/index", expected)


def test_source_config_is_sandbox_denied(tmp_path: Path) -> None:
    if not Path("/usr/bin/sandbox-exec").exists():
        pytest.skip("macOS sandbox-exec unavailable")
    git(tmp_path, "init", "-q")
    for name in ("a", "b"):
        (tmp_path / name).write_text(name)
    git(tmp_path, "add", "a", "b")
    expected = {name: git(tmp_path, "hash-object", name) for name in ("a", "b")}
    config = tmp_path / ".git/config"
    poison = tmp_path / ".git/poison"
    config.write_text('[include]\n path = poison\n')
    poison.write_text('[invalid\n')
    profile = tmp_path / "deny.sb"
    profile.write_text(f'(version 1)\n(allow default)\n(deny file-read* (literal "{config}"))\n'
                       f'(deny file-read* (literal "{poison}"))\n')
    denied = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile), "/bin/cat", str(config)],
                            capture_output=True, check=False)
    assert denied.returncode != 0
    code = ("from pathlib import Path; from app.builderops.legacy_tracked_index import inspect_index; "
            f"inspect_index(Path({str(tmp_path / '.git/index')!r}), {expected!r})")
    result = subprocess.run(["/usr/bin/sandbox-exec", "-f", str(profile),
                             __import__("sys").executable, "-c", code], capture_output=True, check=False)
    assert result.returncode == 0, result.stderr.decode()
