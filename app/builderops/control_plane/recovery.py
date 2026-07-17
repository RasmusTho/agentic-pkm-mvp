"""Secret-safe asynchronous recovery-pipeline contracts for BuilderOps."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


class RecoveryConfigurationError(ValueError):
    """Raised when recovery storage shares the primary failure domain."""


_LOCAL_HOSTS = frozenset({"", "localhost", "host.docker.internal", "127.0.0.1", "::1"})


@dataclass(frozen=True)
class RecoveryTarget:
    """Validated non-secret identity for an independently recoverable target."""

    url: str
    primary_failure_domain: str
    recovery_failure_domain: str
    encryption_key_ref: str
    custody_ref: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.url)
        if parsed.scheme.lower() not in {"s3", "gs", "azure"}:
            raise RecoveryConfigurationError("recovery target must use remote object storage")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise RecoveryConfigurationError(
                "recovery target identity must not embed credentials or query material"
            )
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if hostname in _LOCAL_HOSTS:
            raise RecoveryConfigurationError("recovery target is co-resident with the primary host")
        try:
            if ipaddress.ip_address(hostname).is_loopback:
                raise RecoveryConfigurationError("recovery target resolves to loopback")
        except ValueError:
            pass
        primary = self.primary_failure_domain.strip().lower()
        recovery = self.recovery_failure_domain.strip().lower()
        if not primary or not recovery or primary == recovery:
            raise RecoveryConfigurationError("recovery target must use an independent failure domain")
        if not self.encryption_key_ref.strip() or not self.custody_ref.strip():
            raise RecoveryConfigurationError("independent encryption and custody references are required")

    @property
    def fingerprint(self) -> str:
        """Return a stable identity without exposing URL credentials or query data."""
        parsed = urlsplit(self.url)
        safe_identity = f"{parsed.scheme.lower()}://{parsed.hostname or ''}{parsed.path}"
        return hashlib.sha256(safe_identity.encode()).hexdigest()


@dataclass(frozen=True)
class RecoveryStatus:
    """Bounded pipeline status; lag is alerting data, never an acknowledgement gate."""

    state: str
    target_fingerprint: str
    last_full_backup_at: datetime | None = None
    last_archived_wal_at: datetime | None = None
    lag_bytes: int | None = None
    consecutive_failures: int = 0
    reason_code: str = "ok"

    def __post_init__(self) -> None:
        if self.state not in {"healthy", "lagging", "stalled", "misconfigured", "unknown"}:
            raise ValueError("invalid recovery state")
        if self.lag_bytes is not None and self.lag_bytes < 0:
            raise ValueError("lag_bytes cannot be negative")
        if self.consecutive_failures < 0:
            raise ValueError("consecutive_failures cannot be negative")
        if not self.target_fingerprint or not self.reason_code:
            raise ValueError("target fingerprint and bounded reason code are required")

    @property
    def readiness_blocking(self) -> bool:
        """Only structural target misconfiguration blocks readiness."""
        return self.state == "misconfigured"

    @property
    def alerting(self) -> bool:
        return self.state in {"lagging", "stalled", "misconfigured", "unknown"}

    @property
    def lag_seconds(self) -> int | None:
        if self.last_archived_wal_at is None:
            return None
        observed = self.last_archived_wal_at
        if observed.tzinfo is None:
            observed = observed.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - observed).total_seconds()))

    def as_public_dict(self) -> dict[str, object]:
        return {
            "state": self.state,
            "target_fingerprint": self.target_fingerprint,
            "last_full_backup_at": (
                self.last_full_backup_at.isoformat() if self.last_full_backup_at else None
            ),
            "last_archived_wal_at": (
                self.last_archived_wal_at.isoformat() if self.last_archived_wal_at else None
            ),
            "lag_bytes": self.lag_bytes,
            "lag_seconds": self.lag_seconds,
            "consecutive_failures": self.consecutive_failures,
            "reason_code": self.reason_code,
            "alerting": self.alerting,
            "readiness_blocking": self.readiness_blocking,
        }


def load_recovery_target(path: str | Path, *, expected_url: str | None = None) -> RecoveryTarget:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError
        target = RecoveryTarget(
            url=str(raw["url"]),
            primary_failure_domain=str(raw["primary_failure_domain"]),
            recovery_failure_domain=str(raw["recovery_failure_domain"]),
            encryption_key_ref=str(raw["encryption_key_ref"]),
            custody_ref=str(raw["custody_ref"]),
        )
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RecoveryConfigurationError("recovery target configuration is unavailable") from exc
    if expected_url is not None and target.url != expected_url:
        raise RecoveryConfigurationError(
            "WAL archive target does not match the validated recovery target"
        )
    return target


def main(argv: list[str] | None = None) -> int:
    parser = ArgumentParser(description="Validate secret-safe BuilderOps recovery topology")
    parser.add_argument("target_file")
    parser.add_argument("--expected-url", required=True)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        target = load_recovery_target(args.target_file, expected_url=args.expected_url)
    except RecoveryConfigurationError as exc:
        parser.error(str(exc))
    print(json.dumps({"ok": True, "target_fingerprint": target.fingerprint}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
