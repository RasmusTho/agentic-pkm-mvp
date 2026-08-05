"""Regression tests for ``scripts/dev_test_environment_clobber_preflight.py``.

Issue #4613 (PR #4599 review thread r3700034269): the preflight must resolve
Compose interpolation against the same sources the real deploy invocation
uses. ``scripts/lib/deploy_channel_compose.sh`` invokes ``docker compose
--env-file "config/deploy/<channel>.env"``, which makes the channel deploy
env file the interpolation source *under* the invoking shell (shell wins)
and replaces the default repo-root ``.env`` entirely. The reviewed behavior
instead resolved against ``os.environ`` plus the repo ``.env``, so a
variable present only in the repo ``.env`` resolved nonblank in the
preflight while the real invocation resolved it blank -- masking the exact
clobber this gate exists to stop.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import dev_test_environment_clobber_preflight as preflight


#: Base compose mirroring the real docker-compose.yaml heimdal-capture-watch
#: shape after commit f95a6811: env_file chain only, no `environment:` block.
_BASE_COMPOSE = """\
services:
  heimdal-capture-watch:
    env_file:
      - ./config/runtime.defaults.env
      - path: ${WATCHER_RUNTIME_ENV_FILE:-./tmp/runtime.env}
        required: false
"""

#: Dev overlay reintroducing the pre-f95a6811 blank-override clobber shape.
_CLOBBER_OVERLAY = """\
services:
  heimdal-capture-watch:
    env_file:
      - path: ${WATCHER_RUNTIME_ENV_FILE:-./tmp/runtime.env}
        required: false
    environment:
      HEIMDAL_CAPTURE_WATCH_DIR: ${HEIMDAL_CAPTURE_WATCH_DIR:-}
"""

_TEST_CLOBBER_OVERLAY = """\
services:
  heimdal-capture-watch:
    environment:
      HEIMDAL_CAPTURE_WATCH_DIR: ${HEIMDAL_CAPTURE_WATCH_DIR:-}
"""


def _write_fixture_repo(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yaml").write_text(_BASE_COMPOSE, encoding="utf-8")
    (tmp_path / "docker-compose.dev.yml").write_text(_CLOBBER_OVERLAY, encoding="utf-8")
    (tmp_path / "config" / "deploy").mkdir(parents=True)
    (tmp_path / "config" / "runtime.defaults.env").write_text("", encoding="utf-8")
    (tmp_path / "tmp").mkdir()
    (tmp_path / "tmp" / "runtime.env").write_text(
        "HEIMDAL_CAPTURE_WATCH_DIR=/real/capture/dir\n", encoding="utf-8"
    )


def _write_test_runtime_env_fixture(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.test.yml").write_text(
        _TEST_CLOBBER_OVERLAY, encoding="utf-8"
    )
    (tmp_path / "tmp-test").mkdir()
    (tmp_path / "tmp-test" / "runtime.env").write_text(
        "HEIMDAL_CAPTURE_WATCH_DIR=/real/test/capture/dir\n",
        encoding="utf-8",
    )


def _run(
    channel: str, root: Path, capsys: pytest.CaptureFixture[str]
) -> tuple[int, dict]:
    rc = preflight.main([channel], root=root)
    return rc, json.loads(capsys.readouterr().out)


def test_preflight_uses_selected_deploy_env_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The preflight must resolve against the deploy's selected env file.

    Two directions, both of which the reviewed behavior got wrong:

    1. A repo-root ``.env`` value must NOT mask a clobber: the real
       invocation passes ``--env-file config/deploy/dev.env``, which replaces
       default ``.env`` loading, so a variable defined only in the repo
       ``.env`` still resolves blank at deploy time and clobbers the
       env_file-chain value. The preflight must block.
    2. A value the selected deploy env file itself supplies genuinely reaches
       Compose interpolation in the real invocation, so the override resolves
       nonblank and there is no clobber. The preflight must pass.
    """
    # Neither key is ever exported by deploy_channel_compose.sh (#3875); a
    # stray host export must not leak into resolution and skew either phase.
    monkeypatch.delenv("HEIMDAL_CAPTURE_WATCH_DIR", raising=False)
    monkeypatch.delenv("WATCHER_RUNTIME_ENV_FILE", raising=False)
    _write_fixture_repo(tmp_path)

    # Phase 1: repo .env decoy defines the key nonblank; the selected deploy
    # env file does not define it. The reviewed behavior read the decoy,
    # resolved the override nonblank, and passed -- the real deploy resolves
    # it blank and crash-loops the service.
    (tmp_path / ".env").write_text(
        "HEIMDAL_CAPTURE_WATCH_DIR=/masked/by/repo/dotenv\n", encoding="utf-8"
    )
    (tmp_path / "config" / "deploy" / "dev.env").write_text(
        "APP_IMAGE_TAG=dev-local\n", encoding="utf-8"
    )

    rc, receipt = _run("dev", tmp_path, capsys)

    assert rc == 1, (
        "Expected the preflight to BLOCK: the repo .env is not an "
        "interpolation source for the real `docker compose --env-file "
        f"config/deploy/dev.env` invocation. Receipt: {receipt}"
    )
    assert receipt["status"] == "blocked"
    violating = {(v["service"], v["field"]) for v in receipt["violations"]}
    assert ("heimdal-capture-watch", "HEIMDAL_CAPTURE_WATCH_DIR") in violating

    # Phase 2: the selected deploy env file supplies the value, exactly as
    # `--env-file` delivers it to Compose interpolation in the real
    # invocation -- the override resolves nonblank, so nothing is clobbered.
    (tmp_path / "config" / "deploy" / "dev.env").write_text(
        "HEIMDAL_CAPTURE_WATCH_DIR=/from/selected/deploy/env\n", encoding="utf-8"
    )

    rc, receipt = _run("dev", tmp_path, capsys)

    assert rc == 0, (
        "Expected the preflight to PASS: the selected deploy env file "
        f"resolves the override nonblank. Receipt: {receipt}"
    )
    assert receipt["status"] == "ok"


