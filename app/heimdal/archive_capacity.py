"""Aggregate-only capacity evidence for Heimdal's planned local archive (HAR-01).

The report is a rebuildable read model over raw-record metadata.  It never
reads raw paths, content identities, payloads, or decrypted bytes; its output
is deliberately limited to counts and encrypted-byte aggregates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.heimdal import raw_store
from app.heimdal.retention import RetentionWindowMissingError, resolve_retention_window_days

SCHEMA = "heimdal_archive_capacity.v1"
HOT_TIER_DAYS = 7


@dataclass(frozen=True)
class CapacityBucket:
    """A count-and-bytes aggregate for one age window."""

    record_count: int = 0
    encrypted_bytes: int = 0

    def add(self, encrypted_bytes: int) -> "CapacityBucket":
        return CapacityBucket(
            record_count=self.record_count + 1,
            encrypted_bytes=self.encrypted_bytes + encrypted_bytes,
        )

    def as_dict(self) -> dict[str, int]:
        return {
            "record_count": self.record_count,
            "encrypted_bytes": self.encrypted_bytes,
        }


@dataclass(frozen=True)
class CapacityAgeBuckets:
    """Aggregate inventory grouped by the archive's tiering windows."""

    hot_0_to_7_days: CapacityBucket
    archive_eligible: CapacityBucket
    expired: CapacityBucket

    def as_dict(self) -> dict[str, dict[str, int]]:
        return {
            "hot_0_to_7_days": self.hot_0_to_7_days.as_dict(),
            "archive_eligible": self.archive_eligible.as_dict(),
            "expired": self.expired.as_dict(),
        }


@dataclass(frozen=True)
class CapacityForecast:
    """Capacity projection derived from measured aggregate inventory.

    This is intentionally an inventory projection, not a made-up growth-rate
    extrapolation.  A short or empty observation window therefore reports its
    actual aggregate (including zero) without inferring future capture volume.
    """

    hot_tier_days: int
    retention_window_days: int
    hot_tier_encrypted_bytes: int
    archive_eligible_encrypted_bytes: int
    expired_encrypted_bytes: int

    def as_dict(self) -> dict[str, int]:
        return {
            "hot_tier_days": self.hot_tier_days,
            "retention_window_days": self.retention_window_days,
            "hot_tier_encrypted_bytes": self.hot_tier_encrypted_bytes,
            "archive_eligible_encrypted_bytes": self.archive_eligible_encrypted_bytes,
            "expired_encrypted_bytes": self.expired_encrypted_bytes,
        }


@dataclass(frozen=True)
class ArchiveCapacityReport:
    """A redacted, rebuildable capacity receipt with aggregate metadata only."""

    projected_at: datetime
    record_count: int
    encrypted_bytes_total: int
    age_buckets: CapacityAgeBuckets
    forecast: CapacityForecast

    def as_dict(self) -> dict[str, Any]:
        """Return the safe operator/health shape; no raw-record fields escape."""
        return {
            "schema": SCHEMA,
            "projected_at": self.projected_at.isoformat().replace("+00:00", "Z"),
            "record_count": self.record_count,
            "encrypted_bytes_total": self.encrypted_bytes_total,
            "age_buckets": self.age_buckets.as_dict(),
            "forecast": self.forecast.as_dict(),
        }


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def build_archive_capacity_report(
    vault_root: Path,
    *,
    now: datetime | None = None,
) -> ArchiveCapacityReport:
    """Build a fresh aggregate capacity report from the encrypted raw store.

    The retention value is resolved before reading inventory so a missing
    markdown-first policy fails loud instead of fabricating a tier forecast.
    """
    retention_window_days = resolve_retention_window_days(vault_root)
    projected_at = _as_utc(now) if now is not None else datetime.now(timezone.utc)

    hot = CapacityBucket()
    archive_eligible = CapacityBucket()
    expired = CapacityBucket()

    for record in raw_store.all_raw_record_capacity_metadata():
        # The raw-store query itself admits only encrypted storage size and
        # ingest time; raw paths, identities, payloads, and ciphertext never
        # enter this report process.
        encrypted_bytes = record.encrypted_bytes
        age_days = (projected_at - _as_utc(record.ingested_at)).total_seconds() / 86_400
        if age_days > retention_window_days:
            expired = expired.add(encrypted_bytes)
        elif age_days <= HOT_TIER_DAYS:
            hot = hot.add(encrypted_bytes)
        else:
            archive_eligible = archive_eligible.add(encrypted_bytes)

    age_buckets = CapacityAgeBuckets(
        hot_0_to_7_days=hot,
        archive_eligible=archive_eligible,
        expired=expired,
    )
    return ArchiveCapacityReport(
        projected_at=projected_at,
        record_count=hot.record_count + archive_eligible.record_count + expired.record_count,
        encrypted_bytes_total=hot.encrypted_bytes
        + archive_eligible.encrypted_bytes
        + expired.encrypted_bytes,
        age_buckets=age_buckets,
        forecast=CapacityForecast(
            hot_tier_days=HOT_TIER_DAYS,
            retention_window_days=retention_window_days,
            hot_tier_encrypted_bytes=hot.encrypted_bytes,
            archive_eligible_encrypted_bytes=archive_eligible.encrypted_bytes,
            expired_encrypted_bytes=expired.encrypted_bytes,
        ),
    )


__all__ = [
    "ArchiveCapacityReport",
    "CapacityAgeBuckets",
    "CapacityBucket",
    "CapacityForecast",
    "HOT_TIER_DAYS",
    "RetentionWindowMissingError",
    "build_archive_capacity_report",
]
