from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


class LinuxNamedAclUnavailable(RuntimeError):
    """The runner cannot create or inspect the required Linux named ACL."""


@dataclass(frozen=True)
class LinuxNamedAclFile:
    path: Path
    owner_uid: int
    named_uid: int
    access_acl: str


def _require_linux() -> None:
    if sys.platform != "linux":
        raise LinuxNamedAclUnavailable(
            "the named-ACL fixture requires Linux POSIX ACL semantics"
        )


def _acl_tool(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise LinuxNamedAclUnavailable(
            f"Linux named-ACL fixture requires {name}; install the Ubuntu 'acl' package"
        )
    return executable


def _run_acl_tool(
    name: str,
    *arguments: str,
    input_bytes: bytes | None = None,
) -> bytes:
    _require_linux()
    result = subprocess.run(
        [_acl_tool(name), *arguments],
        input=input_bytes,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        diagnostic = result.stderr.decode("utf-8", errors="replace").strip()
        raise LinuxNamedAclUnavailable(
            f"Linux named-ACL fixture could not run {name} "
            f"(exit {result.returncode}): {diagnostic or 'no diagnostic emitted'}"
        )
    return result.stdout


def read_linux_access_acl(path: Path) -> str:
    acl = _run_acl_tool(
        "getfacl",
        "--absolute-names",
        "--numeric",
        "--omit-header",
        "--access",
        os.fspath(path),
    )
    return acl.decode("utf-8")


def create_linux_named_acl_file(path: Path, *, content: bytes) -> LinuxNamedAclFile:
    _require_linux()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    path.chmod(0o640)

    target_stat = path.lstat()
    if not stat.S_ISREG(target_stat.st_mode):
        raise LinuxNamedAclUnavailable(
            "Linux named-ACL fixture target must be a regular file"
        )

    owner_uid = target_stat.st_uid
    named_uid = 65_534 if owner_uid != 65_534 else 65_533
    _run_acl_tool(
        "setfacl",
        "--modify",
        f"user:{named_uid}:r--",
        os.fspath(path),
    )
    access_acl = read_linux_access_acl(path)
    if f"user:{named_uid}:r--" not in access_acl.splitlines():
        raise LinuxNamedAclUnavailable(
            "setfacl completed but getfacl did not report the required named-user entry"
        )
    return LinuxNamedAclFile(
        path=path,
        owner_uid=owner_uid,
        named_uid=named_uid,
        access_acl=access_acl,
    )


def replace_with_staged_acl_copy(path: Path, *, content: bytes) -> int:
    source_acl = read_linux_access_acl(path)
    descriptor, staged_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".stage",
        dir=path.parent,
    )
    staged = Path(staged_name)
    try:
        with os.fdopen(descriptor, "wb") as staged_file:
            staged_file.write(content)
            staged_file.flush()
        _run_acl_tool(
            "setfacl",
            "--set-file=-",
            os.fspath(staged),
            input_bytes=source_acl.encode("utf-8"),
        )
        if read_linux_access_acl(staged) != source_acl:
            raise LinuxNamedAclUnavailable(
                "staged replacement did not reproduce the source access ACL exactly"
            )
        with staged.open("rb") as staged_file:
            os.fsync(staged_file.fileno())
        staged_inode = staged.stat().st_ino
        os.replace(staged, path)
        return staged_inode
    finally:
        staged.unlink(missing_ok=True)
