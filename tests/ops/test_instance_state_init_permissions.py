from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
PERMISSION_SCRIPT = REPO_ROOT / "scripts/prepare_instance_state_permissions.sh"


def _private_root(root: Path) -> None:
    root.mkdir(mode=0o700)
    (root / "nested").mkdir(mode=0o700)
    state_file = root / "nested" / "state.json"
    state_file.write_text("{}\n", encoding="utf-8")
    state_file.chmod(0o600)


def _fake_chown(path: Path, *, exit_code: int) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "printf '%s\\n' called >> \"${CHOWN_MARKER:?}\"\n"
        f"exit {exit_code}\n",
        encoding="utf-8",
    )
    path.chmod(0o755)


def _run_permission_script(
    roots: list[Path],
    *,
    fake_bin: Path | None = None,
    marker: Path | None = None,
    uid: int | None = None,
    gid: int | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "LOCAL_UID": str(os.getuid() if uid is None else uid),
            "LOCAL_GID": str(os.getgid() if gid is None else gid),
        }
    )
    if fake_bin is not None:
        env["PATH"] = f"{fake_bin}:{env['PATH']}"
    if marker is not None:
        env["CHOWN_MARKER"] = str(marker)
    return subprocess.run(
        ["bash", str(PERMISSION_SCRIPT), *(str(root) for root in roots)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_matching_private_roots_skip_redundant_chown(tmp_path: Path) -> None:
    roots = [tmp_path / "instance-state", tmp_path / "instance-ownership"]
    for root in roots:
        _private_root(root)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "chown-called"
    _fake_chown(fake_bin / "chown", exit_code=77)

    result = _run_permission_script(roots, fake_bin=fake_bin, marker=marker)

    assert result.returncode == 0, result.stdout + result.stderr
    assert not marker.exists()
    assert all(stat.S_IMODE(root.stat().st_mode) == 0o700 for root in roots)


def test_mismatched_roots_fail_closed_when_chown_fails(tmp_path: Path) -> None:
    roots = [tmp_path / "instance-state", tmp_path / "instance-ownership"]
    for root in roots:
        _private_root(root)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "chown-called"
    _fake_chown(fake_bin / "chown", exit_code=42)
    result = _run_permission_script(
        roots,
        fake_bin=fake_bin,
        marker=marker,
        uid=os.getuid() + 1,
    )

    assert result.returncode == 42
    assert marker.read_text(encoding="utf-8").splitlines() == ["called"]


def test_compose_and_dockerfile_wire_permission_helper() -> None:
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yaml").read_text())
    command = compose["services"]["instance-state-init"]["command"]

    assert command == [
        "/bin/bash",
        "-c",
        "bash /app/scripts/prepare_instance_state_permissions.sh /app/instance-state /app/instance-ownership",
    ]

    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "scripts/prepare_instance_state_permissions.sh" in dockerfile
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "!scripts/prepare_instance_state_permissions.sh" in dockerignore
    assert "RUN chmod +x scripts/start_api.sh scripts/run_migrations.sh \\\n    scripts/prepare_instance_state_permissions.sh" in dockerfile
