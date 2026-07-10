from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_dev_start_full_invokes_builderops_bootstrap() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    start_script = (REPO_ROOT / "scripts" / "start_full_system.sh").read_text(encoding="utf-8")

    dev_target = makefile[makefile.index("dev-start-full:") : makefile.index("# Canonical dev/Niflheim")]
    assert 'PKM_ENVIRONMENT="dev"' in dev_target
    assert "scripts/start_full_system.sh" in dev_target
    assert "scripts/start_builderops_services.sh" in start_script
    assert "builderops_bootstrap" in start_script
    compose = (REPO_ROOT / "docker-compose.yaml").read_text(encoding="utf-8")
    assert "DISPATCHER_HOST_STATE_DIR" in compose
    assert "${DISPATCHER_HOST_STATE_DIR:-./runtime/dispatcher}" in compose


def test_prod_start_full_invokes_builderops_bootstrap() -> None:
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    prod_wrapper = (REPO_ROOT / "scripts" / "prod" / "start_midgard_stack.sh").read_text(encoding="utf-8")
    start_script = (REPO_ROOT / "scripts" / "start_full_system.sh").read_text(encoding="utf-8")

    prod_target = makefile[makefile.index("prod-start-full:") : makefile.index("test-start-full:")]
    assert 'PKM_ENVIRONMENT="prod"' in prod_target
    assert "bash scripts/prod/start_midgard_stack.sh" in prod_target
    assert "exec scripts/start_full_system.sh" in prod_wrapper
    assert "scripts/start_builderops_services.sh" in start_script
    assert "builderops_bootstrap" in start_script


def test_builderops_bootstrap_environment_guard_covers_dev_and_prod_only() -> None:
    start_script = (REPO_ROOT / "scripts" / "start_full_system.sh").read_text(encoding="utf-8")

    guard = start_script[
        start_script.index("builderops_bootstrap_environment=") : start_script.index(
            "unset builderops_bootstrap_environment"
        )
    ]
    assert "dev|prod)" in guard
    assert "test)" not in guard
    assert "scripts/start_builderops_services.sh" in guard


def test_builderops_bootstrap_degrades_without_github_access(tmp_path: Path) -> None:
    startup_status = tmp_path / "startup_status.json"
    builderops_status = tmp_path / "builderops_status.json"
    missing_gh = tmp_path / "missing-gh"
    env = os.environ.copy()
    env.update(
        {
            "PYTHON": sys.executable,
            "DISPATCHER_STATE_DIR": str(tmp_path / "dispatcher"),
            "DISPATCHER_DB_PATH": str(tmp_path / "dispatcher" / "dispatcher.sqlite3"),
            "DISPATCHER_EVENTS_PATH": str(tmp_path / "dispatcher" / "events.jsonl"),
            "SIGNBOARD_ROOT": str(tmp_path / "signboard"),
            "BUILDEROPS_DB_PATH": str(tmp_path / "builderops" / "builderops.sqlite3"),
        }
    )

    result = subprocess.run(
        [
            str(REPO_ROOT / "scripts" / "start_builderops_services.sh"),
            "--repo",
            "RasmusTho/agentic-pkm-mvp",
            "--gh-bin",
            str(missing_gh),
            "--startup-status-path",
            str(startup_status),
            "--status-output",
            str(builderops_status),
            "--json",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["status"] == "degraded"
    assert "gh_not_found" in payload["reasons"]
    assert payload["dispatcher"]["db_exists"] is True
    assert payload["signboard"]["status"] == "ok"
    assert payload["signboard"]["count"] == 0
    assert (tmp_path / "signboard" / "Ready").is_dir()
    assert payload["builderops"]["wrapper"] == "scripts/builderops_cli.sh"
    assert payload["builderops"]["status"] in {"ok", "degraded"}
    if payload["builderops"]["status"] == "degraded":
        assert payload["builderops"]["reason"] == "builderops_readiness_failed"
        assert "builderops_readiness_failed" in payload["reasons"]

    status_payload = json.loads(startup_status.read_text(encoding="utf-8"))
    assert status_payload["builderops_bootstrap"]["status"] == "degraded"
    assert json.loads(builderops_status.read_text(encoding="utf-8")) == payload
