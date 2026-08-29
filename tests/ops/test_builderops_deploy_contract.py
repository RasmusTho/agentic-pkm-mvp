from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


class _ComposeLoader(yaml.SafeLoader):
    """Load the Compose-only !override tag as its wrapped value for contract checks."""


def _construct_compose_override(
    loader: _ComposeLoader, node: yaml.nodes.SequenceNode
) -> object:
    return loader.construct_sequence(node)


_ComposeLoader.add_constructor("!override", _construct_compose_override)


def _run_local_wal_guard(
    tmp_path: Path, *, archive_mode: str, archive_command: str = ""
) -> subprocess.CompletedProcess[str]:
    pgdata = tmp_path / "pgdata"
    (pgdata / "pg_wal").mkdir(parents=True)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _write_executable(
        bin_dir / "psql",
        """#!/usr/bin/env bash
set -eu
case "$*" in
  *'SHOW archive_mode'*) printf '%s\\n' "$TEST_ARCHIVE_MODE" ;;
  *'SHOW archive_command'*) printf '%s\\n' "$TEST_ARCHIVE_COMMAND" ;;
  *) exit 2 ;;
esac
""",
    )
    _write_executable(
        bin_dir / "du",
        """#!/usr/bin/env bash
printf '0\\t%s\\n' "$2"
""",
    )
    _write_executable(
        bin_dir / "df",
        """#!/usr/bin/env bash
printf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n'
printf 'tmpfs 100 10 90 10%% /tmp\\n'
""",
    )
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "PGDATA": str(pgdata),
            "TEST_ARCHIVE_MODE": archive_mode,
            "TEST_ARCHIVE_COMMAND": archive_command,
        }
    )
    return subprocess.run(
        ["bash", str(ROOT / "scripts/builderops/local_wal_guard.sh")],
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )


def test_local_wal_guard_accepts_postgresql_disabled_archive_mode(tmp_path: Path) -> None:
    result = _run_local_wal_guard(tmp_path, archive_mode="(disabled)")

    assert result.returncode == 0, result.stdout + result.stderr


def test_local_wal_guard_refuses_enabled_or_unexpected_archive_configuration(
    tmp_path: Path,
) -> None:
    for archive_mode in ("on", "always", "unknown"):
        enabled = _run_local_wal_guard(
            tmp_path / archive_mode, archive_mode=archive_mode
        )

        assert enabled.returncode == 70
        assert "archive drift" in enabled.stderr
    unexpected = _run_local_wal_guard(
        tmp_path / "unexpected", archive_mode="off", archive_command="wal-g wal-push %p"
    )

    assert unexpected.returncode == 70
    assert "archive_command=set" in unexpected.stderr


def _slot_wal_keep_size_assignments(config: str) -> list[str]:
    return re.findall(
        r"^\s*max_slot_wal_keep_size\s*=\s*['\"]?([^\s'#]+)['\"]?\s*(?:#.*)?$",
        config,
        flags=re.MULTILINE,
    )


def test_postgres_wal_limits_are_pinned() -> None:
    config = (ROOT / "config/builderops/postgresql.conf").read_text(encoding="utf-8")

    assert "max_wal_size = '2GB'" in config
    assert _slot_wal_keep_size_assignments(config) == ["2GB"]
    for drifted_value in ("1GB", "0", "3GB"):
        assert _slot_wal_keep_size_assignments(
            config.replace("max_slot_wal_keep_size = '2GB'", f"max_slot_wal_keep_size = '{drifted_value}'")
        ) != ["2GB"]
    assert _slot_wal_keep_size_assignments(
        config + "\nmax_slot_wal_keep_size = '3GB'\n"
    ) != ["2GB"]


def test_tars_profile_is_setup_specific_and_probe_truthful() -> None:
    profile = (ROOT / "docs/deployment/profiles/TARS_PROXMOX.md").read_text(
        encoding="utf-8"
    )
    normalized_profile = " ".join(profile.split())

    assert "does not qualify a host or authorize a deployment" in normalized_profile
    assert "fresh qualification input" in normalized_profile
    assert "required-but-not-yet-installed live prerequisite" in normalized_profile
    assert "macOS launchd" in normalized_profile
    assert "does not prove a Linux installation" in normalized_profile


