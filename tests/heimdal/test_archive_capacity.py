"""Aggregate-only capacity evidence for the Heimdal local archive (HAR-01)."""

from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from app.cli import cli
from app.heimdal import raw_store
from app.heimdal.archive_capacity import (
    ArchiveCapacityReport,
    RetentionWindowMissingError,
    build_archive_capacity_report,
)
from app.heimdal.raw_store import (
    RawRecordCapacityMetadata,
    encrypt_raw_bytes,
    insert_raw_record,
    reset_memory_raw_store,
)
from app.heimdal.settings_notes import SETTINGS, SettingsNote, write_settings_note
from app.write_guard import WriteGuard

pytestmark = pytest.mark.not_pg

_TEST_KEY = bytes.fromhex(secrets.token_hex(32))


@pytest.fixture(autouse=True)
def _reset_backends(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("STORE_BACKEND", "memory")
    reset_memory_raw_store()
    yield
    reset_memory_raw_store()


def _allowing_guard() -> WriteGuard:
    return WriteGuard(lambda: {"state": "healthy"})


def _vault(tmp_path: Path, *, retention_days: int | None = 30) -> Path:
    vault_root = tmp_path / "vault"
    vault_root.mkdir()
    if retention_days is not None:
        write_settings_note(
            vault_root,
            SettingsNote(spec=SETTINGS, values={"retention_window_days": retention_days}),
            write_guard=_allowing_guard(),
        )
    return vault_root


def _record(content_identity: str, payload: bytes):
    ciphertext, nonce = encrypt_raw_bytes(payload, key=_TEST_KEY)
    record, created = insert_raw_record(
        content_identity=content_identity,
        capture_chain=["test"],
        sensor={"sensor_id": "test"},
        consent={"grant_ref": "self-record"},
        ciphertext=ciphertext,
        nonce=nonce,
        key_ref="test",
        source_path="private-recording.m4a",
    )
    assert created
    return record


def test_capacity_receipt_contains_aggregates_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 7, 29, tzinfo=timezone.utc)
    record = _record("private-content-hash", b"secret spoken words")
    monkeypatch.setattr(
        raw_store,
        "all_raw_record_capacity_metadata",
        lambda: [
            RawRecordCapacityMetadata(
                ingested_at=now - timedelta(days=2), encrypted_bytes=len(record.ciphertext)
            )
        ],
    )
    monkeypatch.setattr(
        raw_store,
        "all_raw_records",
        lambda: pytest.fail("capacity reporting must not materialize raw records"),
    )

    report = build_archive_capacity_report(_vault(tmp_path), now=now)
    receipt = report.as_dict()

    assert isinstance(report, ArchiveCapacityReport)
    assert receipt["record_count"] == 1
    assert receipt["encrypted_bytes_total"] == len(record.ciphertext)
    assert set(receipt) == {
        "schema",
        "projected_at",
        "record_count",
        "encrypted_bytes_total",
        "age_buckets",
        "forecast",
    }
    assert set(receipt["age_buckets"]["hot_0_to_7_days"]) == {"record_count", "encrypted_bytes"}
    assert "private-recording.m4a" not in repr(receipt)
    assert "private-content-hash" not in repr(receipt)
    assert "secret spoken words" not in repr(receipt)
    assert "source_path" not in repr(receipt)
    assert "content_identity" not in repr(receipt)
    assert "payload" not in repr(receipt)


def test_capacity_forecast_uses_hot_and_retention_windows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 7, 29, tzinfo=timezone.utc)
    hot = _record("hot", b"a" * 10)
    archive = _record("archive", b"b" * 20)
    expired = _record("expired", b"c" * 30)
    monkeypatch.setattr(
        raw_store,
        "all_raw_record_capacity_metadata",
        lambda: [
            RawRecordCapacityMetadata(now - timedelta(days=7), len(hot.ciphertext)),
            RawRecordCapacityMetadata(now - timedelta(days=8), len(archive.ciphertext)),
            RawRecordCapacityMetadata(now - timedelta(days=31), len(expired.ciphertext)),
        ],
    )

    report = build_archive_capacity_report(_vault(tmp_path, retention_days=30), now=now)

    assert report.forecast.hot_tier_days == 7
    assert report.forecast.retention_window_days == 30
    assert report.forecast.hot_tier_encrypted_bytes == len(hot.ciphertext)
    assert report.forecast.archive_eligible_encrypted_bytes == len(archive.ciphertext)
    assert report.age_buckets.expired.record_count == 1
    assert report.forecast.expired_encrypted_bytes == len(expired.ciphertext)


def test_capacity_forecast_requires_retention_setting(tmp_path: Path) -> None:
    with pytest.raises(RetentionWindowMissingError, match="retention_window_days"):
        build_archive_capacity_report(_vault(tmp_path, retention_days=None))


def test_capacity_forecast_does_not_extend_a_shorter_retention_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime(2026, 7, 29, tzinfo=timezone.utc)
    expired = _record("past-short-retention", b"d" * 10)
    monkeypatch.setattr(
        raw_store,
        "all_raw_record_capacity_metadata",
        lambda: [
            RawRecordCapacityMetadata(
                ingested_at=now - timedelta(days=4), encrypted_bytes=len(expired.ciphertext)
            )
        ],
    )

    report = build_archive_capacity_report(_vault(tmp_path, retention_days=3), now=now)

    assert report.forecast.hot_tier_encrypted_bytes == 0
    assert report.forecast.archive_eligible_encrypted_bytes == 0
    assert report.forecast.expired_encrypted_bytes == len(expired.ciphertext)


def test_capacity_receipt_is_emitted_on_the_heimdal_operator_surface(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(timezone.utc)
    record = _record("operator-surface", b"recording payload")
    monkeypatch.setattr(
        raw_store,
        "all_raw_record_capacity_metadata",
        lambda: [RawRecordCapacityMetadata(now, len(record.ciphertext))],
    )

    result = CliRunner().invoke(cli, ["heimdal", "capacity", "--vault-root", str(_vault(tmp_path))])

    assert result.exit_code == 0, result.output
    receipt = json.loads(result.output)
    assert receipt["schema"] == "heimdal_archive_capacity.v1"
    assert receipt["record_count"] == 1
    assert "operator-surface" not in result.output
    assert "recording payload" not in result.output
