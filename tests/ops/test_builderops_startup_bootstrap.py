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
    assert 'PKM_ENVIRONMENT:-}" = "dev"' in start_script


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
    assert payload["builderops"]["wrapper"] == "scripts/builderops_cli.sh"
    assert payload["builderops"]["status"] in {"ok", "degraded"}
    if payload["builderops"]["status"] == "degraded":
        assert payload["builderops"]["reason"] == "builderops_readiness_failed"
        assert "builderops_readiness_failed" in payload["reasons"]

    status_payload = json.loads(startup_status.read_text(encoding="utf-8"))
    assert status_payload["builderops_bootstrap"]["status"] == "degraded"
    assert json.loads(builderops_status.read_text(encoding="utf-8")) == payload
