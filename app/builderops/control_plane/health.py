"""Secret-safe liveness, readiness, and status projection for BuilderOps."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from app.builderops.control_plane.auth import CredentialRateLimiter, CredentialRegistry
from app.builderops.control_plane.migrations import SCHEMA_VERSION
from app.builderops.control_plane.models import StorePort
from app.builderops.control_plane.recovery import RecoveryConfigurationError, load_recovery_target


@dataclass(frozen=True)
class OperationalStatus:
    outbox_pending: int = 0
    outbox_oldest_age_seconds: float = 0.0
    dead_letters: int = 0
    active_leases: int = 0
    lease_conflicts_total: int = 0
    rate_limit_enabled: bool = True
    rate_limit_rejections_total: int = 0
    executor_heartbeat_state: str = "unknown"
    recovery_pipeline_state: str = "unknown"
    recovery_target_independent: bool = False
    authority_threatening_outbox: bool = False


class OperationalStatusProvider(Protocol):
    def snapshot(self) -> OperationalStatus: ...


class FileOperationalStatusProvider:
    """Read an allowlisted rebuildable projection written by service workers."""

    def __init__(self, path: str | Path | None) -> None:
        self.path = Path(path) if path else None

    def snapshot(self) -> OperationalStatus:
        if self.path is None:
            return OperationalStatus()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return OperationalStatus()
        if not isinstance(raw, dict):
            return OperationalStatus()
        # Construct from an explicit allowlist. Unknown fields (including any
        # accidentally supplied credential material) can never reach status.
        return OperationalStatus(
            outbox_pending=max(0, int(raw.get("outbox_pending", 0))),
            outbox_oldest_age_seconds=max(0.0, float(raw.get("outbox_oldest_age_seconds", 0))),
            dead_letters=max(0, int(raw.get("dead_letters", 0))),
            active_leases=max(0, int(raw.get("active_leases", 0))),
            lease_conflicts_total=max(0, int(raw.get("lease_conflicts_total", 0))),
            rate_limit_enabled=bool(raw.get("rate_limit_enabled", True)),
            rate_limit_rejections_total=max(0, int(raw.get("rate_limit_rejections_total", 0))),
            executor_heartbeat_state=str(raw.get("executor_heartbeat_state", "unknown")),
            recovery_pipeline_state=str(raw.get("recovery_pipeline_state", "unknown")),
            recovery_target_independent=bool(raw.get("recovery_target_independent", False)),
            authority_threatening_outbox=bool(raw.get("authority_threatening_outbox", False)),
        )


class LiveOperationalStatusProvider:
    """Project live database, worker, and recovery state through a secret-safe allowlist."""

    def __init__(
        self,
        store: StorePort,
        *,
        recovery_target_file: str | Path,
        worker_heartbeat_file: str | Path,
        archive_lag_seconds: int = 900,
    ) -> None:
        self.store = store
        self.recovery_target_file = Path(recovery_target_file)
        self.worker_heartbeat_file = Path(worker_heartbeat_file)
        self.archive_lag_seconds = archive_lag_seconds

    def _recovery_target_independent(self) -> bool:
        try:
            load_recovery_target(self.recovery_target_file)
        except RecoveryConfigurationError:
            return False
        return True

    def _worker_state(self) -> str:
        heartbeat_reader = getattr(self.store, "service_heartbeat", None)
        try:
            if callable(heartbeat_reader):
                raw = heartbeat_reader("outbox-worker")
                if raw is None:
                    return "unknown"
            else:
                raw = json.loads(self.worker_heartbeat_file.read_text(encoding="utf-8"))
            observed = datetime.fromisoformat(str(raw["observed_at"]).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - observed.astimezone(timezone.utc)).total_seconds()
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return "unknown"
        return "healthy" if raw.get("state") == "running" and 0 <= age <= 45 else "stale"

    def snapshot(self) -> OperationalStatus:
        values: dict[str, Any] = {}
        connector = getattr(self.store, "_connect", None)
        if callable(connector):
            try:
                with connector() as conn:
                    row = conn.execute(
                        "SELECT "
                        "(SELECT count(*) FROM builderops_outbox WHERE status IN ('pending','claimed')) "
                        "AS outbox_pending, "
                        "(SELECT COALESCE(EXTRACT(epoch FROM clock_timestamp() - min(updated_at)), 0) "
                        "FROM builderops_outbox WHERE status IN ('pending','claimed')) AS oldest_age, "
                        "(SELECT count(*) FROM builderops_dead_letters) AS dead_letters, "
                        "(SELECT count(*) FROM builderops_leases WHERE expires_at > clock_timestamp()) "
                        "AS active_leases, "
                        "archiver.archived_count, archiver.failed_count, "
                        "archiver.last_archived_time, archiver.last_failed_time "
                        "FROM pg_stat_archiver AS archiver"
                    ).fetchone()
                    values = dict(row or {})
            except Exception:
                values = {}
        archived_at = values.get("last_archived_time")
        failed_at = values.get("last_failed_time")
        if failed_at is not None and (archived_at is None or failed_at > archived_at):
            recovery_state = "stalled"
        elif archived_at is None:
            recovery_state = "unknown"
        else:
            age = (datetime.now(timezone.utc) - archived_at.astimezone(timezone.utc)).total_seconds()
            recovery_state = "lagging" if age > self.archive_lag_seconds else "healthy"
        return OperationalStatus(
            outbox_pending=int(values.get("outbox_pending") or 0),
            outbox_oldest_age_seconds=float(values.get("oldest_age") or 0),
            dead_letters=int(values.get("dead_letters") or 0),
            active_leases=int(values.get("active_leases") or 0),
            executor_heartbeat_state=self._worker_state(),
            recovery_pipeline_state=recovery_state,
            recovery_target_independent=self._recovery_target_independent(),
        )


class HealthService:
    def __init__(
        self,
        store: StorePort,
        credentials: CredentialRegistry,
        operational: OperationalStatusProvider,
        rate_limiter: CredentialRateLimiter | None = None,
    ) -> None:
        self.store = store
        self.credentials = credentials
        self.operational = operational
        self.rate_limiter = rate_limiter

    @staticmethod
    def liveness() -> dict[str, bool]:
        return {"ok": True}

    def status(self) -> dict[str, Any]:
        database: dict[str, Any]
        try:
            readiness = self.store.readiness()
            database = {
                "available": True,
                "schema_version": int(readiness["schema_version"]),
                "authority_epoch": int(readiness["authority_epoch"]),
            }
        except Exception:
            database = {"available": False, "schema_version": None, "authority_epoch": None}
        runtime = self.operational.snapshot()
        expected_lineage = database["schema_version"] == SCHEMA_VERSION and bool(
            database["authority_epoch"] and database["authority_epoch"] > 0
        )
        ready = bool(
            database["available"]
            and expected_lineage
            and not runtime.authority_threatening_outbox
            and runtime.recovery_target_independent
        )
        rate_limit = (
            self.rate_limiter.status()
            if self.rate_limiter is not None
            else {
                "enabled": runtime.rate_limit_enabled,
                "rejections_total": runtime.rate_limit_rejections_total,
            }
        )
        return {
            "ready": ready,
            "database": database,
            "lineage": {
                "expected_schema_version": SCHEMA_VERSION,
                "authority_epoch_positive": bool(
                    database["authority_epoch"] and database["authority_epoch"] > 0
                ),
                "matches_release": expected_lineage,
            },
            "outbox": {
                "pending": runtime.outbox_pending,
                "oldest_age_seconds": runtime.outbox_oldest_age_seconds,
                "dead_letters": runtime.dead_letters,
                "authority_threatening": runtime.authority_threatening_outbox,
            },
            "leases": {
                "active": runtime.active_leases,
                "conflicts_total": runtime.lease_conflicts_total,
            },
            "auth": self.credentials.status(),
            "rate_limit": rate_limit,
            "executor_heartbeat": {"state": runtime.executor_heartbeat_state},
            "recovery_pipeline": {
                "state": runtime.recovery_pipeline_state,
                "target_independent": runtime.recovery_target_independent,
                "structural_ready": runtime.recovery_target_independent,
                "alert": runtime.recovery_pipeline_state
                in {"stalled", "lagging", "failed", "unknown", "misconfigured"},
                # Lag/stall is intentionally observable but not an ack/readiness
                # gate unless the recovery target is structurally co-resident.
                "acknowledgement_gate": False,
            },
        }


__all__ = [
    "FileOperationalStatusProvider",
    "HealthService",
    "LiveOperationalStatusProvider",
    "OperationalStatus",
    "OperationalStatusProvider",
]
