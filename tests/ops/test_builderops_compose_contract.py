from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.builderops.yml"


class _ComposeLoader(yaml.SafeLoader):
    pass


_ComposeLoader.add_constructor("!override", lambda loader, node: loader.construct_sequence(node))


def _compose() -> dict[str, object]:
    return yaml.load(COMPOSE.read_text(encoding="utf-8"), Loader=_ComposeLoader)


def test_builderops_compose_is_lifecycle_isolated() -> None:
    compose = _compose()
    text = COMPOSE.read_text(encoding="utf-8")
    services = compose["services"]

    assert compose["name"] == "builderops-control-plane"
    assert set(services) == {"db", "migrate", "api", "worker"}
    assert "docker-compose.yaml" not in text
    assert "pkm-dev" not in text
    assert "pkm-test" not in text
    assert "pkm-prod" not in text
    assert "APP_IMAGE_TAG" not in text
    assert "BUILDEROPS_IMAGE_DIGEST" in text
    assert "@${BUILDEROPS_IMAGE_DIGEST" in text

    db = services["db"]
    assert db["environment"]["POSTGRES_DB"] == "builderops"
    assert db["environment"]["POSTGRES_USER"] == "builderops_owner"
    assert db["volumes"] == [
        "builderops-pgdata:/var/lib/postgresql/data",
        "./config/builderops/postgresql.conf:/etc/postgresql/builderops-postgresql.conf:ro",
        "./scripts/builderops/local_wal_guard.sh:/app/scripts/builderops/local_wal_guard.sh:ro",
        "./scripts/builderops/init_roles.sh:/docker-entrypoint-initdb.d/10-builderops-roles.sh:ro",
    ]
    assert compose["volumes"]["builderops-pgdata"] == {
        "external": True,
        "name": "builderops-control-plane_pgdata",
    }
    assert set(compose["volumes"]) == {"builderops-pgdata"}

    assert services["migrate"]["restart"] == "no"
    for name in ("api", "worker"):
        dependencies = services[name]["depends_on"]
        assert dependencies["db"]["condition"] == "service_healthy"
        assert dependencies["migrate"]["condition"] == "service_completed_successfully"
    assert services["api"]["ports"] == ["127.0.0.1:${BUILDEROPS_API_PORT:-18100}:8000"]
    assert services["db"].get("ports") is None
    assert compose["networks"]["builderops-internal"]["internal"] is True
    for name in ("db", "migrate", "api", "worker"):
        assert services[name]["networks"] == ["builderops-internal"]

    secret_names = set(compose["secrets"])
    assert {
        "builderops_database_owner_password",
        "builderops_database_owner_url",
        "builderops_database_app_password",
        "builderops_database_url",
        "builderops_api_credentials",
        "builderops_executor_credentials",
        "builderops_probe_token",
    } <= secret_names
    assert "API_KEY" not in text
    assert "/Users:/Users" not in text
    assert "/Volumes:/Volumes" not in text
    assert "runtime/dispatcher" not in text


def test_local_control_plane_disables_wal_archiving_without_recovery_egress() -> None:
    compose = _compose()
    db = compose["services"]["db"]
    config = (ROOT / "config/builderops/postgresql.conf").read_text(encoding="utf-8")

    assert "archive_mode = off" in config
    assert "archive_command = ''" in config
    assert "wal_archive.sh" not in str(db)
    assert "WALG_S3_PREFIX" not in db["environment"]
    assert "builderops-recovery-egress" not in compose["networks"]
    assert all("wal_" not in secret for secret in compose["secrets"])
    assert "builderops_recovery_target" not in compose["secrets"]
    assert "BUILDEROPS_RECOVERY_TARGET_FILE" not in compose["services"]["api"]["environment"]
    assert compose["services"]["api"]["environment"]["BUILDEROPS_LOCAL_DURABILITY_MODE"] == "${BUILDEROPS_LOCAL_DURABILITY_MODE:?Local BuilderOps durability mode is required}"


def test_rebuildable_candidate_path_has_no_backup_or_restore_gate() -> None:
    dockerfile = (ROOT / "Dockerfile.builderops-postgres").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/app-image-build.yml").read_text(encoding="utf-8")
    receipt_writer = (ROOT / "scripts/builderops/write_candidate_pair_receipt.py").read_text(
        encoding="utf-8"
    )

    assert "wal-g" not in dockerfile.lower()
    assert "restore" not in workflow.lower()
    assert "backup" not in workflow.lower()
    assert '"durability_posture": "rebuildable"' in receipt_writer
    assert "restore_gate" not in receipt_writer
    for script_name in ("backup.sh", "restore_drill.sh", "wal_archive.sh", "real_restore_selftest.sh"):
        assert not (ROOT / "scripts/builderops" / script_name).exists()


