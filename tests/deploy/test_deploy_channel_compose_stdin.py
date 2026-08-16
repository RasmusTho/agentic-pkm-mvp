"""Regression coverage for #4536: the Compose wrapper's own SIGNBOARD_ROOT
override document used to bind to the command's stdin (`-f -` plus a
terminating heredoc), so any caller piping real data into
`deploy_channel_compose` — most notably `prepare_instance_state_deployment`
delivering a host-produced quiescence or legacy-owner inventory into the
`instance-state-init` container — had that data silently replaced by the
override document instead of reaching the container. Both inventories then
arrived empty at their consumer paths and every channel deploy failed closed
on `deployment-prove`.

These tests exercise the fix at both levels named in the issue:

- `deploy_channel_compose` itself must not consume a caller's stdin for its
  own override document (test 1).
- The real deployment producer, `prepare_instance_state_deployment`, must
  deliver non-empty, privately-owned inventories to their consumer paths
  (tests 2-4), and must still fail closed when a source inventory is empty
  or missing (test 5).
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEPLOY_CHANNEL_COMPOSE_SH = REPO_ROOT / "scripts/lib/deploy_channel_compose.sh"
INSTANCE_STATE_DEPLOYMENT_SH = REPO_ROOT / "scripts/lib/instance_state_deployment.sh"
# Resolved once, before any test prepends a fake python3 to PATH, so the
# writer-inventory fixture's fallback branch can still reach a real
# interpreter for any call it does not stub itself.
_REAL_PYTHON3 = shutil.which("python3") or "/usr/bin/python3"


def _write_executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


def _compose_repo_fixture(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docker-compose.yaml").write_text("services: {}\n", encoding="utf-8")
    (repo / "overlay.yml").write_text("", encoding="utf-8")
    (repo / "channel.env").write_text("", encoding="utf-8")
    return repo


def test_compose_wrapper_does_not_consume_caller_stdin(tmp_path: Path) -> None:
    """A caller that pipes data into deploy_channel_compose receives that data
    at the container's stdin rather than the Compose override document."""

    repo = _compose_repo_fixture(tmp_path)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    stdin_capture = tmp_path / "stdin-capture.txt"

    _write_executable(
        fake_bin / "docker",
        "#!/usr/bin/env bash\n"
        'if [[ " $* " == *" run "* ]]; then\n'
        '  cat > "$STDIN_CAPTURE"\n'
        "fi\n"
        "exit 0\n",
    )

    harness = tmp_path / "harness.sh"
    _write_executable(
        harness,
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        f"source '{DEPLOY_CHANNEL_COMPOSE_SH}'\n"
        f"deploy_channel_compose '{repo}' dev overlay.yml testproj '{repo}/channel.env' "
        "run --rm --no-deps -T instance-state-init sh -c cat\n",
    )

    marker = "caller-supplied-stdin-payload\n"
    result = subprocess.run(
        ["bash", str(harness)],
        input=marker,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "STDIN_CAPTURE": str(stdin_capture),
        },
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert stdin_capture.exists(), "the container never received a stdin payload"
    assert stdin_capture.read_text(encoding="utf-8") == marker
    # The override document Compose would otherwise have received on stdin
    # must not have leaked through instead of the caller's payload.
    assert "SIGNBOARD_ROOT" not in stdin_capture.read_text(encoding="utf-8")