def test_preflight_missing_deploy_env_file_contributes_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A channel's first deploy runs this preflight before its pin file ever
    exists (write_pin happens after the preflight passes): an absent
    ``config/deploy/<channel>.env`` must contribute nothing, not crash, and
    the clobber must still be detected from the shell-only resolution."""
    monkeypatch.delenv("HEIMDAL_CAPTURE_WATCH_DIR", raising=False)
    monkeypatch.delenv("WATCHER_RUNTIME_ENV_FILE", raising=False)
    _write_fixture_repo(tmp_path)
    assert not (tmp_path / "config" / "deploy" / "dev.env").exists()

    rc, receipt = _run("dev", tmp_path, capsys)

    assert rc == 1
    assert receipt["status"] == "blocked"
    violating = {(v["service"], v["field"]) for v in receipt["violations"]}
    assert ("heimdal-capture-watch", "HEIMDAL_CAPTURE_WATCH_DIR") in violating


def test_preflight_uses_deploy_wrapper_runtime_env_default(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test preflight mirrors the wrapper's ``tmp-test`` runtime-env default."""
    monkeypatch.delenv("HEIMDAL_CAPTURE_WATCH_DIR", raising=False)
    monkeypatch.delenv("WATCHER_RUNTIME_ENV_FILE", raising=False)
    _write_fixture_repo(tmp_path)
    _write_test_runtime_env_fixture(tmp_path)

    rc, receipt = _run("test", tmp_path, capsys)

    assert rc == 1
    assert receipt["status"] == "blocked"
    violation = receipt["violations"][0]
    assert (violation["service"], violation["field"]) == (
        "heimdal-capture-watch",
        "HEIMDAL_CAPTURE_WATCH_DIR",
    )
    assert "/real/test/capture/dir" in violation["actual"]
    assert "/tmp-test/runtime.env" in violation["actual"]


def test_blank_override_against_derived_runtime_env_file_fails_closed(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blank test override cannot mask a value only in ``tmp-test``."""
    monkeypatch.delenv("HEIMDAL_CAPTURE_WATCH_DIR", raising=False)
    monkeypatch.delenv("WATCHER_RUNTIME_ENV_FILE", raising=False)
    _write_fixture_repo(tmp_path)
    _write_test_runtime_env_fixture(tmp_path)

    rc, receipt = _run("test", tmp_path, capsys)

    assert rc == 1
    assert receipt["status"] == "blocked"
    violating = {(v["service"], v["field"]) for v in receipt["violations"]}
    assert ("heimdal-capture-watch", "HEIMDAL_CAPTURE_WATCH_DIR") in violating
