"""Production migration reversibility gate coverage for Issue #5046."""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import yaml


class _ComposeLoader(yaml.SafeLoader):
    pass


def _construct_override(loader: _ComposeLoader, node: yaml.Node) -> object:
    return loader.construct_sequence(node)


def _construct_reset(loader: _ComposeLoader, node: yaml.Node) -> object:
    return None if node.value == "null" else loader.construct_object(node)


_ComposeLoader.add_constructor("!override", _construct_override)
_ComposeLoader.add_constructor("!reset", _construct_reset)


REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATION_SCRIPT = REPO_ROOT / "scripts" / "run_migrations.sh"
START_SCRIPT = REPO_ROOT / "scripts" / "start_full_system.sh"
PROD_COMPOSE = REPO_ROOT / "docker-compose.prod.yml"
DEV_COMPOSE = REPO_ROOT / "docker-compose.dev.yml"
TEST_COMPOSE = REPO_ROOT / "docker-compose.test.yml"
BASE_REVISION = "base0001"


def _make_fixture(
    tmp_path: Path,
    *,
    child: str,
    current_revision: str = "base0001",
) -> tuple[Path, Path, Path]:
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
        f'  *" current") printf "%s (head)\\n" "{current_revision}" ;;\n'
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
    gate_token_only: bool = False,
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
            "MIGRATION_GATE_TOKEN_ONLY": "1" if gate_token_only else "0",
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
    """The prod launcher delegates gate ownership to the prod overlay."""

    start_script = START_SCRIPT.read_text(encoding="utf-8")
    migration_script = MIGRATION_SCRIPT.read_text(encoding="utf-8")
    assert "_pkm_resolved_channel" in start_script
    assert "MIGRATION_PRODUCTION_GATE=1" not in start_script
    assert "MIGRATION_TARGET_IDENTITY=pkm-prod/app" not in start_script
    assert "channel-neutral" in start_script
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


def test_gate_token_only_mode_emits_token_without_running_upgrade(tmp_path: Path) -> None:
    root, _child_path, log_path = _make_fixture(
        tmp_path,
        child='reversibility = "forward-only"',
    )

    result = _run_migration(root, log_path, gate_token_only=True)

    assert result.returncode == 0, result.stderr
    assert re.fullmatch(r"prod-migration-ack\.v1:[0-9a-f]{64}\n?", result.stdout)
    assert "upgrade head" not in log_path.read_text(encoding="utf-8")


def test_gate_token_only_mode_fails_closed_without_forward_only_pending(
    tmp_path: Path,
) -> None:
    at_head_root, _child_path, at_head_log = _make_fixture(
        tmp_path / "at-head",
        child='reversibility = "forward-only"',
        current_revision="child0002",
    )
    at_head = _run_migration(at_head_root, at_head_log, gate_token_only=True)

    assert at_head.returncode == 78
    assert "token-only migration probe found no pending migration" in at_head.stderr
    assert "upgrade head" not in at_head_log.read_text(encoding="utf-8")

    reversible_root, _child_path, reversible_log = _make_fixture(
        tmp_path / "reversible",
        child='reversibility = "reversible"',
    )
    reversible = _run_migration(reversible_root, reversible_log, gate_token_only=True)

    assert reversible.returncode == 78
    assert (
        "token-only migration probe found no forward-only pending migration"
        in reversible.stderr
    )
    assert "upgrade head" not in reversible_log.read_text(encoding="utf-8")


