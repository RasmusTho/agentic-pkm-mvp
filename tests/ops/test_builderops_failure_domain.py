from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import os
import plistlib
from pathlib import Path
import subprocess

import pytest

from app.builderops.control_plane.recovery import (
    RecoveryConfigurationError,
    RecoveryStatus,
    RecoveryTarget,
    load_recovery_target,
)


def test_builder_plane_survives_product_stack_lifecycle_and_alerts_on_stalled_archiving() -> None:
    """A1: archival stalls alert but cannot become an acknowledgement gate."""
    target = RecoveryTarget(
        url="s3://backup.example.invalid/builderops",
        primary_failure_domain="builder-primary-storage",
        recovery_failure_domain="offsite-object-storage",
        encryption_key_ref="secret-ref:builderops-recovery-key",
        custody_ref="custody:offline-operator-copy",
    )
    stalled = RecoveryStatus(
        state="stalled",
        target_fingerprint=target.fingerprint,
        last_archived_wal_at=datetime.now(timezone.utc) - timedelta(hours=2),
        lag_bytes=32 * 1024 * 1024,
        consecutive_failures=4,
        reason_code="wal_archive_stalled",
    )

    assert stalled.alerting is True
    assert stalled.readiness_blocking is False
    assert stalled.as_public_dict()["lag_seconds"] >= 60 * 60
    assert target.url not in str(stalled.as_public_dict())

    store_source = Path("app/builderops/control_plane/store.py").read_text(encoding="utf-8")
    assert "RecoveryStatus" not in store_source
    assert "recovery watermark" not in store_source.lower()

    for local_target in (
        "file:///Volumes/offsite/builderops",
        "s3://localhost/builderops",
        "s3://host.docker.internal/builderops",
        "s3://127.0.0.1/builderops",
    ):
        with pytest.raises(RecoveryConfigurationError):
            RecoveryTarget(
                url=local_target,
                primary_failure_domain="builder-primary",
                recovery_failure_domain="builder-primary",
                encryption_key_ref="secret-ref:key",
                custody_ref="custody:operator",
            )


def test_only_structural_recovery_misconfiguration_blocks_readiness() -> None:
    common = {"target_fingerprint": "f" * 64, "reason_code": "test"}
    for state in ("healthy", "lagging", "stalled", "unknown"):
        assert RecoveryStatus(state=state, **common).readiness_blocking is False
    assert RecoveryStatus(state="misconfigured", **common).readiness_blocking is True


def test_local_control_plane_wal_growth_or_archive_drift_is_loud(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    guard = root / "scripts/builderops/local_wal_guard.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    for command, source in {
        "psql": "#!/bin/sh\ncase \"$*\" in\n  *archive_mode*) printf '%s\\n' \"${FAKE_ARCHIVE_MODE:-off}\" ;;\n  *archive_command*) printf '%s\\n' \"${FAKE_ARCHIVE_COMMAND:-}\" ;;\nesac\n",
        "du": "#!/bin/sh\nprintf '%s %s\\n' \"${FAKE_WAL_BYTES:-0}\" \"$3\"\n",
        "df": "#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n/dev/test 100 10 90 %s%% /data\\n' \"${FAKE_DISK_USED_PERCENT:-10}\"\n",
    }.items():
        path = fake_bin / command
        path.write_text(source, encoding="utf-8")
        path.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PGDATA": str(tmp_path / "pgdata"),
        "POSTGRES_USER": "builderops_owner",
        "POSTGRES_DB": "builderops",
        "BUILDEROPS_LOCAL_WAL_MAX_BYTES": "100",
        "BUILDEROPS_LOCAL_DISK_MAX_USED_PERCENT": "85",
    }
    (tmp_path / "pgdata/pg_wal").mkdir(parents=True)

    healthy = subprocess.run([str(guard)], env=env, text=True, capture_output=True, check=False)
    assert healthy.returncode == 0

    for drift in (
        {"FAKE_ARCHIVE_MODE": "on"},
        {"FAKE_ARCHIVE_COMMAND": "wal-g wal-push %p"},
        {"FAKE_WAL_BYTES": "101"},
        {"FAKE_DISK_USED_PERCENT": "85"},
    ):
        result = subprocess.run(
            [str(guard)], env={**env, **drift}, text=True, capture_output=True, check=False
        )
        assert result.returncode != 0
        assert "local BuilderOps" in result.stderr


def test_wal_target_must_match_validated_recovery_identity(tmp_path: Path) -> None:
    target_file = tmp_path / "recovery-target.json"
    target_file.write_text(
        """{
          "url": "s3://offsite.example.invalid/builderops",
          "primary_failure_domain": "builder-primary",
          "recovery_failure_domain": "operator-offsite",
          "encryption_key_ref": "kms:builderops-recovery",
          "custody_ref": "operator:independent"
        }""",
        encoding="utf-8",
    )
    assert load_recovery_target(
        target_file,
        expected_url="s3://offsite.example.invalid/builderops",
    ).fingerprint
    with pytest.raises(RecoveryConfigurationError, match="does not match"):
        load_recovery_target(target_file, expected_url="s3://other.invalid/builderops")


