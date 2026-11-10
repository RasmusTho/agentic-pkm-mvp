"""Find external libraries linked directly by the selected macOS Python binary."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def python_binary_roots(python: Path, prefix: Path) -> list[str]:
    if sys.platform != "darwin":
        return []
    binary = python.resolve(strict=True)
    env = {key: os.environ[key] for key in ("PATH", "HOME", "USER", "LOGNAME", "LANG") if key in os.environ}
    try:
        output = subprocess.check_output(["/usr/bin/otool", "-L", str(binary)], text=True, env=env, timeout=15)
        lines = output.splitlines()
        if not lines or not lines[0].strip().startswith(str(binary)):
            raise ValueError("invalid executable inspection")
        roots: list[str] = []
        for line in lines[1:]:
            if " (compatibility version " not in line:
                continue
            library = Path(line.strip().split(" (compatibility version ", 1)[0])
            if not library.is_absolute() or ".." in library.parts:
                raise ValueError("unresolved executable library")
            if str(library).startswith(("/usr/lib/", "/System/Library/")):
                continue
            resolved = library.resolve(strict=True)
            if prefix == resolved or prefix in resolved.parents:
                continue
            opt = library.parent.parent.parent
            cellar = opt.parent / "Cellar"
            if (opt.name == "opt" and opt.parent != Path("/") and opt.is_dir()
                    and library.parent.parent.is_symlink() and cellar in resolved.parents and str(opt) not in roots):
                roots.append(str(opt))
            for directory in (library.parent, resolved.parent):
                if (not directory.is_dir() or directory == Path.home()
                        or "lib" not in directory.parts or not resolved.is_file()):
                    raise ValueError("unsafe executable library")
                if str(directory) not in roots:
                    roots.append(str(directory))
        return roots
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RuntimeError("Cannot safely inspect Python executable libraries") from exc