def test_production_overlay_owns_gate_and_nonproduction_overlays_clear_stale_controls() -> None:
    prod_text = PROD_COMPOSE.read_text(encoding="utf-8")
    prod_migrate = yaml.load(prod_text, Loader=_ComposeLoader)["services"]["migrate"]
    prod_environment = prod_migrate["environment"]
    assert prod_environment["PKM_ENVIRONMENT"] == "prod"
    assert prod_environment["DATABASE_URL"] == "postgresql+psycopg://app:app@db:5432/app"
    assert prod_environment["DB_DSN"] == "postgresql+psycopg://app:app@db:5432/app"
    assert prod_environment["MIGRATION_PRODUCTION_GATE"] == "1"
    assert prod_environment["MIGRATION_TARGET_IDENTITY"] == "pkm-prod/app"
    assert prod_environment["PROD_MIGRATION_FORWARD_ONLY_ACK"] == (
        "${PROD_MIGRATION_FORWARD_ONLY_ACK:-}"
    )
    assert prod_environment["MIGRATION_GATE_TOKEN_ONLY"] == (
        "${DEPLOY_MIGRATION_GATE_TOKEN_ONLY:-0}"
    )

    # These stale values represent a runtime.env generated by an older prod
    # start. They are service env_file input only; the explicit prod mapping
    # must replace every control value before the container is created.
    stale_runtime = {
        "DATABASE_URL": "postgresql+psycopg://app:app@foreign-db:5432/app",
        "DB_DSN": "postgresql+psycopg://app:app@foreign-db:5432/app",
        "MIGRATION_PRODUCTION_GATE": "1",
        "MIGRATION_TARGET_IDENTITY": "pkm-prod/app",
        "MIGRATION_GATE_TOKEN_ONLY": "1",
        "PROD_MIGRATION_FORWARD_ONLY_ACK": "some-stale-value",
        "PKM_ENVIRONMENT": "prod",
    }
    effective = dict(stale_runtime)
    effective.update(
        {
            "PKM_ENVIRONMENT": prod_environment["PKM_ENVIRONMENT"],
            "DATABASE_URL": prod_environment["DATABASE_URL"],
            "DB_DSN": prod_environment["DB_DSN"],
            "MIGRATION_PRODUCTION_GATE": prod_environment["MIGRATION_PRODUCTION_GATE"],
            "MIGRATION_TARGET_IDENTITY": prod_environment["MIGRATION_TARGET_IDENTITY"],
            "MIGRATION_GATE_TOKEN_ONLY": "0",
            "PROD_MIGRATION_FORWARD_ONLY_ACK": "",
        }
    )
    assert effective["MIGRATION_PRODUCTION_GATE"] == "1"
    assert effective["DATABASE_URL"] == "postgresql+psycopg://app:app@db:5432/app"
    assert effective["DB_DSN"] == "postgresql+psycopg://app:app@db:5432/app"
    assert effective["MIGRATION_TARGET_IDENTITY"] == "pkm-prod/app"
    assert effective["MIGRATION_GATE_TOKEN_ONLY"] == "0"
    assert effective["PROD_MIGRATION_FORWARD_ONLY_ACK"] == ""

    for compose_path in (DEV_COMPOSE, TEST_COMPOSE):
        compose = yaml.load(compose_path.read_text(encoding="utf-8"), Loader=_ComposeLoader)
        migrate_environment = compose["services"]["migrate"]["environment"]
        expected_environment = "dev" if compose_path == DEV_COMPOSE else "test"
        assert migrate_environment["PKM_ENVIRONMENT"] == expected_environment
        nonproduction_effective = dict(stale_runtime)
        nonproduction_effective["PKM_ENVIRONMENT"] = migrate_environment["PKM_ENVIRONMENT"]
        assert nonproduction_effective["PKM_ENVIRONMENT"] == expected_environment
        text = compose_path.read_text(encoding="utf-8")
        assert 'MIGRATION_PRODUCTION_GATE: "0"' in text
        assert 'MIGRATION_GATE_TOKEN_ONLY: "0"' in text
        assert "MIGRATION_TARGET_IDENTITY: !reset null" in text
        assert "PROD_MIGRATION_FORWARD_ONLY_ACK: !reset null" in text


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


def test_gate_token_drift_between_probe_and_full_run_blocks_upgrade(tmp_path: Path) -> None:
    root, child_path, log_path = _make_fixture(
        tmp_path,
        child='reversibility = "forward-only"',
    )
    probe = _run_migration(root, log_path, gate_token_only=True)
    assert probe.returncode == 0, probe.stderr
    token = probe.stdout.strip()

    child_path.write_text(
        child_path.read_text(encoding="utf-8") + "# drift after pre-cutover probe\n",
        encoding="utf-8",
    )
    replayed = _run_migration(root, log_path, acknowledgement=token)

    assert replayed.returncode == 78, replayed.stderr
    assert "does not match the current target/migration decision" in replayed.stderr
    assert "upgrade head" not in log_path.read_text(encoding="utf-8")


def test_unclassified_pending_migration_fails_closed(tmp_path: Path) -> None:
    root, _child_path, log_path = _make_fixture(
        tmp_path,
        child="# no reversibility marker",
    )

    result = _run_migration(root, log_path)

    assert result.returncode == 78, result.stderr
    assert "unclassified pending migration" in result.stderr
    assert "upgrade head" not in log_path.read_text(encoding="utf-8")