def test_builderops_postgres_listens_on_the_internal_network() -> None:
    conf = (ROOT / "config/builderops/postgresql.conf").read_text(encoding="utf-8")
    assert "listen_addresses = '*'" in conf
    assert "internal: true" in conf


def test_builderops_db_healthcheck_probes_the_container_network_address() -> None:
    compose = _compose()
    test_cmd = compose["services"]["db"]["healthcheck"]["test"][-1]
    assert "127.0.0.1" not in test_cmd
    assert "hostname -i" in test_cmd
    assert "local_wal_guard.sh" in test_cmd
    assert "pg_isready" in test_cmd


def test_builderops_image_has_a_dedicated_non_root_entrypoint() -> None:
    dockerfile = (ROOT / "Dockerfile.builderops").read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in dockerfile
    assert "USER builderops" in dockerfile
    assert "app.builderops.control_plane.service:production_app" in dockerfile
    assert '"--factory"' in dockerfile
    assert "requirements-tts" not in dockerfile
    assert "ffmpeg" not in dockerfile

    roles = (ROOT / "scripts/builderops/init_roles.sh").read_text(encoding="utf-8")
    assert "builderops_app" in roles
    assert "ALTER DEFAULT PRIVILEGES FOR ROLE builderops_owner" in roles
    assert "BUILDEROPS_DATABASE_APP_PASSWORD_FILE" in roles
    assert "PASSWORD %L" in roles


def test_builderops_init_stages_only_app_password_for_postgres() -> None:
    compose = _compose()
    db = compose["services"]["db"]
    environment = db["environment"]
    dockerfile = (ROOT / "Dockerfile.builderops-postgres").read_text(encoding="utf-8")
    entrypoint = (ROOT / "scripts/builderops/postgres_entrypoint.sh").read_text(
        encoding="utf-8"
    )
    roles = (ROOT / "scripts/builderops/init_roles.sh").read_text(encoding="utf-8")

    assert environment["BUILDEROPS_DATABASE_APP_PASSWORD_FILE"] == (
        "/run/builderops-init/app-password"
    )
    assert "BUILDEROPS_DATABASE_APP_PASSWORD_SECRET_FILE" not in environment
    assert db["secrets"] == [
        "builderops_database_owner_password",
        "builderops_database_app_password",
    ]
    assert db["tmpfs"] == ["/run/builderops-init:uid=999,gid=999,mode=0700"]
    assert all(
        "builderops_database_app_password" not in service.get("secrets", [])
        for name, service in compose["services"].items()
        if name != "db"
    )

    assert "COPY scripts/builderops/postgres_entrypoint.sh /usr/local/bin/" in dockerfile
    assert 'ENTRYPOINT ["/usr/local/bin/builderops-postgres-entrypoint.sh"]' in dockerfile
    dockerignore = (ROOT / ".dockerignore").read_text(encoding="utf-8")
    assert "!scripts/builderops" in dockerignore
    assert "!scripts/builderops/postgres_entrypoint.sh" in dockerignore
    assert 'readonly source_secret="/run/secrets/builderops_database_app_password"' in entrypoint
    assert "BUILDEROPS_DATABASE_APP_PASSWORD_FILE" in entrypoint
    assert '"$(id -u)" -eq 0' in entrypoint
    assert "PG_VERSION" in entrypoint
    assert 'staged_directory="/run/builderops-init"' in entrypoint
    assert "stat -c '%u:%a'" in entrypoint
    assert '"0:600"' in entrypoint
    assert "/proc/mounts" in entrypoint
    assert '"tmpfs"' in entrypoint
    assert "install -m 0400 -o postgres -g postgres" in entrypoint
    assert 'exec /usr/local/bin/docker-entrypoint.sh "$@"' in entrypoint
    assert ".builderops-app-role-init-pending" in entrypoint
    assert ".builderops-app-role-init-ready" in entrypoint

    assert "trap cleanup EXIT" in roles
    assert 'rm -f -- "$BUILDEROPS_DATABASE_APP_PASSWORD_FILE"' in roles
    assert "BEGIN;" in roles and "COMMIT;" in roles


