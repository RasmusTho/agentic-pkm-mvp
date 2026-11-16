"""Prepare the pinned, isolated test environment used by the OpenHands trial.

The lock is deliberately specific to macOS arm64 and Python 3.12. Networked
setup downloads only hash-checked wheels; installation and execution are offline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import canonicalize_name

from app.builderops import openhands_delivery as delivery
from app.builderops import openhands_factory as factory
from scripts.openhands_native_libraries import python_binary_roots

LOCK = factory.FACTORY_ROOT / "config/builderops/openhands-test-macos-arm64-py312.lock"
LINE = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9_.+-]*) --hash=sha256:([0-9a-f]{64})")


def _pins(lock: bytes) -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in lock.decode("ascii").splitlines():
        match = LINE.fullmatch(line)
        if match is None or canonicalize_name(match[1]) in pins:
            raise delivery.DeliveryError("Invalid or duplicate test environment lock entry")
        pins[canonicalize_name(match[1])] = match[2]
    if not pins:
        raise delivery.DeliveryError("Empty test environment lock")
    return pins


def check_requirements(lock: bytes, manifests: dict[str, str]) -> None:
    """Reject a task whose declared dependencies are absent from the prepared lock."""
    pins = _pins(lock)
    for name, content in manifests.items():
        for raw in content.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                req = Requirement(line)
            except ValueError as exc:
                raise delivery.DeliveryError(f"Unsupported requirement in {name}: {line}") from exc
            if req.marker and not req.marker.evaluate():
                continue
            package = canonicalize_name(req.name)
            version = pins.get(package)
            supported_extra = (not req.extras or (package == "psycopg" and req.extras == {"binary"}
                               and pins.get("psycopg-binary") == version))
            if req.url or not supported_extra or version is None or not req.specifier.contains(version, prereleases=True):
                raise delivery.DeliveryError(f"Prepared test environment does not cover {name}: {line}")


def check_project(lock: bytes, content: str) -> None:
    """Check the runtime dependencies declared independently in pyproject.toml."""
    try:
        project = tomllib.loads(content)["project"]
        dependencies = project["dependencies"]
        requires_python = project["requires-python"]
        if (not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies)
                or not isinstance(requires_python, str)
                or not SpecifierSet(requires_python).contains(platform.python_version(), prereleases=True)):
            raise ValueError("unsupported project metadata")
    except (KeyError, TypeError, ValueError, InvalidSpecifier) as exc:
        raise delivery.DeliveryError("Cannot validate project dependencies or Python version") from exc
    check_requirements(lock, {"pyproject.toml": "\n".join(dependencies)})


def _platform() -> None:
    if sys.platform != "darwin" or platform.machine() != "arm64" or sys.version_info[:2] != (3, 12):
        raise delivery.DeliveryError("Prepared test environment requires macOS arm64 and Python 3.12")


def environment(install: Path, lock: bytes) -> Path:
    """Read the completed environment only when its lock and runtime match."""
    _platform()
    _pins(lock)
    digest = hashlib.sha256(lock).hexdigest()
    directory = install / "test-environments" / digest
    try:
        receipt = json.loads((directory / "receipt.json").read_text())
        interpreter = directory / "test-venv/bin/python"
        if receipt != {"version": 1, "lock_sha256": digest, "platform": "darwin-arm64-py312"}:
            raise ValueError("receipt mismatch")
        if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
            raise ValueError("missing interpreter")
    except (OSError, ValueError) as exc:
        raise delivery.DeliveryError("Prepared test environment is missing or incomplete; run setup") from exc
    return interpreter


def prepare(install: Path) -> Path:
    _platform()
    lock = LOCK.read_bytes()
    _pins(lock)
    digest = hashlib.sha256(lock).hexdigest()
    parent = install / "test-environments"
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory = parent / digest
    if directory.exists():
        return environment(install, lock)  # An incomplete attempt must be inspected, not overwritten.
    directory.mkdir(mode=0o700)
    home = directory / "home"
    home.mkdir(mode=0o700)
    (directory / "requirements.lock").write_bytes(lock)
    base = (install / "venv/bin/python").resolve(strict=True)
    prefix_output = subprocess.check_output([str(base), "-I", "-S", "-c", "import sys;print(sys.base_prefix)"], text=True)
    prefix = Path(prefix_output.strip()).resolve(strict=True)
    roots = [str(prefix), *factory._python_framework_traversal_roots(prefix),
             *factory._python_library_roots(base, prefix), *python_binary_roots(base, prefix)]
    entries = ['":minimal"="read"', '":workspace_roots"="read"']
    entries += [json.dumps(path) + '="read"' for path in dict.fromkeys(roots)]
    entries.append(json.dumps(str(directory)) + '="write"')
    filesystem = "permissions.test_setup.filesystem={" + ",".join(entries) + "}"
    codex = factory._executable("codex")
    outer_env = {key: os.environ[key] for key in ("PATH", "HOME", "USER", "LOGNAME", "LANG", "TMPDIR") if key in os.environ}

    def run(command: list[str], *, network: bool = False) -> None:
        invocation = [str(codex), "sandbox", "-c", f"permissions.test_setup.network.enabled={str(network).lower()}",
                      "-c", filesystem, "-P", "test_setup", "-C", str(directory), "--", "/usr/bin/env", "-i",
                      f"HOME={home}", f"TMPDIR={home}", "PATH=/usr/bin:/bin", *command]
        subprocess.run(invocation, cwd=directory, env=outer_env, stdin=subprocess.DEVNULL, check=True, timeout=900)

    run([str(base), "-I", "-S", "-m", "venv", str(directory / "bootstrap")])
    wheels = directory / "wheelhouse"
    wheels.mkdir(mode=0o700)
    requirements = str(directory / "requirements.lock")
    run([str(directory / "bootstrap/bin/python"), "-I", "-m", "pip", "--isolated", "download",
         "--only-binary=:all:", "--no-deps", "--require-hashes", "--index-url", "https://pypi.org/simple",
         "--dest", str(wheels), "-r", requirements], network=True)
    run([str(base), "-I", "-S", "-m", "venv", str(directory / "test-venv")])
    python = str(directory / "test-venv/bin/python")
    run([python, "-I", "-m", "pip", "--isolated", "install", "--no-index", "--find-links", str(wheels),
         "--require-hashes", "--no-deps", "-r", requirements])
    run([python, "-I", "-m", "pip", "--isolated", "check"])
    (directory / "receipt.json").write_text(json.dumps({"version": 1, "lock_sha256": digest,
                                                       "platform": "darwin-arm64-py312"}) + "\n")
    return environment(install, lock)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("install", type=Path)
    args = parser.parse_args()
    print(prepare(args.install.resolve(strict=True)))


if __name__ == "__main__":
    main()
