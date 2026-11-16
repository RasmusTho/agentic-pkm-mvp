"""Verify one binary patch against two explicitly supplied baseline blobs.

Inputs are untrusted bytes. This only proves the patch-to-bytes relationship;
the caller must independently bind baseline blobs to HEAD and establish custody.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import subprocess
import stat
import tempfile


class PatchApplicationRefused(ValueError):
    """The supplied patch cannot be proven to produce the selected bytes."""


def verify_application(baseline: dict[str, bytes], expected: dict[str, str], patch: bytes,
                       patch_sha256: str) -> None:
    """Apply in a disposable repository and bind its entire output to two files."""
    if (len(baseline) != 2 or set(baseline) != set(expected) or not patch
            or len(patch) > 16 * 1024 * 1024 or hashlib.sha256(patch).hexdigest() != patch_sha256):
        raise PatchApplicationRefused("invalid patch contract")
    for name, content in baseline.items():
        relative = PurePosixPath(name)
        if (not name or relative.is_absolute() or str(relative) != name
                or any(p in (".", "..", ".git") for p in relative.parts)
                or any(c in name for c in "\\\n\r\0") or not isinstance(content, bytes)
                or len(content) > 16 * 1024 * 1024
                or not isinstance(expected[name], str) or len(expected[name]) != 64 or any(c not in "0123456789abcdef" for c in expected[name])):
            raise PatchApplicationRefused("invalid selected file")
    with tempfile.TemporaryDirectory(prefix="legacy-patch-") as temporary:
        root = Path(temporary)
        env = {"PATH": "/usr/bin:/bin", "HOME": temporary, "LC_ALL": "C",
               "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
               "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_OPTIONAL_LOCKS": "0"}
        try:
            init = subprocess.run(["/usr/bin/git", "init", "-q"], cwd=root, env=env,
                                  capture_output=True, timeout=10, check=False)
            if init.returncode:
                raise PatchApplicationRefused("isolated Git unavailable")
            for name, content in baseline.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
                path.chmod(0o644)
            applied = subprocess.run(["/usr/bin/git", "apply", "--binary", "--whitespace=nowarn", "-"],
                                     cwd=root, env=env, input=patch, capture_output=True, timeout=10, check=False)
            if applied.returncode:
                raise PatchApplicationRefused("patch did not apply")
            found: set[str] = set()
            for current, dirs, files in os.walk(root, followlinks=False):
                current_path = Path(current)
                if current_path == root:
                    dirs.remove(".git")
                if any((current_path / d).is_symlink() for d in dirs):
                    raise PatchApplicationRefused("patch created a symlink")
                for filename in files:
                    path = current_path / filename
                    if path.is_symlink() or not path.is_file() or stat.S_IMODE(path.stat().st_mode) != 0o644:
                        raise PatchApplicationRefused("patch created an unsupported file")
                    found.add(path.relative_to(root).as_posix())
            if found != set(baseline):
                raise PatchApplicationRefused("patch changed the selected file set")
            for name in baseline:
                path = root / name
                if path.stat().st_size > 16 * 1024 * 1024 or hashlib.sha256(path.read_bytes()).hexdigest() != expected[name]:
                    raise PatchApplicationRefused("patch output differs from selected bytes")
        except (OSError, subprocess.SubprocessError) as exc:
            raise PatchApplicationRefused("isolated patch verification failed") from exc
