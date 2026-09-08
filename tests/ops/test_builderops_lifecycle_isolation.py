from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LIB = ROOT / "scripts/lib/builderops_compose.sh"


def _fake_docker(tmp_path: Path) -> tuple[Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "docker.log"
    docker = bin_dir / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -eu
printf '%s\n' "$*" >> "$FAKE_DOCKER_LOG"
context=""
if [ "${1:-}" = "--context" ]; then context="$2"; shift 2; fi
if [ "${1:-}" = "info" ]; then
  [ "$context" = builderops ] && printf '799a3d86-54f6-4208-b71a-36ae3eee61b6\n' || printf '2cae4764-d613-484d-b63d-0d353d5eab7c\n'
  exit 0
fi
if [ "${1:-}" = compose ] && [ "${2:-}" = ls ]; then
  [ "$context" = builderops ] && printf '%s\n' "${FAKE_BUILDER_PROJECTS:-[]}" || printf '%s\n' "${FAKE_PRODUCT_PROJECTS:-[]}"
  exit 0
fi
exit 0
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    return bin_dir, log


def _run_contract(tmp_path: Path, **overrides: str) -> subprocess.CompletedProcess[str]:
    bin_dir, log = _fake_docker(tmp_path)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "FAKE_DOCKER_LOG": str(log),
            "BUILDEROPS_DOCKER_CONTEXT": "builderops",
            "PRODUCT_DOCKER_CONTEXT": "default",
            **overrides,
        }
    )
    return subprocess.run(
        ["bash", "-c", f"source {LIB!s}; builderops_assert_failure_domain"],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_product_and_builderops_start_stop_independently(tmp_path: Path) -> None:
    result = _run_contract(tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr

    lib_text = LIB.read_text(encoding="utf-8")
    deploy_text = (ROOT / "scripts/deploy_builderops.sh").read_text(encoding="utf-8")
    assert "-p builderops-control-plane" in lib_text
    assert "docker-compose.builderops.yml" in lib_text
    assert "docker-compose.yaml" not in lib_text
    assert "builderops_validate_recovery_target" not in lib_text
    assert "recovery target" not in deploy_text.lower()
    assert "assert_local_durability_posture" in deploy_text
    assert "scripts/deploy_channel.sh" not in deploy_text
    assert "COMPOSE_PROJECT_NAME=pkm-" not in deploy_text


def test_failure_domain_preflight_rejects_product_project_on_builder_engine(
    tmp_path: Path,
) -> None:
    result = _run_contract(tmp_path, FAKE_BUILDER_PROJECTS='[{"Name":"pkm-prod"}]')
    assert result.returncode == 72
    assert "Product project detected on BuilderOps engine" in result.stderr


def test_failure_domain_preflight_decodes_product_project_names_before_boundary_check(
    tmp_path: Path,
) -> None:
    result = _run_contract(tmp_path, FAKE_BUILDER_PROJECTS='[{"Name":"\\u0070km-prod"}]')
    assert result.returncode == 72
    assert "Product project detected on BuilderOps engine" in result.stderr


def test_failure_domain_preflight_rejects_noncanonical_engine_ids(tmp_path: Path) -> None:
    for engine_id in ("builder-engine", "f" * 36, "00000000-0000-0000-0000-000000000000"):
        result = subprocess.run(
            ["bash", "-c", f"source {LIB!s}; builderops_valid_engine_id \"$1\"", "bash", engine_id],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0


def test_failure_domain_preflight_rejects_same_context(tmp_path: Path) -> None:
    result = _run_contract(tmp_path, PRODUCT_DOCKER_CONTEXT="builderops")
    assert result.returncode == 70
    assert "contexts must differ" in result.stderr
