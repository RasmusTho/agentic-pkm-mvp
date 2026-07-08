from __future__ import annotations

import subprocess
from pathlib import Path

from app.release_channels.cutover_readiness import (
    check_cutover_readiness,
)


TARGET_SHA = "314632235404cae1c51dc92b5f37174aa02b5fb0"
OTHER_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def _write_base_fixture(root: Path, *, include_all_services: bool = True) -> None:
    (root / "config" / "deploy").mkdir(parents=True)
    (root / "config" / "deploy" / "prod.env").write_text(
        f"APP_IMAGE_TAG={TARGET_SHA}\n",
        encoding="utf-8",
    )
    (root / "config" / "runtime.defaults.env").parent.mkdir(parents=True, exist_ok=True)
    (root / "config" / "runtime.defaults.env").write_text(
        "\n".join(
            [
                "HEIMDAL_RAW_READ_ALLOWLIST=reader",
                "EMBED_PROFILE=bge-m3",
                "COMPANION_TRUSTED_PROXY_HOSTS=172.18.0.0/24",
                "DATABASE_URL=postgresql+psycopg://app:app@db:5432/app",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    services = ["api", "worker", "watcher", "heimdal-capture-watch", "companion-ui"]
    if not include_all_services:
        services.remove("heimdal-capture-watch")
    body = ["services:"]
    for service in services:
        body.extend(
            [
                f"  {service}:",
                "    image: ghcr.io/rasmustho/pkm-app:${APP_IMAGE_TAG}",
                "    env_file:",
                "      - ./config/runtime.defaults.env",
                "    environment:",
                "      PKM_ENVIRONMENT: prod",
            ]
        )
    (root / "docker-compose.yaml").write_text("\n".join(body) + "\n", encoding="utf-8")
    (root / "docker-compose.prod.yml").write_text("services: {}\n", encoding="utf-8")
    _write_migration(
        root,
        filename="001_base.py",
        revision="001",
        down_revision=None,
        reversibility="reversible",
    )


def _write_migration(
    root: Path,
    *,
    filename: str,
    revision: str,
    down_revision: str | None,
    reversibility: str,
) -> None:
    versions = root / "app" / "alembic" / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    down = "None" if down_revision is None else repr(down_revision)
    (versions / filename).write_text(
        "\n".join(
            [
                f"revision = {revision!r}",
                f"down_revision = {down}",
                f"reversibility = {reversibility!r}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _runner(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    command = " ".join(args)
    forbidden = ("pull", "up", "rm", "run", "compose")
    assert not any(word in args for word in forbidden), command
    if args[:3] == ["git", "cat-file", "-e"]:
        return subprocess.CompletedProcess(args, 0, "", "")
    if args[:3] == ["git", "merge-base", "--is-ancestor"]:
        return subprocess.CompletedProcess(args, 0, "", "")
    if args[:3] == ["docker", "image", "inspect"]:
        return subprocess.CompletedProcess(args, 1, "", "not local")
    if args[:3] == ["docker", "manifest", "inspect"]:
        return subprocess.CompletedProcess(args, 0, "{}", "")
    if args[:3] == ["alembic", "-c", "alembic.ini"]:
        return subprocess.CompletedProcess(args, 0, "001 (head)\n", "")
    raise AssertionError(f"unexpected command: {command}")


def test_missing_required_env_named_in_failure(tmp_path: Path) -> None:
    _write_base_fixture(tmp_path)
    runtime_env = tmp_path / "config" / "runtime.defaults.env"
    runtime_env.write_text(
        "\n".join(
            [
                "EMBED_PROFILE=bge-m3",
                "COMPANION_TRUSTED_PROXY_HOSTS=172.18.0.0/24",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = check_cutover_readiness(
        "prod",
        TARGET_SHA,
        root=tmp_path,
        db_revision="001",
        runner=_runner,
    )

    assert not result.ok
    assert "HEIMDAL_RAW_READ_ALLOWLIST" in result.summary()


def test_incomplete_recreate_set_fails(tmp_path: Path) -> None:
    _write_base_fixture(tmp_path, include_all_services=False)

    result = check_cutover_readiness(
        "prod",
        TARGET_SHA,
        root=tmp_path,
        db_revision="001",
        runner=_runner,
    )

    assert not result.ok
    assert "heimdal-capture-watch" in result.summary()


def test_deploy_pin_mismatch_fails_with_pin_and_target(tmp_path: Path) -> None:
    _write_base_fixture(tmp_path)
    (tmp_path / "config" / "deploy" / "prod.env").write_text(
        f"APP_IMAGE_TAG={OTHER_SHA}\n",
        encoding="utf-8",
    )

    result = check_cutover_readiness(
        "prod",
        TARGET_SHA,
        root=tmp_path,
        db_revision="001",
        runner=_runner,
    )

    summary = result.summary()
    assert not result.ok
    assert "deploy pin mismatch" in summary
    assert f"APP_IMAGE_TAG={OTHER_SHA}" in summary
    assert f"target-sha={TARGET_SHA}" in summary


def test_pending_forward_only_migrations_listed_and_gated(tmp_path: Path) -> None:
    _write_base_fixture(tmp_path)
    _write_migration(
        tmp_path,
        filename="002_forward_only.py",
        revision="002",
        down_revision="001",
        reversibility="forward-only",
    )
    _write_migration(
        tmp_path,
        filename="003_reversible.py",
        revision="003",
        down_revision="002",
        reversibility="reversible",
    )

    result = check_cutover_readiness(
        "prod",
        TARGET_SHA,
        root=tmp_path,
        db_revision="001",
        runner=_runner,
    )

    assert not result.ok
    assert result.pending_migrations == ("002_forward_only.py", "003_reversible.py")
    assert result.pending_forward_only_migrations == ("002_forward_only.py",)
    assert "002_forward_only.py" in result.summary()


def test_read_only_and_no_secret_values_in_output(tmp_path: Path) -> None:
    _write_base_fixture(tmp_path)
    secret = "super-secret-allowlist-value"
    runtime_env = tmp_path / "config" / "runtime.defaults.env"
    before = runtime_env.read_text(encoding="utf-8")
    runtime_env.write_text(before + f"SECRET_SENTINEL={secret}\n", encoding="utf-8")
    expected_after = runtime_env.read_text(encoding="utf-8")

    result = check_cutover_readiness(
        "prod",
        TARGET_SHA,
        root=tmp_path,
        db_revision="001",
        runner=_runner,
    )

    assert result.ok, result.summary()
    assert runtime_env.read_text(encoding="utf-8") == expected_after
    assert secret not in result.summary()
    assert "reader" not in result.summary()
