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


def main() -> None:
    if sys.platform != "darwin" or platform.machine() != "arm64" or sys.version_info[:2] != (3, 12):
        raise SystemExit("OpenHands bootstrap requires macOS arm64 and Python 3.12")
    install = Path(sys.argv[1]).resolve(strict=True)
    sdist = install / "setup-home/func_timeout-4.3.5.tar.gz"
    python = install / "venv/bin/python"
    uv = Path(shutil.which("uv") or "").resolve(strict=True)
    codex = shutil.which("codex")
    if not codex or not sdist.is_file() or not python.is_file() or not uv.is_file():
        raise SystemExit("OpenHands bootstrap tools or pinned source are unavailable")
    if hashlib.sha256(sdist.read_bytes()).hexdigest() != "74cd3c428ec94f4edfba81f9b2f14904846d5ffccc27c92433b8b5939b5575dd":
        raise SystemExit("OpenHands bootstrap source hash does not match")
    prefix = Path(sys.base_prefix).resolve(strict=True)
    roots = [str(prefix), str(uv.parent)]
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
    entries = ['":minimal"="read"', '":workspace_roots"="write"']
    entries += [json.dumps(root) + '="read"' for root in dict.fromkeys(roots)]
    profile = "permissions.openhands_bootstrap.filesystem={" + ",".join(entries) + "}"
    home = install / "setup-home"
    command = [codex, "sandbox", "-c", "permissions.openhands_bootstrap.network.enabled=true",
               "-c", profile, "-P", "openhands_bootstrap", "-C", str(install), "--", "/usr/bin/env", "-i",
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