def test_builderops_probe_alerts_on_the_local_database_guard() -> None:
    root = Path(__file__).resolve().parents[2]
    unit_root = root / "ops/host-setup/mac-mini"
    with (unit_root / "com.yggdrasil.builderops-probe.plist").open("rb") as handle:
        probe = plistlib.load(handle)
    assert probe["Label"] == "com.yggdrasil.builderops-probe"
    assert probe["StartInterval"] == 60
    assert probe["EnvironmentVariables"]["BUILDEROPS_PROBE_TOKEN_FILE"] == "__PROBE_TOKEN__"
    assert probe["EnvironmentVariables"]["BUILDEROPS_STATUS_TOKEN_FILE"] == "__STATUS_TOKEN__"
    assert probe["EnvironmentVariables"]["BUILDEROPS_DOCKER_CONTEXT"] == "__DOCKER_CONTEXT__"

    installer = (unit_root / "install_builderops_units.sh").read_text(encoding="utf-8")
    assert "com.yggdrasil.builderops-backup.plist" in installer
    assert "launchctl load \"$backup_plist\"" not in installer
    assert not (unit_root / "com.yggdrasil.builderops-backup.plist").exists()
    assert not (root / "scripts/builderops/scheduled_backup.sh").exists()
    assert "com.yggdrasil.prod-probe" not in installer


def test_builderops_probe_uses_separate_health_and_status_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[2]
    probe_path = root / "ops/host-setup/mac-mini/builderops_probe.py"
    spec = importlib.util.spec_from_file_location("builderops_probe_test", probe_path)
    assert spec is not None and spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    health_token = tmp_path / "health-token"
    status_token = tmp_path / "status-token"
    health_token.write_text("health-only\n", encoding="utf-8")
    status_token.write_text("status-only\n", encoding="utf-8")
    monkeypatch.setattr(probe, "TOKEN_FILE", health_token)
    monkeypatch.setattr(probe, "STATUS_TOKEN_FILE", status_token)
    monkeypatch.setattr(probe, "STATE_FILE", tmp_path / "probe-state.json")

    calls: list[tuple[str, str]] = []

    def fake_get(path: str, token: str) -> tuple[int, dict[str, object]]:
        calls.append((path, token))
        if path == "/readyz":
            return 200, {"ready": True}
        return 200, {"recovery_pipeline": {"alert": False}}

    monkeypatch.setattr(probe, "_get", fake_get)
    monkeypatch.setattr(probe, "_database_health_guard", lambda: True)

    assert probe.run_probe() is True
    assert calls == [("/readyz", "health-only"), ("/status", "status-only")]


def test_builderops_probe_consumes_the_service_recovery_alert_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[2]
    probe_path = root / "ops/host-setup/mac-mini/builderops_probe.py"
    spec = importlib.util.spec_from_file_location("builderops_probe_alert_test", probe_path)
    assert spec is not None and spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    health_token = tmp_path / "health-token"
    status_token = tmp_path / "status-token"
    health_token.write_text("health-only\n", encoding="utf-8")
    status_token.write_text("status-only\n", encoding="utf-8")
    monkeypatch.setattr(probe, "TOKEN_FILE", health_token)
    monkeypatch.setattr(probe, "STATUS_TOKEN_FILE", status_token)
    monkeypatch.setattr(probe, "STATE_FILE", tmp_path / "probe-state.json")
    monkeypatch.setattr(
        probe,
        "_get",
        lambda path, _token: (
            (200, {"ready": True})
            if path == "/readyz"
            else (200, {"recovery_pipeline": {"alert": True}})
        ),
    )
    monkeypatch.setattr(probe, "_database_health_guard", lambda: True)

    class Channel:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        def send(self, subject: str, body: str) -> None:
            self.messages.append((subject, body))

    channel = Channel()
    assert probe.run_probe(channel) is False
    assert channel.messages == [
        (
            "BuilderOps control plane down",
            "backup/WAL recovery pipeline is stalled or lagging",
        )
    ]


def test_builderops_probe_notifies_when_the_local_database_guard_is_unhealthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = Path(__file__).resolve().parents[2]
    probe_path = root / "ops/host-setup/mac-mini/builderops_probe.py"
    spec = importlib.util.spec_from_file_location("builderops_probe_guard_test", probe_path)
    assert spec is not None and spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)

    health_token = tmp_path / "health-token"
    status_token = tmp_path / "status-token"
    health_token.write_text("health-only\n", encoding="utf-8")
    status_token.write_text("status-only\n", encoding="utf-8")
    monkeypatch.setattr(probe, "TOKEN_FILE", health_token)
    monkeypatch.setattr(probe, "STATUS_TOKEN_FILE", status_token)
    monkeypatch.setattr(probe, "STATE_FILE", tmp_path / "probe-state.json")
    monkeypatch.setattr(
        probe,
        "_get",
        lambda path, _token: (200, {"ready": True, "recovery_pipeline": {"alert": False}}),
    )
    monkeypatch.setattr(probe, "_database_health_guard", lambda: False)

    class Channel:
        def __init__(self) -> None:
            self.messages: list[tuple[str, str]] = []

        def send(self, subject: str, body: str) -> None:
            self.messages.append((subject, body))

    channel = Channel()
    assert probe.run_probe(channel) is False
    assert channel.messages == [
        ("BuilderOps control plane down", "local database health guard is unhealthy")
    ]
