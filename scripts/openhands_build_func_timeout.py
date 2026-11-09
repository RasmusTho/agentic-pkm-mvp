"""Build the pinned OpenHands sdist without access to the host's workspaces or home."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path


def validate_read_roots(roots: list[str], install: Path, host_home: Path, source: Path) -> None:
    for raw in roots:
        path = Path(raw)
        for candidate in (path, path.resolve(strict=True)):
            if (candidate == Path("/") or candidate == host_home or candidate in host_home.parents
                    or candidate == source or candidate in source.parents or source in candidate.parents
                    or candidate == install or candidate in install.parents or install in candidate.parents
                    or candidate.name == ".git"
                    or any((ancestor / ".git").exists() for ancestor in (candidate, *candidate.parents))):
                raise SystemExit("OpenHands bootstrap read root overlaps host, repository or installation state")


def main() -> None:
    if sys.platform != "darwin" or platform.machine() != "arm64" or sys.version_info[:2] != (3, 12):
        raise SystemExit("OpenHands bootstrap requires macOS arm64 and Python 3.12")
    install = Path(sys.argv[1]).resolve(strict=True)
    host_home = Path(sys.argv[2]).resolve(strict=True)
    source = Path(sys.argv[3]).resolve(strict=True)
    if (install == host_home or install in host_home.parents or install == source
            or install in source.parents or source in install.parents):
        raise SystemExit("OpenHands installation overlaps the host home or source repository")
    home = install / "setup-home"
    venv = install / "venv"
    if home.is_symlink() or venv.is_symlink() or not home.is_dir() or not venv.is_dir():
        raise SystemExit("OpenHands bootstrap directories are unavailable or linked")
    sdist = install / "setup-home/func_timeout-4.3.5.tar.gz"
    python = install / "venv/bin/python"
    uv = Path(shutil.which("uv") or "").resolve(strict=True)
    codex = shutil.which("codex")
    if not codex or not sdist.is_file() or not python.is_file() or not uv.is_file():
        raise SystemExit("OpenHands bootstrap tools or pinned source are unavailable")
    if hashlib.sha256(sdist.read_bytes()).hexdigest() != "74cd3c428ec94f4edfba81f9b2f14904846d5ffccc27c92433b8b5939b5575dd":
        raise SystemExit("OpenHands bootstrap source hash does not match")
    prefix = Path(sys.base_prefix).resolve(strict=True)
    sys.path.insert(0, str(source))
    from scripts.openhands_native_libraries import python_binary_roots

    roots = [str(prefix), str(uv.parent), *python_binary_roots(python, prefix)]
    framework = prefix.parent.parent
    if framework.name == "Python.framework" and framework.parent.name == "Frameworks":
        package = framework.parent.parent
        if package.parent.parent.name == "Cellar":
            roots.extend((str(package), str(package.parent.parent.parent / "opt")))
    for name in ("_ssl", "_sqlite3"):
        spec = importlib.util.find_spec(name)
        if spec is None or not spec.origin or spec.origin == "built-in":
            continue
        extension = Path(spec.origin).resolve(strict=True)
        if prefix not in extension.parents:
            raise SystemExit("Python extension is outside the selected runtime")
        output = subprocess.check_output(["/usr/bin/otool", "-arch", platform.machine(), "-L", str(extension)], text=True)
        for line in output.splitlines()[1:]:
            path = line.strip().split(" (compatibility version ", 1)[0]
            lib = Path(path)
            if not re.fullmatch(r"lib(?:sqlite3|ssl|crypto)(?:\.[A-Za-z0-9_-]+)*\.dylib", lib.name):
                continue
            if not lib.is_absolute() or ".." in lib.parts:
                raise SystemExit("Python library path is unresolved")
            if str(lib).startswith(("/usr/lib/", "/System/Library/")):
                continue
            resolved = lib.resolve(strict=True)
            for directory in (lib.parent, resolved.parent):
                if not directory.is_dir() or directory == Path.home() or "lib" not in directory.parts:
                    raise SystemExit("Python library directory is unavailable")
                roots.append(str(directory))
    validate_read_roots(roots, install, host_home, source)
    entries = ['":minimal"="read"', '":workspace_roots"="write"']
    entries += [json.dumps(root) + '="read"' for root in dict.fromkeys(roots)]
    entries.append(json.dumps(str(venv)) + '="write"')
    profile = "permissions.openhands_bootstrap.filesystem={" + ",".join(entries) + "}"
    command = [codex, "sandbox", "-c", "permissions.openhands_bootstrap.network.enabled=true",
               "-c", profile, "-P", "openhands_bootstrap", "-C", str(home), "--", "/usr/bin/env", "-i",
               "PATH=/usr/bin:/bin", f"HOME={home}", f"TMPDIR={home}", str(uv), "pip", "install",
               "--no-config", "--index-url", "https://pypi.org/simple", "--python", str(python)]
    outer_env = {key: os.environ[key] for key in ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR") if key in os.environ}
    subprocess.run([*command, str(sdist)], cwd=install, env=outer_env, stdin=subprocess.DEVNULL, check=True, timeout=600)
    subprocess.run([*command, "--only-binary", ":all:", "openhands-agent-server==1.60.1",
                    "openhands-sdk==1.60.1", "openhands-tools==1.60.1", "agent-client-protocol==0.12.1",
                    "psycopg[binary]==3.2.10"], cwd=install, env=outer_env, stdin=subprocess.DEVNULL,
                   check=True, timeout=900)


if __name__ == "__main__":
    main()
