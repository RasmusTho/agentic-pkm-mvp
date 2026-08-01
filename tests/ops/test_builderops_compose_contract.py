from __future__ import annotations

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
    assert set(services) == {"db", "migrate", "api", "worker", "backup"}
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
        "./scripts/builderops/wal_archive.sh:/app/scripts/builderops/wal_archive.sh:ro",
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
    assert services["backup"]["profiles"] == ["ops"]
    assert services["backup"]["restart"] == "no"
    assert "builderops-pgdata:/var/lib/postgresql/data:ro" in services["backup"]["volumes"]
    assert services["backup"]["environment"]["PGPASSWORD_FILE"].startswith("/run/secrets/")

    assert services["api"]["ports"] == ["127.0.0.1:${BUILDEROPS_API_PORT:-18100}:8000"]
    assert services["db"].get("ports") is None
    assert compose["networks"]["builderops-internal"]["internal"] is True
    assert compose["networks"]["builderops-recovery-egress"].get("internal") is not True
    assert services["db"]["networks"] == [
        "builderops-internal",
        "builderops-recovery-egress",
    ]
    assert services["backup"]["networks"] == [
        "builderops-internal",
        "builderops-recovery-egress",
    ]
    for name in ("migrate", "api", "worker"):
        assert services[name]["networks"] == ["builderops-internal"]

    secret_names = set(compose["secrets"])
    assert {
        "builderops_database_owner_password",
        "builderops_database_owner_url",
        "builderops_database_app_password",
        "builderops_database_url",
        "builderops_api_credentials",
        "builderops_executor_credentials",
        "builderops_recovery_target",
        "builderops_probe_token",
        "builderops_wal_access_key_id",
        "builderops_wal_secret_access_key",
        "builderops_wal_encryption_key",
    } <= secret_names
    assert "API_KEY" not in text
    assert "/Users:/Users" not in text
    assert "/Volumes:/Volumes" not in text
    assert "runtime/dispatcher" not in text


def test_builderops_postgres_listens_on_the_internal_network() -> None:
    conf = (ROOT / "config/builderops/postgresql.conf").read_text(encoding="utf-8")
    assert "listen_addresses = '*'" in conf
    assert "internal: true" in conf


def test_builderops_db_healthcheck_probes_the_container_network_address() -> None:
    compose = _compose()
    test_cmd = compose["services"]["db"]["healthcheck"]["test"][-1]
    assert "127.0.0.1" not in test_cmd
    assert "hostname -i" in test_cmd
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


def test_builderops_postgres_pin_has_an_exact_restore_checked_image_producer() -> None:
    dockerfile = (ROOT / "Dockerfile.builderops-postgres").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/app-image-build.yml").read_text(encoding="utf-8")

    assert "FROM postgres:16-bookworm" in dockerfile
    assert "WAL_G_VERSION=v3.0.8" in dockerfile
    assert "sha256sum -c" in dockerfile
    assert "wal-g-pg-20.04-amd64" not in dockerfile
    assert "wal_g_arch=amd64" in dockerfile
    assert "wal_g_arch=aarch64" in dockerfile
    assert "Dockerfile.builderops-postgres" in workflow
    assert "builderops-postgres:${GITHUB_SHA}" in workflow
    assert "platforms: linux/amd64" in workflow
    assert "Prove encrypted full-backup plus archived-WAL restore" in workflow
    assert "Publish the exact restore-proved BuilderOps images" in workflow
    publish = workflow.split("Publish the exact restore-proved BuilderOps images", maxsplit=1)[1]
    assert "docker build" not in publish
    assert 'docker push "${{ steps.images.outputs.postgres }}"' in publish
    assert "docker run --rm --entrypoint wal-g" in workflow
