from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql

from app.builderops.control_plane import AuthorityEnvelope, DurabilityPending, PostgresBuilderOpsStore


REPO_ROOT = Path(__file__).resolve().parents[2]
RESTORE = REPO_ROOT / "scripts" / "builderops" / "restore_drill.sh"


def _tool(path: Path, name: str, body: str) -> None:
    target = path / name
    target.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n{body}\n", encoding="utf-8")
    target.chmod(0o755)


def test_restore_from_backup_without_demerzel_secret_store(tmp_path: Path) -> None:
    """Exercise the restore orchestration with deterministic tool equivalents."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "calls.log"
    _tool(
        bin_dir,
        "wal-g",
        'printf "wal-g:%s\\n" "$*" >>"$CALLS"; '
        'if [[ "$1" == backup-fetch ]]; then mkdir -p "$2"; touch "$2/PG_VERSION"; fi',
    )
    _tool(bin_dir, "pg_ctl", 'printf "pg_ctl:%s\\n" "$*" >>"$CALLS"')
    _tool(
        bin_dir,
        "python",
        'printf "python:%s\\n" "$*" >>"$CALLS"; cat >"$PYTHON_STDIN"; '
        'printf \'{"authority_epoch": 2, "executor_enabled": false, '
        '"ok": true, "reconciliation_required": true, "schema_version": 2}\\n\'',
    )

    secrets = {
        "INDEPENDENT_AWS_ACCESS_KEY_ID_FILE": "independent-access",
        "INDEPENDENT_AWS_SECRET_ACCESS_KEY_FILE": "independent-secret",
        "INDEPENDENT_WALG_LIBSODIUM_KEY_FILE": "independent-recovery-key",
        "BUILDEROPS_DATABASE_URL_FILE": "postgresql://restore:password@127.0.0.1/restore",
    }
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "CALLS": str(calls),
            "PYTHON_STDIN": str(tmp_path / "restore-verifier.py"),
            "WALG_S3_PREFIX": "s3://offsite.example.invalid/builderops",
            "BUILDEROPS_RECOVERY_ID": "drill-20260716",
            "BUILDEROPS_RESTORE_REPOSITORY": "RasmusTho/agentic-pkm-mvp",
            "BUILDEROPS_RESTORE_SENTINEL_RECORD_ID": "wal-sentinel-3790",
            "DEMERZEL_SECRET_STORE_AVAILABLE": "0",
        }
    )
    for variable, value in secrets.items():
        secret_file = tmp_path / variable.lower()
        secret_file.write_text(value, encoding="utf-8")
        env[variable] = str(secret_file)

    restored = tmp_path / "restored"
    result = subprocess.run(
        ["bash", str(RESTORE), str(restored), "0/1600000"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    assert '"ok": true' in result.stdout
    assert '"executor_enabled": false' in result.stdout
    assert "backup-fetch" in calls.read_text(encoding="utf-8")
    recovery_config = (restored / "postgresql.auto.conf").read_text(encoding="utf-8")
    assert f"{REPO_ROOT}/scripts/builderops/wal_archive.sh fetch %f %p" in recovery_config
    assert "recovery_target_lsn = '0/1600000'" in recovery_config
    assert (restored / "recovery.signal").exists()
    call_log = calls.read_text(encoding="utf-8")
    assert "unix_socket_directories=" in call_log
    assert str(restored) in call_log
    verifier = Path(env["PYTHON_STDIN"]).read_text(encoding="utf-8")
    assert 'identity_conn.execute("SHOW data_directory")' in verifier
    assert "verification DSN is not bound" in verifier
    combined = result.stdout + result.stderr + call_log + recovery_config
    assert all(value not in combined for value in secrets.values())

    rejected = subprocess.run(
        ["bash", str(RESTORE), str(tmp_path / "rejected"), "0/1600000"],
        cwd=REPO_ROOT,
        env={**env, "PRIMARY_HOST_SECRET_STORE_AVAILABLE": "1"},
        capture_output=True,
        text=True,
    )
    assert rejected.returncode != 0
    assert "primary host secret store unavailable" in rejected.stderr


def test_real_encrypted_restore_selftest_is_a_required_image_gate() -> None:
    script = (REPO_ROOT / "scripts/builderops/real_restore_selftest.sh").read_text(
        encoding="utf-8"
    )
    workflow = (REPO_ROOT / ".github/workflows/app-image-build.yml").read_text(
        encoding="utf-8"
    )

    assert "wal-g backup-push" in script
    assert "wal-g backup-fetch" in script
    assert "pg_switch_wal" in script
    assert "wal-sentinel-3790" in script
    assert "activate_recovered_epoch" in script
    assert "reconciliation_required" in script
    assert "raw database credential leaked" in script
    assert "real_restore_selftest.sh" in workflow
    assert "Prove encrypted full-backup plus archived-WAL restore" in workflow


def _schema_dsn(dsn: str, schema: str) -> str:
    parts = urlsplit(dsn)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["options"] = f"-csearch_path={schema},public"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


@pytest.fixture
def recovery_store() -> Iterator[PostgresBuilderOpsStore]:
    # Explicit-or-nothing: this used to fall back to the production DSN (#4573).
    from app.db.dsn import resolve_dsn

    base_dsn = os.getenv("BUILDEROPS_DATABASE_URL", "").strip() or resolve_dsn()
    if not base_dsn:
        pytest.skip(
            "no control-plane database configured: set BUILDEROPS_DATABASE_URL "
            "(or DATABASE_URL) to an explicit non-production Postgres"
        )
    try:
        with psycopg.connect(base_dsn, connect_timeout=2, autocommit=True) as conn:
            schema = f"builderops_recovery_{uuid4().hex}"
            conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    except psycopg.Error as exc:
        pytest.skip(f"PostgreSQL unavailable for recovery integration test: {exc}")
    store = PostgresBuilderOpsStore(_schema_dsn(base_dsn, schema))
    store.initialize()
    try:
        yield store
    finally:
        with psycopg.connect(base_dsn, connect_timeout=2, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))


@pytest.mark.pg
def test_recovered_epoch_fences_leases_and_executor_until_reconciliation(
    recovery_store: PostgresBuilderOpsStore,
) -> None:
    envelope = AuthorityEnvelope(
        repository="RasmusTho/agentic-pkm-mvp",
        scope="issue:3790",
        stack="builderops-control-plane",
        actor="test:restore",
        source_refs=("github:issue:3790",),
    )
    recovery_store.commit_transition(
        envelope=envelope,
        task_id="restore-task",
        to_state="ready",
        idempotency_key="restore-create",
        request={"command": "create"},
    )
    _, lease = recovery_store.claim_task(
        envelope=envelope,
        task_id="restore-task",
        holder="pre-restore-worker",
        idempotency_key="restore-claim",
        request={"command": "claim"},
    )
    scheduled = recovery_store.commit_transition(
        envelope=envelope,
        task_id="restore-task",
        to_state="effect_pending",
        idempotency_key="restore-effect",
        request={"command": "effect"},
        outbox={"effect_type": "github.comment", "payload": {"issue": 3790}},
        lease=lease,
    )
    pre_restore_claim = recovery_store.claim_outbox(
        envelope=envelope,
        operation_key=scheduled.operation_key,
        worker_id="pre-restore-worker",
    )

    epoch = recovery_store.activate_recovered_epoch(
        recovery_id="restore-drill", restored_lsn=scheduled.recovery_lsn
    )
    assert epoch == 2
    assert recovery_store.activate_recovered_epoch(
        recovery_id="restore-drill", restored_lsn=scheduled.recovery_lsn
    ) == epoch
    assert recovery_store.readiness()["authority_epoch"] == 2
    recovery_store.initialize()
    assert recovery_store.readiness()["authority_epoch"] == 2
    state = recovery_store.recovery_state()
    assert state["reconciliation_required"] is True
    assert state["executor_enabled"] is False

    with pytest.raises(DurabilityPending, match="fenced"):
        recovery_store.claim_outbox(
            envelope=envelope,
            operation_key=scheduled.operation_key,
            worker_id="post-restore-worker",
        )

    with pytest.raises(RuntimeError, match="reconciliation gate"):
        recovery_store.complete_recovery_reconciliation(
            recovery_id="restore-drill", authority_epoch=epoch
        )
    recovery_store.reconcile_outbox(
        pre_restore_claim,
        observed_applied=False,
        evidence={"github_readback": "not_applied"},
    )
    recovery_store.complete_recovery_reconciliation(
        recovery_id="restore-drill", authority_epoch=epoch
    )
    assert recovery_store.recovery_state()["executor_enabled"] is True
