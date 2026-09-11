"""Production migration reversibility gate coverage for Issue #5046."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SCRIPT = REPO_ROOT / "scripts" / "run_migrations.sh"
START_SCRIPT = REPO_ROOT / "scripts" / "start_full_system.sh"
BASE_REVISION = "base0001"


def _make_fixture(tmp_path: Path, *, child: str) -> tuple[Path, Path, Path]:
    root = tmp_path / "fixture"
    versions = root / "app" / "alembic" / "versions"
    versions.mkdir(parents=True)
    (root / "app" / "alembic.ini").write_text("[alembic]\n", encoding="utf-8")
    (versions / "001_base.py").write_text(
        'revision = "base0001"\n'
        "down_revision = None\n"
        'reversibility = "reversible"\n',
        encoding="utf-8",
    )
    child_path = versions / "002_pending.py"
    child_path.write_text(
        'revision = "child0002"\n'
        'down_revision = "base0001"\n'
        f"{child}\n",
        encoding="utf-8",
    )

    fake_bin = root / "bin"
    fake_bin.mkdir()
    (fake_bin / "alembic").write_text(
        "#!/usr/bin/env bash\n"
        'printf "%s\\n" "$*" >> "$ALEMBIC_LOG"\n'
        'case "$*" in\n'
        '  *" current") printf "%s (head)\\n" "base0001" ;;\n'
        '  *" upgrade head") printf "upgrade\\n" >> "$ALEMBIC_LOG" ;;\n'
        "esac\n",
        encoding="utf-8",
    )
    (fake_bin / "alembic").chmod(0o755)
    return root, child_path, root / "alembic.log"


def _run_migration(
    root: Path,
    log_path: Path,
    *,
    acknowledgement: str | None = None,
    target: str = "pkm-prod/app",
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{root / 'bin'}{os.pathsep}{environment['PATH']}",
            "ALEMBIC_LOG": str(log_path),
            "DATABASE_URL": "",
            "DB_DSN": "postgresql+psycopg://app:app@db:5432/app",
            "LLM_PROVIDER": "mock",
            "MIGRATION_PRODUCTION_GATE": "1",
            "MIGRATION_TARGET_IDENTITY": target,
            "PYTHONPATH": f"{REPO_ROOT}{os.pathsep}{environment.get('PYTHONPATH', '')}",
        }
    )
    if acknowledgement is None:
        environment.pop("PROD_MIGRATION_FORWARD_ONLY_ACK", None)
    else:
        environment["PROD_MIGRATION_FORWARD_ONLY_ACK"] = acknowledgement
    return subprocess.run(
        ["bash", str(MIGRATION_SCRIPT)],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _acknowledgement_from(result: subprocess.CompletedProcess[str]) -> str:
    match = re.search(
        r"PROD_MIGRATION_FORWARD_ONLY_ACK=(prod-migration-ack\.v1:[0-9a-f]{64})",
        result.stderr,
    )
    assert match, result.stderr
    return match.group(1)


def test_prod_start_full_enforces_migration_gate_before_upgrade(tmp_path: Path) -> None:
    """The prod launcher wires the gate and refuses an unacknowledged upgrade."""

    start_script = START_SCRIPT.read_text(encoding="utf-8")
    migration_script = MIGRATION_SCRIPT.read_text(encoding="utf-8")
    assert 'if [ "$_pkm_resolved_channel" = "prod" ]; then' in start_script
    assert "MIGRATION_PRODUCTION_GATE=1" in start_script
    assert "MIGRATION_TARGET_IDENTITY=pkm-prod/app" in start_script
    assert start_script.index("MIGRATION_PRODUCTION_GATE=1") < start_script.index(
        "run_docker_compose up -d db"
    )
    assert migration_script.index("run_production_migration_gate") < migration_script.rindex(
        "alembic -c app/alembic.ini upgrade head"
    )

    root, _child_path, log_path = _make_fixture(
        tmp_path,
        child='reversibility = "forward-only"',
    )
    blocked = _run_migration(root, log_path)

    assert blocked.returncode == 78, blocked.stderr
    assert "forward-only migration(s) require explicit acknowledgement" in blocked.stderr
    assert "upgrade head" not in log_path.read_text(encoding="utf-8")

    acknowledgement = _acknowledgement_from(blocked)
    allowed = _run_migration(root, log_path, acknowledgement=acknowledgement)
    assert allowed.returncode == 0, allowed.stderr
    assert "upgrade head" in log_path.read_text(encoding="utf-8")


def test_forward_only_acknowledgement_is_target_bound(tmp_path: Path) -> None:
    """A decision token cannot cross either a target DB or migration change."""

    first_root, _first_child, first_log = _make_fixture(
        tmp_path / "first",
        child='reversibility = "forward-only"',
    )
    blocked = _run_migration(first_root, first_log)
    acknowledgement = _acknowledgement_from(blocked)

    wrong_target = _run_migration(
        first_root,
        first_log,
        acknowledgement=acknowledgement,
        target="pkm-prod/another-db",
    )
    assert wrong_target.returncode == 78
    assert "unexpected migration target identity" in wrong_target.stderr

    changed_root, changed_child, changed_log = _make_fixture(
        tmp_path / "changed",
        child='reversibility = "forward-only"',
    )
    changed_child.write_text(
        changed_child.read_text(encoding="utf-8") + "# changed migration decision\n",
        encoding="utf-8",
    )
    replayed = _run_migration(
        changed_root,
        changed_log,
        acknowledgement=acknowledgement,
    )
    assert replayed.returncode == 78
    assert "does not match the current target/migration decision" in replayed.stderr
    assert "upgrade head" not in changed_log.read_text(encoding="utf-8")


def test_unclassified_pending_migration_fails_closed(tmp_path: Path) -> None:
    root, _child_path, log_path = _make_fixture(
        tmp_path,
        child="# no reversibility marker",
    )

    result = _run_migration(root, log_path)

    assert result.returncode == 78, result.stderr
    assert "unclassified pending migration" in result.stderr
    assert "upgrade head" not in log_path.read_text(encoding="utf-8")