def test_effective_builderops_compose_has_no_recovery_egress_or_wal_secrets() -> None:
    compose = (ROOT / "docker-compose.builderops.yml").read_text(encoding="utf-8")
    effective = yaml.load(compose, Loader=_ComposeLoader)
    deploy = (ROOT / "scripts/deploy_builderops.sh").read_text(encoding="utf-8")

    assert effective["networks"]["builderops-internal"]["internal"] is True
    services = effective["services"]
    assert all(
        service["networks"] == ["builderops-internal"]
        for service in services.values()
    )
    assert services["api"]["ports"] == [
        "127.0.0.1:${BUILDEROPS_API_PORT:-18100}:8000"
    ]
    assert all(
        name == "api" or "ports" not in service
        for name, service in services.items()
    )
    declared_secrets = effective["secrets"]
    assert not any(
        token in secret.lower()
        for secret in declared_secrets
        for token in ("wal", "archive", "recovery")
    )
    assert "recovery-target" not in compose
    assert 'BUILDEROPS_LOCAL_DURABILITY_MODE=rebuildable' in (
        ROOT / "config/deploy/builderops.env"
    ).read_text(encoding="utf-8")
    assert '"source_sha": os.environ["SOURCE_SHA"]' in deploy
    assert '"previous_image_digest": os.environ["PREVIOUS_DIGEST"]' in deploy


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _harness(tmp_path: Path) -> tuple[Path, dict[str, str], str, str, str]:
    root = tmp_path / "repo"
    for relative in (
        "scripts/lib/builderops_compose.sh",
        "scripts/deploy_builderops.sh",
        "scripts/builderops/configure_tailnet_tls.sh",
        "config/deploy/builderops.env",
        "docker-compose.builderops.yml",
        "app/builderops/control_plane/recovery.py",
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, destination)

    # Rollback is meaningful only after a real release has been installed.
    # The committed pin deliberately uses all-zero bootstrap placeholders,
    # which deploy_builderops.sh correctly refuses to preserve as a rollback
    # target. Seed the harness with a valid current release so the test proves
    # deploy -> rollback behavior rather than rollback-to-bootstrap behavior.
    pin_path = root / "config/deploy/builderops.env"
    pin_path.write_text(
        pin_path.read_text(encoding="utf-8")
        .replace("sha256:" + "0" * 64, "sha256:" + "d" * 64)
        .replace("0" * 40, "c" * 40),
        encoding="utf-8",
    )

    source_sha = "a" * 40
    digest = "sha256:" + "b" * 64
    postgres_digest = "sha256:" + "e" * 64
    candidate_receipt = tmp_path / "candidate-pair.json"
    candidate_receipt.write_text(
        json.dumps(
            {
                "receipt_version": 1,
                "repository": "RasmusTho/agentic-pkm-mvp",
                "workflow": ".github/workflows/app-image-build.yml",
                "event_name": "push",
                "source_ref": "refs/heads/main",
                "source_sha": source_sha,
                "control_plane_image_digest": digest,
                "postgres_walg_image_digest": postgres_digest,
                "restore_gate": "encrypted-full-backup-plus-archived-wal",
                "platform": "linux/amd64",
            }
        ),
        encoding="utf-8",
    )
    token_file = tmp_path / "probe-token"
    token_file.write_text("probe-secret", encoding="utf-8")
    receipt_dir = tmp_path / "receipts"
    event_log = tmp_path / "events.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    _write_executable(
        bin_dir / "gh",
        """#!/usr/bin/env bash
set -eu
printf 'gh %s\n' "$*" >> "$FAKE_EVENT_LOG"
[ "${FAKE_FAIL_ATTESTATION:-0}" != 1 ]
""",
    )
    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
set -eu
printf 'docker %s\n' "$*" >> "$FAKE_EVENT_LOG"
context=""
if [ "${1:-}" = "--context" ]; then context="$2"; shift 2; fi
if [ "${1:-}" = info ]; then
  [ "$context" = builderops ] && printf 'builder-engine\n' || printf 'product-engine\n'
elif [ "${1:-}" = compose ] && [ "${2:-}" = ls ]; then
  printf '[]\n'
elif [ "${FAKE_FAIL_PULL:-0}" = 1 ]; then
  case " $* " in
    *" pull "*) exit 19 ;;
  esac