def _install_writer_inventory_fixture(
    fake_bin: Path,
    event_log: Path,
    *,
    owner_inventory_content: str = '{"fixture":"legacy-owner","writers_drained":true}\n',
    quiescence_inventory_content: str = '{"fixture":"quiescence","inventory_complete":true}\n',
) -> None:
    """A minimal stand-in for scripts/instance_state_writer_inventory.py that
    writes deterministic, known content so delivery can be asserted byte-for-
    byte, mirroring the harness pattern already used in
    tests/ops/test_instance_state_volume_contract.py."""

    _write_executable(
        fake_bin / "python3",
        "#!/usr/bin/env bash\n"
        "printf 'python:%s\\n' \"$*\" >> \"$EVENT_LOG\"\n"
        "if [[ \"$1\" == *instance_state_writer_inventory.py ]]; then\n"
        '  case " $* " in\n'
        "    *' produce-legacy-owners '*)\n"
        '      while [ "$#" -gt 0 ]; do\n'
        '        if [ "$1" = --output ]; then '
        f"printf '{owner_inventory_content}' > \"$2\"; exit 0; fi\n"
        "        shift\n"
        "      done\n"
        "      exit 2 ;;\n"
        "    *' controller-token '*) printf 'linux:%064d\\n' 0; exit 0 ;;\n"
        "    *' prove-quiescent '*)\n"
        '      while [ "$#" -gt 0 ]; do\n'
        '        if [ "$1" = --output ]; then '
        f"printf '{quiescence_inventory_content}' > \"$2\"; exit 0; fi\n"
        "        shift\n"
        "      done\n"
        "      exit 2 ;;\n"
        "    *' validate-legacy-owners '*)\n"
        '      while [ "$#" -gt 0 ]; do\n'
        '        if [ "$1" = --output ]; then '
        f"printf '{owner_inventory_content}' > \"$2\"; exit 0; fi\n"
        "        shift\n"
        "      done\n"
        "      exit 2 ;;\n"
        "    *' compose-fence-plan '*)\n"
        '      while [ "$#" -gt 0 ]; do\n'
        '        if [ "$1" = --receipt-output ]; then '
        "printf '%s\\n' '{\"schema\":\"agentic-pkm.mvr05-cutover-fence.v1\",\"db_clients\":[\"api\",\"migrate\"],\"migration_runner\":\"migrate\",\"stopped_services\":[\"api\"],\"source_sha256\":\"0000000000000000000000000000000000000000000000000000000000000000\"}' > \"$2\"; "
        "printf 'api\\n'; exit 0; fi\n"
        "        shift\n"
        "      done\n"
        "      exit 2 ;;\n"
        "  esac\n"
        "  exit 2\n"
        "fi\n"
        # Any other python3 invocation falls through to the real interpreter so
        # the rest of the sourced libraries keep working normally.
        'exec "$REAL_PYTHON3" "$@"\n',
    )


def _fake_compose_harness(tmp_path: Path, extra_env: dict[str, str]) -> tuple[subprocess.CompletedProcess, Path]:
    event_log = tmp_path / "events.log"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _install_writer_inventory_fixture(fake_bin, event_log)

    ownership_root = tmp_path / "instance-ownership"
    ownership_root.mkdir()

    harness = tmp_path / "harness.sh"
    _write_executable(
        harness,
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"source '{INSTANCE_STATE_DEPLOYMENT_SH}'\n"
        "fake_compose() {\n"
        "  printf 'compose:%s\\n' \"$*\" >> \"$EVENT_LOG\"\n"
        "  if [ \"${1:-}\" = config ] && [ -n \"${DEPLOY_COMPOSE_FENCE_CONFIG_OUTPUT:-}\" ]; then\n"
        "    printf '%s\\n' 'services: {api: {depends_on: [db], labels: {com.agentic-pkm.mvr05.db-role: client}}, db: {labels: {com.agentic-pkm.mvr05.db-role: server}}, instance-state-init: {labels: {com.agentic-pkm.mvr05.db-role: fence-controller}}, migrate: {command: [/app/scripts/run_migrations.sh], depends_on: [db], labels: {com.agentic-pkm.mvr05.db-role: migration-runner}}}' > \"$DEPLOY_COMPOSE_FENCE_CONFIG_OUTPUT\"\n"
        "  fi\n"
        "  return 0\n"
        "}\n"
        "prepare_instance_state_deployment fake_compose prod\n",
    )

    result = subprocess.run(
        ["bash", str(harness)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "EVENT_LOG": str(event_log),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "INSTANCE_OWNERSHIP_HOST_STATE_DIR": str(ownership_root),
            "REAL_PYTHON3": _REAL_PYTHON3,
            **extra_env,
        },
        check=False,
    )
    return result, ownership_root


def test_producer_delivers_quiescence_inventory_with_content(tmp_path: Path) -> None:
    """The deployment producer delivers a non-empty quiescence inventory to
    its consumer path, asserted through prepare_instance_state_deployment
    rather than the delivery helper alone."""

    result, ownership_root = _fake_compose_harness(tmp_path, {})
    assert result.returncode == 0, result.stderr

    delivered = ownership_root / "deployment-quiescence-inventory.json"
    assert delivered.exists(), "quiescence inventory was never delivered"
    content = delivered.read_text(encoding="utf-8")
    assert content.strip() != ""
    assert "quiescence" in content