def test_builderops_init_secret_staging_refuses_bad_inputs_and_cleans_up(tmp_path: Path) -> None:
    entrypoint = ROOT / "scripts/builderops/postgres_entrypoint.sh"
    roles = ROOT / "scripts/builderops/init_roles.sh"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    event_log = tmp_path / "events.log"
    source_secret = tmp_path / "app-password-source"
    source_secret.write_text("not-a-real-secret\n", encoding="utf-8")
    staged_secret = tmp_path / "app-password-staged"
    entrypoint_copy = tmp_path / "postgres_entrypoint.sh"
    entrypoint_copy.write_text(
        entrypoint.read_text(encoding="utf-8").replace(
            'readonly source_secret="/run/secrets/builderops_database_app_password"',
            f'readonly source_secret="{source_secret}"',
        ), encoding="utf-8"
    )

    _write_executable(bin_dir / "id", "#!/usr/bin/env bash\nprintf '0\\n'\n")
    _write_executable(
        bin_dir / "awk",
        "#!/usr/bin/env bash\n[ \"${TEST_TMPFS:-1}\" = 1 ]\n",
    )
    _write_executable(
        bin_dir / "stat",
        "#!/usr/bin/env bash\nprintf '%s\\n' \"${TEST_SECRET_STAT:-0:600}\"\n",
    )
    _write_executable(
        bin_dir / "install",
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$*\" >> \"$TEST_EVENT_LOG\"\n",
    )
    _write_executable(bin_dir / "psql", "#!/usr/bin/env bash\nexit 1\n")

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "TEST_EVENT_LOG": str(event_log),
            "BUILDEROPS_DATABASE_APP_PASSWORD_FILE": "/run/builderops-init/app-password",
        }
    )

    success = _run_staging_function(entrypoint_copy, env)
    assert success.returncode == 0, success.stderr
    events = event_log.read_text(encoding="utf-8")
    assert "-d -m 0700 -o postgres -g postgres /run/builderops-init" in events
    assert (
        f"-m 0400 -o postgres -g postgres {source_secret} /run/builderops-init/app-password"
        in events
    )

    event_log.unlink()
    missing_copy = tmp_path / "missing_source_entrypoint.sh"
    missing_copy.write_text(entrypoint_copy.read_text(encoding="utf-8").replace(str(source_secret), str(tmp_path / "missing")), encoding="utf-8")
    missing = _run_staging_function(missing_copy, env)
    assert missing.returncode == 78
    assert not event_log.exists()

    non_root_source = env | {"TEST_SECRET_STAT": "1000:600"}
    non_root = _run_staging_function(entrypoint_copy, non_root_source)
    assert non_root.returncode == 78
    assert not event_log.exists()

    group_readable_source = env | {"TEST_SECRET_STAT": "0:640"}
    group_readable = _run_staging_function(entrypoint_copy, group_readable_source)
    assert group_readable.returncode == 78
    assert not event_log.exists()

    wrong_target = env | {"BUILDEROPS_DATABASE_APP_PASSWORD_FILE": str(tmp_path / "not-tmpfs")}
    wrong = _run_staging_function(entrypoint_copy, wrong_target)
    assert wrong.returncode == 78
    assert not event_log.exists()

    absent_tmpfs = env | {"TEST_TMPFS": "0"}
    no_tmpfs = _run_staging_function(entrypoint_copy, absent_tmpfs)
    assert no_tmpfs.returncode == 78
    assert not event_log.exists()

    staged_secret.write_text("not-a-real-secret\n", encoding="utf-8")
    cleanup = subprocess.run(
        ["bash", str(roles)],
        env=env
        | {
            "BUILDEROPS_DATABASE_APP_PASSWORD_FILE": str(staged_secret),
            "POSTGRES_USER": "builderops_owner",
            "POSTGRES_DB": "builderops",
            "PGDATA": str(tmp_path / "pgdata"),
        },
        check=False,
        capture_output=True,
        text=True,
    )
    assert cleanup.returncode == 1
    assert not staged_secret.exists()


def _run_staging_function(
    entrypoint: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", "-c", 'source "$1"; stage_app_password', "_", str(entrypoint)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def test_builderops_postgres_pin_has_a_rebuildable_candidate_producer() -> None:
    dockerfile = (ROOT / "Dockerfile.builderops-postgres").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/app-image-build.yml").read_text(encoding="utf-8")

    assert "FROM postgres:16-bookworm" in dockerfile
    assert 'org.opencontainers.image.durability="rebuildable"' in dockerfile
    assert "wal-g" not in dockerfile.lower()
    assert "Dockerfile.builderops-postgres" in workflow
    assert "builderops-postgres:${GITHUB_SHA}" in workflow
    assert "platforms: linux/amd64" in workflow
    assert "Publish the exact rebuildable BuilderOps images" in workflow
    publish = workflow.split("Publish the exact rebuildable BuilderOps images", maxsplit=1)[1]
    assert "docker build" not in publish
    assert 'docker push "${{ steps.images.outputs.postgres }}"' in publish
    assert "wal-g" not in workflow.lower()
