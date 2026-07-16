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


def test_tts_layer_is_opt_in_so_default_build_succeeds() -> None:
    """requirements-tts.txt pins piper-tts==1.2.0 -> piper-phonemize~=1.1.0,
    which publishes no cp312 linux wheels and no sdist, so installing it on
    the python:3.12 base fails EVERY default build (`docker build .`,
    compose build, app-image-build.yml — none pass INSTALL_TTS). The
    app-image-build.yml "Build SHA-tagged app image" job requires the default
    build to produce a working image, so the TTS layer must be opt-in
    (default 0) until the pins gain 3.12 support; the guarded RUN keeps the
    skip loud in the build log."""
    text = DOCKERFILE_PATH.read_text(encoding="utf-8")
    assert re.search(r"^ARG INSTALL_TTS=0\s*$", text, flags=re.MULTILINE), (
        "INSTALL_TTS must default to 0: the TTS pins cannot install on the "
        "python:3.12 base, so a default of 1 makes every default build fail "
        "(app-image-build.yml passes no INSTALL_TTS build-arg)"
    )
    assert 'if [ "$INSTALL_TTS" = "1" ]' in text, (
        "the TTS install must stay behind the INSTALL_TTS guard so it can be "
        "re-enabled with --build-arg INSTALL_TTS=1 once the pins support 3.12"
    )
    assert "SKIPPING requirements-tts.txt" in text, (
        "the skip must be loud in the build log so a missing TTS layer is "
        "diagnosable from CI output alone"
    )
