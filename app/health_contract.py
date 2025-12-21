from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.cli.events_doctor import event_name, latest_trace_story, normalize_timestamp, read_outbox
from app.config.paths import resolve_vault_root
from app.index.doctor import diagnose_index
from app.settings.health_settings import HealthThresholds, load_health_settings


@dataclass
class HealthStateMachine:
    state: str = "boot"
    reason: str = "initializing"
    since: datetime = field(default_factory=lambda: datetime.now(UTC))  # noqa: UP017
    bad_counter: int = 0
    good_counter: int = 0

    def reset(self) -> None:
        self.state = "boot"
        self.reason = "initializing"
        self.since = datetime.now(UTC)  # noqa: UP017
        self.bad_counter = 0
        self.good_counter = 0

    def update(
        self,
        age: float,
        thresholds: HealthThresholds,
        *,
        now: datetime | None = None,
    ) -> tuple[str, str, str]:
        now = now or datetime.now(UTC)  # noqa: UP017
        prev_state = self.state
        next_state = self.state
        reason = self.reason
        degrade_limit = thresholds.outbox_degrade_oldest_age_s
        recover_limit = thresholds.outbox_recover_oldest_age_s
        degrade_samples = thresholds.degrade_samples
        recover_samples = thresholds.recover_samples

        if age > degrade_limit:
            self.bad_counter += 1
            self.good_counter = 0
            if self.bad_counter >= degrade_samples:
                next_state = "degraded"
                reason = f"outbox lag {age:.1f}s exceeded {degrade_limit}s"
            else:
                next_state = "catch_up"
                reason = f"catching up (lag {age:.1f}s)"
        elif age < recover_limit:
            self.good_counter += 1
            self.bad_counter = 0
            if self.state in {"degraded", "recovery"}:
                if self.good_counter >= recover_samples:
                    next_state = "running"
                    reason = "outbox lag recovered"
                else:
                    next_state = "recovery"
                    reason = "recovering (lag improving)"
            else:
                next_state = "running"
                reason = "operational"
        else:
            self.bad_counter = 0
            self.good_counter = 0
            next_state = "running"
            reason = "normal"

        if next_state != prev_state or reason != self.reason:
            self.state = next_state
            self.reason = reason
            self.since = now
        return self.state, self.reason, self.since.isoformat()


class HealthContract:
    def __init__(
        self,
        *,
        state_machine: HealthStateMachine | None = None,
        now_fn: Callable[[], datetime] | None = None,
        vault_root_fn: Callable[[], Path] | None = None,
    ):
        self.state_machine = state_machine or HealthStateMachine()
        self.now_fn = now_fn or (lambda: datetime.now(UTC))  # noqa: UP017
        self.vault_root_fn = vault_root_fn or resolve_vault_root

    def evaluate(self) -> dict[str, Any]:
        now = self.now_fn()
        vault_root = self.vault_root_fn()
        settings_result = load_health_settings(vault_root=vault_root)
        records = read_outbox()
        outbox_count = len(records)
        oldest_ts = self._earliest_timestamp(records)
        age = self._compute_age(oldest_ts, now)
        state, reason, since_ts = self.state_machine.update(
            age,
            settings_result.settings.thresholds,
            now=now,
        )
        index_result = diagnose_index()
        index_status = self._summary_status(
            index_result.get("issues"), index_result.get("warnings")
        )
        events_status = self._events_status(records)
        errors = self._count_errors(records, now)
        return {
            "state": state,
            "reason": reason,
            "since_ts": since_ts,
            "outbox_count": outbox_count,
            "outbox_oldest_age_s": age,
            "embedding_identity": {
                "backend": index_result.get("backend"),
                "expected_identity": index_result.get("expected_identity"),
                "stored_identity": index_result.get("stored_identity"),
            },
            "index_doctor_status": index_status,
            "events_doctor_status": events_status,
            "errors_last_10m": errors,
            "settings_status": settings_result.status,
            "settings_source": settings_result.source.to_payload(),
            "settings_errors": settings_result.errors,
            "thresholds": settings_result.settings.thresholds.to_payload(),
        }

    def _earliest_timestamp(self, records: Iterable[dict[str, Any]]) -> datetime | None:
        earliest: datetime | None = None
        for rec in records:
            value = normalize_timestamp(rec)
            ts = self._parse_timestamp(value)
            if ts is None:
                continue
            if earliest is None or ts < earliest:
                earliest = ts
        return earliest

    def _compute_age(self, ts: datetime | None, now: datetime) -> float:
        if ts is None:
            return 0.0
        delta = now - ts
        return max(delta.total_seconds(), 0.0)

    def _parse_timestamp(self, value: str) -> datetime | None:
        if not value:
            return None
        text = value.strip()
        if text.endswith("Z") and not text.endswith("+00:00"):
            text = text[:-1] + "+00:00"
        try:
            return datetime.fromisoformat(text)
        except Exception:
            return None

    def _summary_status(self, issues: Any, warnings: Any) -> str:
        if issues:
            return "fail"
        if warnings:
            return "warn"
        return "pass"

    def _events_status(self, records: Iterable[dict[str, Any]]) -> str:
        rows = list(records)
        if not rows:
            return "warn"
        story = latest_trace_story(rows)
        if story.get("count", 0) > 0:
            return "pass"
        return "warn"

    def _count_errors(self, records: Iterable[dict[str, Any]], now: datetime) -> int | None:
        cutoff = now - timedelta(minutes=10)
        errors = 0
        seen = False
        for rec in records:
            seen = True
            ts = self._parse_timestamp(normalize_timestamp(rec))
            if ts is None:
                continue
            if ts < cutoff:
                continue
            name = event_name(rec).lower()
            if "error" in name:
                errors += 1
        return errors if seen else None


GLOBAL_STATE_MACHINE = HealthStateMachine()
DEFAULT_CONTRACT = HealthContract(state_machine=GLOBAL_STATE_MACHINE)


def reset_state_machine() -> None:
    GLOBAL_STATE_MACHINE.reset()


__all__ = [
    "HealthStateMachine",
    "GLOBAL_STATE_MACHINE",
    "DEFAULT_CONTRACT",
    "HealthContract",
    "reset_state_machine",
]