def test_producer_delivers_owner_inventory_with_content(tmp_path: Path) -> None:
    """The deployment producer delivers a non-empty legacy-owner inventory to
    its consumer path, asserted through the same production entrypoint."""

    result, ownership_root = _fake_compose_harness(tmp_path, {})
    assert result.returncode == 0, result.stderr

    delivered = ownership_root / "legacy-owner-inventory.json"
    assert delivered.exists(), "legacy-owner inventory was never delivered"
    content = delivered.read_text(encoding="utf-8")
    assert content.strip() != ""
    assert "legacy-owner" in content


def test_delivered_inventories_are_private(tmp_path: Path) -> None:
    """Both delivered inventories are regular files with mode 0600 owned by
    the runtime user."""

    result, ownership_root = _fake_compose_harness(tmp_path, {})
    assert result.returncode == 0, result.stderr

    for name in (
        "deployment-quiescence-inventory.json",
        "legacy-owner-inventory.json",
    ):
        delivered = ownership_root / name
        metadata = delivered.lstat()
        assert stat.S_ISREG(metadata.st_mode), f"{name} is not a regular file"
        assert stat.S_IMODE(metadata.st_mode) == 0o600, f"{name} is not mode 0600"
        assert metadata.st_uid == os.geteuid(), f"{name} is not owned by the runtime user"


def test_producer_fails_closed_on_empty_inventory(tmp_path: Path) -> None:
    """The producer still fails closed when an inventory is empty or missing
    at delivery time."""

    result, ownership_root = _fake_compose_harness(
        tmp_path,
        {},
    )
    # Baseline: the happy path succeeds and delivers content (sanity, not the
    # assertion under test — re-run with an empty quiescence proof below).
    assert result.returncode == 0, result.stderr

    tmp_path_empty = tmp_path / "empty-case"
    tmp_path_empty.mkdir()
    event_log = tmp_path_empty / "events.log"
    fake_bin = tmp_path_empty / "bin"
    fake_bin.mkdir()
    _install_writer_inventory_fixture(
        fake_bin,
        event_log,
        quiescence_inventory_content="",
    )
    ownership_root_empty = tmp_path_empty / "instance-ownership"
    ownership_root_empty.mkdir()
    harness = tmp_path_empty / "harness.sh"
    _write_executable(
        harness,
        "#!/usr/bin/env bash\n"
        "set -u\n"
        f"source '{INSTANCE_STATE_DEPLOYMENT_SH}'\n"
        "fake_compose() {\n"
        "  printf 'compose:%s\\n' \"$*\" >> \"$EVENT_LOG\"\n"
        "  if [ \"${1:-}\" = config ] && [ -n \"${DEPLOY_COMPOSE_FENCE_CONFIG_OUTPUT:-}\" ]; then\n"
        "    printf '%s\\n' 'services: {api: {depends_on: [db], labels: {com.agentic-pkm.mvr05.db-role: client}}, db: {labels: {com.agentic-pkm.mvr05.db-role: server}}, instance-state-init: {labels: {com.agentic-pkm.mvr05.db-role: fence-controller}}, migrate: {command: [/app/scripts/run_migrations.sh], depends_on: [db], labels: {com.agentic-pkm.mvr05.db-role: migration-runner}}}' > \"$DEPLOY_COMPOSE_FENCE_CONFIG_OUTPUT\"\n"
        "  fi\n"
        "  return 0\n"
        "}\n"
        "prepare_instance_state_deployment fake_compose prod\n",
    )
    empty_result = subprocess.run(
        ["bash", str(harness)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "EVENT_LOG": str(event_log),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "INSTANCE_OWNERSHIP_HOST_STATE_DIR": str(ownership_root_empty),
            "REAL_PYTHON3": _REAL_PYTHON3,
        },
        check=False,
    )

    assert empty_result.returncode != 0
    delivered = ownership_root_empty / "deployment-quiescence-inventory.json"
    assert not delivered.exists() or delivered.stat().st_size == 0
