"""Guard Dockerfile base-image alignment with CI (#3893).

Production must run the same Python minor version CI tests against, and the
base image must be digest-pinned for reproducible builds.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE_PATH = Path("Dockerfile")
CI_SMOKE_PATH = Path(".github/workflows/ci-smoke.yaml")


def _dockerfile_from_line() -> str:
    for line in DOCKERFILE_PATH.read_text(encoding="utf-8").splitlines():
        if line.startswith("FROM "):
            return line.strip()
    raise AssertionError("Dockerfile has no FROM line")


def test_dockerfile_base_image_is_digest_pinned() -> None:
    from_line = _dockerfile_from_line()
    assert re.fullmatch(
        r"FROM python:3\.\d+-slim@sha256:[0-9a-f]{64}", from_line
    ), f"FROM line must be python:3.x-slim pinned by sha256 digest, got: {from_line}"


def test_dockerfile_python_minor_matches_ci_smoke() -> None:
    from_line = _dockerfile_from_line()
    match = re.search(r"python:(3\.\d+)-slim", from_line)
    assert match, f"cannot parse python minor version from: {from_line}"
    docker_minor = match.group(1)

    ci_versions = re.findall(
        r"python-version:\s*['\"]?(3\.\d+)",
        CI_SMOKE_PATH.read_text(encoding="utf-8"),
    )
    assert ci_versions, "ci-smoke.yaml declares no python-version"
    assert set(ci_versions) == {docker_minor}, (
        f"Dockerfile python {docker_minor} != ci-smoke python-version {sorted(set(ci_versions))}"
    )
