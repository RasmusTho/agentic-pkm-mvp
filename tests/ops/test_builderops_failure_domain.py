from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
import plistlib
from pathlib import Path

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


def test_builderops_probe_and_backup_are_independently_scheduled() -> None:
    root = Path(__file__).resolve().parents[2]
    unit_root = root / "ops/host-setup/mac-mini"
    with (unit_root / "com.yggdrasil.builderops-probe.plist").open("rb") as handle:
        probe = plistlib.load(handle)
    with (unit_root / "com.yggdrasil.builderops-backup.plist").open("rb") as handle:
        backup = plistlib.load(handle)
    assert probe["Label"] == "com.yggdrasil.builderops-probe"
    assert probe["StartInterval"] == 60
    assert probe["EnvironmentVariables"]["BUILDEROPS_PROBE_TOKEN_FILE"] == "__PROBE_TOKEN__"
    assert probe["EnvironmentVariables"]["BUILDEROPS_STATUS_TOKEN_FILE"] == "__STATUS_TOKEN__"
    assert backup["Label"] == "com.yggdrasil.builderops-backup"
    assert backup["StartInterval"] == 21600

    wrapper = (root / "scripts/builderops/scheduled_backup.sh").read_text(encoding="utf-8")
    installer = (unit_root / "install_builderops_units.sh").read_text(encoding="utf-8")
    assert "builderops_assert_failure_domain" in wrapper
    assert "--profile ops run --rm --no-deps backup" in wrapper
    assert "pkm-" not in wrapper
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
        return 200, {"recovery_pipeline": {"alerting": False}}

    monkeypatch.setattr(probe, "_get", fake_get)

    assert probe.run_probe() is True
    assert calls == [("/readyz", "health-only"), ("/status", "status-only")]