fi
""",
    )
    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
set -eu
printf 'curl %s\n' "$*" >> "$FAKE_EVENT_LOG"
if [ -n "${FAKE_FAIL_READY_DIGEST:-}" ] && grep -q "$FAKE_FAIL_READY_DIGEST" "$BUILDEROPS_PIN_FILE"; then
  exit 22
fi
printf '{"ready":true,"database":{"schema_version":7,"authority_epoch":3}}\n'
""",
    )
    _write_executable(
        bin_dir / "tailscale",
        """#!/usr/bin/env bash
set -eu
printf 'tailscale %s\n' "$*" >> "$FAKE_EVENT_LOG"
if [ "${1:-}" = status ]; then
  printf '{"BackendState":"Running"}\n'
elif [ "${1:-}" = serve ] && [ "${2:-}" = status ]; then
  if [ "${FAKE_FUNNEL_ACTIVE:-0}" = 1 ]; then
    printf '{"AllowFunnel":{"443":true}}\n'
  else
    printf '{"AllowFunnel":false,"TCP":{"443":{"HTTPS":true}},"Web":{"builder.ts.net:443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:18100"}}}}}\n'
  fi
fi
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "FAKE_EVENT_LOG": str(event_log),
            "BUILDEROPS_PROBE_TOKEN_FILE": str(token_file),
            "BUILDEROPS_RECEIPT_DIR": str(receipt_dir),
            "BUILDEROPS_HEALTH_TIMEOUT_SECONDS": "1",
            "BUILDEROPS_TEST_CANDIDATE_RECEIPT": str(candidate_receipt),
        }
    )
    return root, env, source_sha, digest, postgres_digest


def test_deploy_and_rollback_receipts_bind_pin_schema_and_epoch(tmp_path: Path) -> None:
    root, env, source_sha, digest, postgres_digest = _harness(tmp_path)
    deploy = subprocess.run(
        [
            "bash",
            "scripts/deploy_builderops.sh",
            "deploy",
            env["BUILDEROPS_TEST_CANDIDATE_RECEIPT"],
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert deploy.returncode == 0, deploy.stdout + deploy.stderr

    receipt = json.loads((Path(env["BUILDEROPS_RECEIPT_DIR"]) / "latest.json").read_text())
    assert receipt["action"] == "deploy"
    assert receipt["project"] == "builderops-control-plane"
    assert receipt["engine_context"] == "builderops"
    assert receipt["engine_id"] == "builder-engine"
    assert receipt["source_sha"] == source_sha
    assert receipt["image_digest"] == digest
    assert receipt["postgres_walg_image_digest"] == postgres_digest
    assert receipt["schema_version"] == 7
    assert receipt["authority_epoch"] == 3
    assert receipt["database_restore_performed"] is False

    events = Path(env["FAKE_EVENT_LOG"]).read_text(encoding="utf-8")
    assert "probe-secret" not in events
    assert "Authorization: Bearer" not in events
    assert "-p builderops-control-plane" in events
    assert "up -d db" in events
    assert "tailscale serve --bg --yes --https=443 http://127.0.0.1:18100" in events
    assert "tailscale serve status --json" in events
    assert "up --abort-on-container-exit --exit-code-from migrate migrate" in events
    assert events.index("up -d db") < events.index(
        "up --abort-on-container-exit --exit-code-from migrate migrate"
    )
    migration_event = "up --abort-on-container-exit --exit-code-from migrate migrate"
    assert events.index(migration_event) < events.index("up -d --force-recreate api worker")
    pin = (root / "config/deploy/builderops.env").read_text(encoding="utf-8")
    assert pin.count("BUILDEROPS_POSTGRES_IMAGE_REPOSITORY=") == 1
    assert pin.count("BUILDEROPS_POSTGRES_IMAGE_DIGEST=sha256:") == 1
    assert pin.count("BUILDEROPS_LOCAL_DURABILITY_MODE=rebuildable") == 1
    assert "pg_restore" not in events

    rollback = subprocess.run(
        ["bash", "scripts/deploy_builderops.sh", "rollback"],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert rollback.returncode == 0, rollback.stdout + rollback.stderr
    rollback_receipt = json.loads(
        (Path(env["BUILDEROPS_RECEIPT_DIR"]) / "latest.json").read_text()
    )
    assert rollback_receipt["action"] == "rollback"
    assert rollback_receipt["database_restore_performed"] is False


def test_deploy_refuses_a_local_mode_that_would_require_recovery_egress(tmp_path: Path) -> None:
    root, env, _source_sha, _digest, _postgres_digest = _harness(tmp_path)
    env["BUILDEROPS_LOCAL_DURABILITY_MODE"] = "independent-recovery"

    result = subprocess.run(
        [
            "bash",
            "scripts/deploy_builderops.sh",
            "deploy",
            env["BUILDEROPS_TEST_CANDIDATE_RECEIPT"],
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "must be rebuildable" in result.stderr
    events = Path(env["FAKE_EVENT_LOG"]).read_text(encoding="utf-8")
    assert " pull " not in events
    assert " up " not in events

def test_failed_deploy_restores_canonical_pin_and_preserves_rollback_target(
    tmp_path: Path,
) -> None:
    root, env, source_sha, digest, postgres_digest = _harness(tmp_path)
    pin_path = root / "config/deploy/builderops.env"
    before = pin_path.read_text(encoding="utf-8")
    previous_path = root / "config/deploy/builderops.previous.env"
    env["FAKE_FAIL_PULL"] = "1"

    failed = subprocess.run(
        [
            "bash",
            "scripts/deploy_builderops.sh",
            "deploy",
            env["BUILDEROPS_TEST_CANDIDATE_RECEIPT"],
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert failed.returncode != 0
    assert pin_path.read_text(encoding="utf-8") == before
    assert not previous_path.exists()


def test_readiness_failure_reactivates_previous_live_release(tmp_path: Path) -> None:
    root, env, source_sha, digest, postgres_digest = _harness(tmp_path)
    pin_path = root / "config/deploy/builderops.env"
    before = pin_path.read_text(encoding="utf-8")
    env["FAKE_FAIL_READY_DIGEST"] = digest

    failed = subprocess.run(
        [
            "bash",
            "scripts/deploy_builderops.sh",
            "deploy",
            env["BUILDEROPS_TEST_CANDIDATE_RECEIPT"],
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert failed.returncode != 0
    assert pin_path.read_text(encoding="utf-8") == before
    events = Path(env["FAKE_EVENT_LOG"]).read_text(encoding="utf-8")
    assert events.count("up -d --force-recreate api worker") == 1
    assert events.count("up -d --force-recreate db api worker") == 1
    assert "previous pin and live API/worker release restored" in failed.stderr


def test_deploy_rejects_unattested_candidate_pair_before_docker(tmp_path: Path) -> None:
    root, env, source_sha, _digest, _postgres_digest = _harness(tmp_path)
    env["FAKE_FAIL_ATTESTATION"] = "1"
    result = subprocess.run(
        [
            "bash",
            "scripts/deploy_builderops.sh",
            "deploy",
            env["BUILDEROPS_TEST_CANDIDATE_RECEIPT"],
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    events = Path(env["FAKE_EVENT_LOG"]).read_text(encoding="utf-8")
    assert "gh attestation verify" in events
    assert "--source-ref refs/heads/main" in events
    assert f"--source-digest {source_sha}" in events
    assert "docker " not in events


def test_active_funnel_is_rejected_before_serve_mutation(tmp_path: Path) -> None:
    root, env, source_sha, digest, postgres_digest = _harness(tmp_path)
    env["FAKE_FUNNEL_ACTIVE"] = "1"

    result = subprocess.run(
        [
            "bash",
            "scripts/deploy_builderops.sh",
            "deploy",
            env["BUILDEROPS_TEST_CANDIDATE_RECEIPT"],
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    events = Path(env["FAKE_EVENT_LOG"]).read_text(encoding="utf-8")
    assert "tailscale serve status --json" in events
    assert "tailscale serve --bg" not in events
    assert " pull " not in events
    assert " up " not in events


def test_candidate_pair_receipt_provenance_is_strict_before_docker(tmp_path: Path) -> None:
    root, env, _source_sha, _digest, _postgres_digest = _harness(tmp_path)
    receipt_path = Path(env["BUILDEROPS_TEST_CANDIDATE_RECEIPT"])
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["source_ref"] = "refs/heads/untrusted"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    result = subprocess.run(
        [
            "bash",
            "scripts/deploy_builderops.sh",
            "deploy",
            str(receipt_path),
        ],
        cwd=root,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert not Path(env["FAKE_EVENT_LOG"]).exists()
