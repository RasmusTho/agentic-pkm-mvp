"""Guard Dockerfile base-image alignment with CI (#3893).

Production must run the same Python minor version CI tests against, and the
base image must be digest-pinned for reproducible builds.
"""

from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE_PATH = Path("Dockerfile")
CI_SMOKE_PATH = Path(".github/workflows/ci-smoke.yaml")


def _dockerfile_from_lines() -> list[str]:
    lines = [
        line.strip()
        for line in DOCKERFILE_PATH.read_text(encoding="utf-8").splitlines()
        if line.startswith("FROM ")
    ]
    if not lines:
        raise AssertionError("Dockerfile has no FROM line")
    return lines


def test_dockerfile_base_image_is_digest_pinned() -> None:
    # Every stage of the multi-stage build must stay on the pinned base
    # (an optional `AS <stage>` suffix names the stage).
    for from_line in _dockerfile_from_lines():
        assert re.fullmatch(
            r"FROM python:3\.\d+-slim@sha256:[0-9a-f]{64}(?: AS [A-Za-z0-9_.-]+)?",
            from_line,
        ), f"FROM line must be python:3.x-slim pinned by sha256 digest, got: {from_line}"


def test_dockerfile_python_minor_matches_ci_smoke() -> None:
    docker_minors: set[str] = set()
    for from_line in _dockerfile_from_lines():
        match = re.search(r"python:(3\.\d+)-slim", from_line)
        assert match, f"cannot parse python minor version from: {from_line}"
        docker_minors.add(match.group(1))
    assert len(docker_minors) == 1, (
        f"all Dockerfile stages must use one python minor, got {sorted(docker_minors)}"
    )
    docker_minor = docker_minors.pop()

    ci_versions = re.findall(
        r"python-version:\s*['\"]?(3\.\d+)",
        CI_SMOKE_PATH.read_text(encoding="utf-8"),
    )
    assert ci_versions, "ci-smoke.yaml declares no python-version"
    assert set(ci_versions) == {docker_minor}, (
        f"Dockerfile python {docker_minor} != ci-smoke python-version {sorted(set(ci_versions))}"
    )


def test_tts_layer_uses_python_aligned_default_install() -> None:
    """The Python 3.12 builder installs the compatible TTS pins by default."""
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    builder_stage = text.split("FROM ", 2)[1]
    assert "INSTALL_TTS" not in text
    assert "pip install --no-cache-dir -r requirements-tts.txt" in builder_stage
