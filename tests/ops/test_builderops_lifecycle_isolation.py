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
  [ "$context" = builderops ] && printf 'builder-engine\n' || printf 'product-engine\n'
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
    assert "builderops_validate_recovery_target" in lib_text
    assert "scripts/deploy_channel.sh" not in deploy_text
    assert "pkm-" not in deploy_text


def test_failure_domain_preflight_rejects_product_project_on_builder_engine(
    tmp_path: Path,
) -> None:
    result = _run_contract(tmp_path, FAKE_BUILDER_PROJECTS='[{"Name":"pkm-prod"}]')
    assert result.returncode == 72
    assert "Product project detected on BuilderOps engine" in result.stderr


def test_failure_domain_preflight_rejects_same_context(tmp_path: Path) -> None:
    result = _run_contract(tmp_path, PRODUCT_DOCKER_CONTEXT="builderops")
    assert result.returncode == 70
    assert "contexts must differ" in result.stderr
