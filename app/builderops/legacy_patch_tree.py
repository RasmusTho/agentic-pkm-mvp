"""Check a first patch commit's two explicitly bound tree changes.

The caller must obtain both maps from authenticated commit/tree object reads,
verify the commit's direct parent, and independently establish authority.
"""
from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path
import re


class PatchTreeRefused(ValueError):
    """The supplied exact tree delta does not match the selected bytes."""


def verify_first_patch_delta(
    delta: Mapping[str, tuple[str, str, str, str]], selected: Mapping[str, bytes],
    baseline_oids: Mapping[str, str],
) -> dict[str, str]:
    """Check exact path, old/new mode and blob OIDs for two modified files.

    The delta maps path to (old mode, old blob, new mode, new blob). It must
    come from a complete, rename-disabled tree comparison; this function does
    not fetch commits, establish ancestry, or authorize publication.
    """
    if len(selected) != 2 or set(delta) != set(selected) or set(baseline_oids) != set(selected):
        raise PatchTreeRefused("patch tree delta must contain exactly two selected files")
    observed: dict[str, str] = {}
    for path, data in selected.items():
        old_oid = baseline_oids[path]
        if (not isinstance(path, str) or not path or not isinstance(data, bytes)
                or not isinstance(old_oid, str) or not re.fullmatch(r"[0-9a-f]{40}", old_oid)):
            raise PatchTreeRefused("patch tree contract is invalid")
        oid = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if delta[path] != ("100644", old_oid, "100644", oid) or oid == old_oid:
            raise PatchTreeRefused("patch tree differs from selected bytes or baseline")
        observed[path] = oid
    return observed


def verify_first_patch_commit(
    *, cwd: "Path", worktree: "Path", parent: str, commit: str,
    selected: Mapping[str, bytes], baseline_oids: Mapping[str, str],
) -> dict[str, str]:
    """Read one direct successor and its complete tree delta after Git qualification.

    The caller must coordinate Git configuration and writers for the entire
    read; this function is not a claim, writer fence, or publication authority.
    """
    import subprocess

    from app.builderops import legacy_git_config

    if (not isinstance(cwd, Path) or not isinstance(worktree, Path)
            or not re.fullmatch(r"[0-9a-f]{40}", parent)
            or not re.fullmatch(r"[0-9a-f]{40}", commit)):
        raise PatchTreeRefused("invalid patch commit identity")
    try:
        legacy_git_config.check_host_config()
        legacy_git_config.check(cwd=cwd, worktree=worktree)

        def read(*args: str) -> bytes:
            result = subprocess.run(["/usr/bin/git", "-C", str(worktree), *args],
                                    env={"PATH": "/usr/bin:/bin", "HOME": "/dev/null",
                                         "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                                         "GIT_OPTIONAL_LOCKS": "0", "GIT_NO_REPLACE_OBJECTS": "1"},
                                    capture_output=True, timeout=30, check=False)
            if result.returncode or len(result.stdout) > 1_000_000:
                raise PatchTreeRefused("patch commit readback unavailable")
            return result.stdout

        parents = read("rev-list", "--parents", "-n", "1", commit).decode("ascii").split()
        if parents != [commit, parent]:
            raise PatchTreeRefused("patch commit is not the direct single-parent successor")
        raw = read("diff-tree", "--no-commit-id", "--raw", "--no-renames", "-r", "-z", parent, commit)
        fields = raw.split(b"\0")
        if fields[-1] != b"" or len(fields) % 2 != 1:
            raise PatchTreeRefused("patch tree delta is malformed")
        delta: dict[str, tuple[str, str, str, str]] = {}
        for metadata, path in zip(fields[:-1:2], fields[1:-1:2]):
            parts = metadata.decode("ascii").split()
            name = path.decode("utf-8")
            if len(parts) != 5 or not parts[0].startswith(":") or parts[4] != "M" or name in delta:
                raise PatchTreeRefused("patch tree delta is unsupported")
            delta[name] = (parts[0][1:], parts[2], parts[1], parts[3])
        legacy_git_config.check(cwd=cwd, worktree=worktree)
        return verify_first_patch_delta(delta, selected, baseline_oids)
    except (legacy_git_config.ConfigError, OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise PatchTreeRefused("patch commit readback unavailable") from exc
