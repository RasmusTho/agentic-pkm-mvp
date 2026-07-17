from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


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
    secret_root = tmp_path / "secrets"
    secret_root.mkdir()
    (secret_root / "recovery-target.json").write_text(
        json.dumps(
            {
                "url": "s3://offsite.example.invalid/builderops",
                "primary_failure_domain": "builder-primary",
                "recovery_failure_domain": "operator-offsite",
                "encryption_key_ref": "kms:builderops-recovery",
                "custody_ref": "operator:independent",
            }
        ),
        encoding="utf-8",
    )
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
            "BUILDEROPS_SECRET_ROOT": str(secret_root),
            "BUILDEROPS_WALG_S3_PREFIX": "s3://offsite.example.invalid/builderops",
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
    root, env, _source_sha, _digest, _postgres_digest = _harness(tmp_path)
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
    events = Path(env["FAKE_EVENT_LOG"]).read_text(encoding="utf-8")
    assert "gh attestation verify" in events
    assert "docker " not in events
