from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.builderops.control_plane import AuthorityObjectResult
from app.builderops.control_plane.auth import CredentialRegistry
from app.builderops.control_plane.recovery import (
    RecoveryConfigurationError,
    RecoveryStatus,
    RecoveryTarget,
)
from app.builderops.control_plane.service import create_app


REPO_ROOT = Path(__file__).resolve().parents[2]


def _fake_walg(bin_dir: Path) -> None:
    tool = bin_dir / "wal-g"
    tool.write_text(
        "#!/usr/bin/env bash\nset -euo pipefail\nprintf '%s\\n' \"$*\" >>\"$CALLS\"\n",
        encoding="utf-8",
    )
    tool.chmod(0o755)


def test_raw_credentials_never_enter_durable_state_or_restored_backup(tmp_path: Path) -> None:
    canaries = {
        "client": "bcp-client-RAW-3790",
        "database": "bcp-db-RAW-3790",
        "github": "bcp-github-RAW-3790",
        "model": "bcp-model-RAW-3790",
        "recovery": "bcp-recovery-RAW-3790",
    }

    class PersistingStore:
        def __init__(self) -> None:
            self.persisted: list[dict[str, object]] = []

        def commit_record(self, **kwargs):  # type: ignore[no-untyped-def]
            self.persisted.append(dict(kwargs["payload"]))
            return AuthorityObjectResult(
                repository=kwargs["envelope"].repository,
                object_kind="record",
                object_id=kwargs["record_id"],
                state=kwargs["state"],
                receipt_sequence=1,
                recovery_lsn="0/1",
            )

    client_secret = tmp_path / "client-token"
    client_secret.write_text(canaries["client"], encoding="utf-8")
    manifest = tmp_path / "credential-manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "credentials": [
                    {
                        "id": "client",
                        "principal": "client:secret-scan",
                        "secret_ref": "keychain:builderops/client",
                        "secret_file": str(client_secret),
                        "scopes": ["records:write"],
                        "repositories": ["RasmusTho/agentic-pkm-mvp"],
                        "rotation_generation": 1,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    store = PersistingStore()
    api = TestClient(
        create_app(store=store, credentials=CredentialRegistry(manifest))  # type: ignore[arg-type]
    )
    base_record = {
        "envelope": {
            "repository": "RasmusTho/agentic-pkm-mvp",
            "scope": "issue:3790",
            "stack": "builderops-control-plane",
            "source_refs": ["github:issue:3790"],
        },
        "record_id": "secret-scan",
        "record_type": "BuilderOpsReceipt",
        "state": "active",
    }
    headers = {"Authorization": f"Bearer {canaries['client']}"}
    unsafe_payloads = (
        {"summary": canaries["client"]},
        {"summary": f"prefix {canaries['client']} suffix"},
        {"summary": "prefix github_pat_RAW-3790 suffix"},
        {"summary": "database postgresql://app:RAW-3790@db/builderops value"},
        {"database_url": canaries["database"]},
        {"github_token": canaries["github"]},
        {"model_api_key": canaries["model"]},
        {"recovery_secret": canaries["recovery"]},
    )
    for index, payload in enumerate(unsafe_payloads):
        response = api.post(
            "/v1/records",
            headers=headers,
            json={
                **base_record,
                "payload": payload,
                "idempotency_key": f"reject-secret-{index}",
            },
        )
        assert response.status_code == 400
        assert all(secret not in response.text for secret in canaries.values())
    assert store.persisted == []

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_walg(bin_dir)
    calls = tmp_path / "calls.log"
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    wal = pgdata / "000000010000000000000001"
    wal.write_bytes(b"wal-without-credentials")
    files: dict[str, Path] = {}
    for name in ("access", "object_secret", "recovery"):
        path = tmp_path / name
        path.write_text(canaries["recovery"] if name == "recovery" else canaries["database"])
        files[name] = path

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "CALLS": str(calls),
            "PGDATA": str(pgdata),
            "WALG_S3_PREFIX": "s3://offsite.example.invalid/builderops",
            "AWS_ACCESS_KEY_ID_FILE": str(files["access"]),
            "AWS_SECRET_ACCESS_KEY_FILE": str(files["object_secret"]),
            "WALG_LIBSODIUM_KEY_FILE": str(files["recovery"]),
        }
    )
    outputs = []
    for command in (
        ["bash", "scripts/builderops/backup.sh"],
        ["bash", "scripts/builderops/wal_archive.sh", "push", str(wal)],
    ):
        completed = subprocess.run(
            command, cwd=REPO_ROOT, env=env, capture_output=True, text=True, check=True
        )
        outputs.append(completed.stdout + completed.stderr)

    with pytest.raises(RecoveryConfigurationError):
        RecoveryTarget(
            url="s3://user:query-secret@offsite.example.invalid/builderops?token=hidden",
            primary_failure_domain="builder-primary",
            recovery_failure_domain="offsite",
            encryption_key_ref="secret-ref:recovery",
            custody_ref="custody:operator",
        )
    target = RecoveryTarget(
        url="s3://offsite.example.invalid/builderops",
        primary_failure_domain="builder-primary",
        recovery_failure_domain="offsite",
        encryption_key_ref="secret-ref:recovery",
        custody_ref="custody:operator",
    )
    public = str(
        RecoveryStatus(state="healthy", target_fingerprint=target.fingerprint).as_public_dict()
    )
    durable_equivalents = "".join(outputs) + calls.read_text(encoding="utf-8") + public
    assert "query-secret" not in durable_equivalents
    assert "token=hidden" not in durable_equivalents
    assert all(secret not in durable_equivalents for secret in canaries.values())
    assert "backup-push" in durable_equivalents
    assert "delete retain FULL 14 --confirm" in durable_equivalents
    assert "wal-push" in durable_equivalents
